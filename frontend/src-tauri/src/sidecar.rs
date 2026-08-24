//! Sidecar 进程管理（阶段 6，见 3.12 / 3.13）。
//!
//! 职责：
//! - 选空闲端口 + 生成随机 token
//! - spawn 后端进程（python backend_service 或 backend_service.exe）
//! - 读取 stdout 直到 `BACKEND_READY {...}` marker
//! - 持有 child 句柄供 check_alive / kill / restart

use std::collections::HashMap;
use std::path::PathBuf;
use std::process::Stdio;
use std::sync::Arc;
use std::time::Duration;

use rand::RngCore;
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::{Child, Command};
use tokio::sync::Mutex;

use crate::BackendInfo;

/// marker 前缀（与 backend_service/app.py 对齐）。
const MARKER_PREFIX: &str = "BACKEND_READY ";

/// sidecar 等待 marker 上限。
const READY_TIMEOUT: Duration = Duration::from_secs(15);

pub struct SidecarManager {
    child: Arc<Mutex<Option<Child>>>,
    /// 当前 sidecar 的端口/token（最近一次握手成功值）。
    current: Arc<Mutex<Option<BackendInfo>>>,
}

impl SidecarManager {
    pub fn new() -> Self {
        Self {
            child: Arc::new(Mutex::new(None)),
            current: Arc::new(Mutex::new(None)),
        }
    }

    /// 选空闲端口 + 生成 token + spawn 后端进程。
    pub async fn start(&self) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
        // BACKEND_EXTERNAL 模式：不 spawn 进程，直接连外部后端（PyCharm Debug）
        // 端口固定 8765，token 为空（dev 模式跳过校验）
        if std::env::var("BACKEND_EXTERNAL").is_ok() {
            let port: u16 = std::env::var("BACKEND_PORT")
                .ok()
                .and_then(|s| s.parse().ok())
                .unwrap_or(8765);
            log::info!("[sidecar] BACKEND_EXTERNAL 模式：连外部后端 127.0.0.1:{port}");
            let info = BackendInfo {
                base_url: format!("http://127.0.0.1:{port}"),
                ws_url: format!("ws://127.0.0.1:{port}/ws"),
                token: String::new(),
                ready: true,
            };
            *self.current.lock().await = Some(info);
            return Ok(());
        }

        let port = pick_free_port()?;
        let token = random_token();

        log::info!("[sidecar] 启动后端: port={port}, token={token}");

        let (program, args) = resolve_backend_command(port, &token)?;
        log::info!("[sidecar] 命令: {program} {}", args.join(" "));

        // BACKEND_DEV 模式：Tauri 在 frontend/ 下运行，但 Python 模块在项目根目录
        // 需要把 current_dir 切到项目根（frontend 的父级）并确保 PYTHONPATH 包含根目录
        let is_backend_dev = std::env::var("BACKEND_DEV").is_ok();
        let project_root = if is_backend_dev {
            // CARGO_MANIFEST_DIR = .../frontend/src-tauri → ../../ 即项目根
            let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
            let root = manifest.join("..").join("..").canonicalize().ok();
            log::info!("[sidecar] BACKEND_DEV 模式，项目根: {:?}", root);
            root
        } else {
            None
        };

        let mut cmd = Command::new(&program);
        cmd.args(&args)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(true);
        if let (true, Some(root)) = (is_backend_dev, project_root.as_ref()) {
            cmd.current_dir(root);
            // PYTHONPATH = 项目根 + 现有值
            let existing_pythonpath = std::env::var("PYTHONPATH").unwrap_or_default();
            let mut paths: Vec<String> = vec![root.to_string_lossy().into_owned()];
            if !existing_pythonpath.is_empty() {
                paths.push(existing_pythonpath);
            }
            let sep = if cfg!(windows) { ";" } else { ":" };
            cmd.env("PYTHONPATH", paths.join(sep));
            log::info!("[sidecar] 设置 PYTHONPATH={}", paths.join(sep));
        }

        let mut child = cmd.spawn()?;

        // 拿 stdout/stderr 句柄后立即归还 child（pipe 已取走）
        let stdout = child.stdout.take().expect("stdout piped");
        let stderr = child.stderr.take().expect("stderr piped");

        // stderr 转发到 Rust 日志（不解析）
        tokio::spawn(async move {
            let mut reader = BufReader::new(stderr).lines();
            while let Ok(Some(line)) = reader.next_line().await {
                log::info!("[backend:stderr] {line}");
            }
        });

        // 立即把 child 存入（即使 marker 还没读到；check_alive 会用）
        *self.child.lock().await = Some(child);

        // 同步读 stdout 直到 marker（在 wait_for_ready 里做），这里把 stdout 转入解析循环
        let current = self.current.clone();
        let child_lock = self.child.clone();
        tokio::spawn(async move {
            if let Err(e) = read_stdout_until_marker(stdout, port, &token, &current).await {
                log::error!("[sidecar] marker 读取失败: {e}");
                // 读取失败 → 标记 child 已死
                let mut c = child_lock.lock().await;
                if let Some(mut child) = c.take() {
                    let _ = child.kill().await;
                }
            }
        });

        Ok(())
    }

    /// 阻塞等待 marker（最长 READY_TIMEOUT）。
    pub async fn wait_for_ready(
        &self,
        timeout: Duration,
    ) -> Result<BackendInfo, Box<dyn std::error::Error + Send + Sync>> {
        let deadline = tokio::time::Instant::now() + timeout;
        loop {
            if let Some(info) = self.current.lock().await.clone() {
                return Ok(info);
            }
            if tokio::time::Instant::now() >= deadline {
                return Err("等待 BACKEND_READY marker 超时".into());
            }
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
    }

    /// sidecar 进程是否仍存活。
    pub async fn check_alive(&self) -> Result<bool, Box<dyn std::error::Error + Send + Sync>> {
        // BACKEND_EXTERNAL 模式：不管理进程，永远返回 true（健康检查靠 HTTP 轮询）
        if std::env::var("BACKEND_EXTERNAL").is_ok() {
            return Ok(true);
        }
        let mut guard = self.child.lock().await;
        if let Some(child) = guard.as_mut() {
            match child.try_wait() {
                Ok(None) => Ok(true),
                Ok(Some(_)) => {
                    // 进程已退出，清理
                    *guard = None;
                    *self.current.lock().await = None;
                    Ok(false)
                }
                Err(e) => Err(e.into()),
            }
        } else {
            Ok(false)
        }
    }

    /// 停止 sidecar。
    ///
    /// Windows 下后端被强杀时 Python 的 shutdown 钩子不会执行，
    /// 悬浮球等 spawn 出来的孙进程会残留（无父进程存活监测），
    /// 因此先用 `taskkill /F /T` 终止整个进程树，失败再回退 `child.kill()`。
    pub async fn stop(&self) {
        let mut guard = self.child.lock().await;
        if let Some(mut child) = guard.take() {
            log::info!("[sidecar] 停止后端进程");
            let tree_killed = kill_process_tree(&mut child).await;
            if !tree_killed {
                let _ = child.kill().await;
            }
        }
        *self.current.lock().await = None;
    }

    /// 重启：stop + start。
    pub async fn restart(&self) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
        self.stop().await;
        // 给系统一点时间释放端口
        tokio::time::sleep(Duration::from_millis(500)).await;
        self.start().await
    }
}

/// 读 stdout 直到出现 `BACKEND_READY {...}` 行，解析后写入 current。
/// marker 之前的行作为日志转发；之后的行也转发（运行时日志）。
async fn read_stdout_until_marker(
    stdout: tokio::process::ChildStdout,
    expected_port: u16,
    expected_token: &str,
    current: &Arc<Mutex<Option<BackendInfo>>>,
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let mut reader = BufReader::new(stdout).lines();
    let mut got_marker = false;
    let deadline = tokio::time::Instant::now() + READY_TIMEOUT;

    loop {
        tokio::select! {
            _ = tokio::time::sleep_until(deadline), if !got_marker => {
                if !got_marker {
                    log::error!("[sidecar] marker 等待超时");
                    return Err("marker 等待超时".into());
                }
            }
            line = reader.next_line() => {
                match line {
                    Ok(Some(text)) => {
                        if !got_marker {
                            if let Some(rest) = text.strip_prefix(MARKER_PREFIX) {
                                match parse_marker(rest, expected_port, expected_token) {
                                    Ok(info) => {
                                        log::info!("[sidecar] 收到 marker: base_url={}", info.base_url);
                                        *current.lock().await = Some(info);
                                        got_marker = true;
                                    }
                                    Err(e) => {
                                        log::error!("[sidecar] marker 校验失败: {e}");
                                        return Err(e);
                                    }
                                }
                                continue;
                            }
                            // marker 之前检测 Traceback / Error → 立即报错
                            if text.contains("Traceback") || text.contains("ModuleNotFoundError") {
                                log::error!("[backend:stdout] {text}");
                                return Err(format!("后端启动报错: {text}").into());
                            }
                        }
                        log::info!("[backend:stdout] {text}");
                    }
                    Ok(None) => {
                        log::warn!("[sidecar] stdout EOF");
                        return if got_marker {
                            Ok(())
                        } else {
                            Err("stdout EOF 且未收到 marker".into())
                        };
                    }
                    Err(e) => {
                        log::error!("[sidecar] stdout 读取异常: {e}");
                        return Err(e.into());
                    }
                }
            }
        }
    }
}

/// 解析 marker JSON：`{"port":8765,"token":"...","pid":12345}`。
fn parse_marker(
    json_str: &str,
    expected_port: u16,
    expected_token: &str,
) -> Result<BackendInfo, Box<dyn std::error::Error + Send + Sync>> {
    let v: HashMap<String, serde_json::Value> =
        serde_json::from_str(json_str).map_err(|e| format!("marker JSON 解析失败: {e}"))?;

    let port = v
        .get("port")
        .and_then(|x| x.as_u64())
        .ok_or("marker 缺少 port")?
        as u16;
    let token = v
        .get("token")
        .and_then(|x| x.as_str())
        .ok_or("marker 缺少 token")?
        .to_string();

    if port != expected_port {
        return Err(format!("port 不匹配: expected {expected_port}, got {port}").into());
    }
    if !expected_token.is_empty() && token != expected_token {
        return Err("token 不匹配".into());
    }

    Ok(BackendInfo {
        base_url: format!("http://127.0.0.1:{port}"),
        ws_url: format!("ws://127.0.0.1:{port}/ws"),
        token,
        ready: true,
    })
}

/// 终止 child 及其全部子孙进程（Windows：taskkill /F /T）。
///
/// 返回 true 表示进程树已终止（child 已收尸）；false 表示需回退 child.kill()。
/// CREATE_NO_WINDOW 防止 taskkill（console 程序）在无控制台的 GUI 进程下闪黑框。
async fn kill_process_tree(child: &mut Child) -> bool {
    let Some(pid) = child.id() else {
        return false;
    };

    #[cfg(windows)]
    {
        // tokio::process::Command 在 Windows 上原生提供 creation_flags 方法
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;

        let result = Command::new("taskkill")
            .args(["/F", "/T", "/PID", &pid.to_string()])
            .creation_flags(CREATE_NO_WINDOW)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .await;

        match result {
            Ok(status) if status.success() => {
                log::info!("[sidecar] 进程树 {pid} 已终止");
                // 树已终止，等待 child 退出回收句柄（不再需要 kill）
                let _ = child.wait().await;
                true
            }
            Ok(status) => {
                log::warn!("[sidecar] taskkill 退出码异常: {status}，回退 child.kill()");
                false
            }
            Err(e) => {
                log::warn!("[sidecar] taskkill 执行失败: {e}，回退 child.kill()");
                false
            }
        }
    }

    #[cfg(not(windows))]
    {
        // 非 Windows：child.kill() 本身会向进程组发信号（kill_on_drop + 进程组语义）
        let _ = pid;
        false
    }
}

/// 选一个空闲端口（bind 0 后立即释放，交给后端重新绑定）。
fn pick_free_port() -> Result<u16, Box<dyn std::error::Error + Send + Sync>> {
    let listener = std::net::TcpListener::bind("127.0.0.1:0")?;
    let port = listener.local_addr()?.port();
    drop(listener);
    Ok(port)
}

/// 32 字节 hex token。
fn random_token() -> String {
    let mut bytes = [0u8; 32];
    rand::rngs::OsRng.fill_bytes(&mut bytes);
    hex_encode(&bytes)
}

fn hex_encode(bytes: &[u8]) -> String {
    let mut s = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        s.push_str(&format!("{b:02x}"));
    }
    s
}

/// 解析后端可执行命令：
/// - BACKEND_EXTERNAL=1：Rust 不拉后端，连外部已启动的（PyCharm Debug 启动）
///   端口固定 8765，token 为空（dev 模式跳过校验）
/// - BACKEND_DEV=1：Rust 拉 python -m uvicorn（PyCharm 断点不生效，不推荐）
/// - 默认打包模式：找 backend_service exe
fn resolve_backend_command(
    port: u16,
    token: &str,
) -> Result<(String, Vec<String>), Box<dyn std::error::Error + Send + Sync>> {
    // BACKEND_EXTERNAL 模式：连 PyCharm Debug 启动的后端（固定 8765，无 token）
    // Rust 不 spawn 任何进程，由调用方特殊处理
    if std::env::var("BACKEND_EXTERNAL").is_ok() {
        // 返回一个 no-op 命令占位（实际由 start() 短路）
        return Ok(("cmd".to_string(), vec!["/c".to_string(), "echo".to_string(), "external".to_string()]));
    }

    if std::env::var("BACKEND_DEV").is_ok() {
        // 开发模式：直接调用 backend_service.app 的 main()（它内部 parse_args 处理 --token/--dev）
        // 工作目录是 frontend/，所以需要 PYTHONPATH 指向项目根目录（../）
        let program = std::env::var("PYTHON").unwrap_or_else(|_| "python".to_string());
        let args = vec![
            "-m".to_string(),
            "backend_service.app".to_string(),
            "--host".to_string(),
            "127.0.0.1".to_string(),
            "--port".to_string(),
            port.to_string(),
            "--token".to_string(),
            token.to_string(),
            "--dev".to_string(),
        ];
        return Ok((program, args));
    }

    // 打包模式：找 backend_service exe（Tauri externalBin 约定带平台后缀）
    let exe_name = if cfg!(windows) {
        "backend_service-x86_64-pc-windows-msvc.exe"
    } else if cfg!(target_os = "macos") {
        "backend_service-x86_64-apple-darwin"
    } else {
        "backend_service-x86_64-unknown-linux-gnu"
    };

    // 开发期 tauri dev：从项目根目录的 dist-sidecar/ 找
    let dev_path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("dist-sidecar")
        .join(exe_name);
    if dev_path.exists() {
        let args = vec![
            "--host".to_string(),
            "127.0.0.1".to_string(),
            "--port".to_string(),
            port.to_string(),
            "--token".to_string(),
            token.to_string(),
        ];
        return Ok((dev_path.to_string_lossy().into_owned(), args));
    }

    // 打包后：Tauri 把 externalBin 解压到 sidecar 资源目录
    // Tauri 2：通过 sidecar 资源目录查找；这里用当前可执行文件所在目录兜底
    let app_dir = std::env::current_exe()
        .map_err(|e| e.to_string())?
        .parent()
        .ok_or("无法定位 exe 目录")?
        .to_path_buf();
    let packaged = app_dir.join(exe_name);
    if packaged.exists() {
        let args = vec![
            "--host".to_string(),
            "127.0.0.1".to_string(),
            "--port".to_string(),
            port.to_string(),
            "--token".to_string(),
            token.to_string(),
        ];
        return Ok((packaged.to_string_lossy().into_owned(), args));
    }

    Err(format!("找不到后端可执行文件: {exe_name}（开发模式请设置 BACKEND_DEV=1）").into())
}
