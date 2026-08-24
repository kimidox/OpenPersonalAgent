//! Tauri 应用主模块（阶段 6 打包入口）。
//!
//! 职责（见 frontend-tauri-refactor.md 3.12 / 3.13）：
//! - 拉起 Python 后端 sidecar（backend_service.exe / python backend_service）
//! - 解析 stdout 的 `BACKEND_READY {"port":...,"token":...,"pid":...}` marker
//! - 把后端 URL/token 经 invoke 命令注入前端
//! - 健康轮询（GET /api/health）+ 崩溃重启（上限 3 次/会话）
//! - 系统托盘 + 单例锁 + 窗口显隐（window.show 事件 → 主窗 show+setFocus）

mod sidecar;

use std::sync::Arc;

use serde::Serialize;
use tauri::{Emitter, Manager, WindowEvent};
use tauri_plugin_dialog::DialogExt;
use tokio::sync::RwLock;

use sidecar::SidecarManager;

/// 后端连接信息（前端 invoke('get_backend_url') 取得）。
#[derive(Debug, Clone, Serialize)]
pub struct BackendInfo {
    pub base_url: String,
    pub ws_url: String,
    pub token: String,
    pub ready: bool,
}

/// 应用全局状态（经 AppState 注入到 Tauri）。
struct AppState {
    sidecar: Arc<SidecarManager>,
    backend: Arc<RwLock<BackendInfo>>,
}

#[tauri::command]
async fn get_backend_url(state: tauri::State<'_, AppState>) -> Result<BackendInfo, String> {
    Ok(state.backend.read().await.clone())
}

/// 前端手动触发"重启后端"（设置页按钮）。
#[tauri::command]
async fn restart_backend(state: tauri::State<'_, AppState>) -> Result<BackendInfo, String> {
    log::info!("[tauri] 用户请求重启后端");
    // 先 clone Arc 再 await，避免 tauri::State 跨 await 的 Send 问题
    let sidecar = state.sidecar.clone();
    let backend = state.backend.clone();
    sidecar.restart().await.map_err(|e| e.to_string())?;
    // 等待新 marker
    let info = sidecar
        .wait_for_ready(std::time::Duration::from_secs(15))
        .await
        .map_err(|e| e.to_string())?;
    let mut b = backend.write().await;
    *b = info.clone();
    log::info!("[tauri] 后端已重启: {}", info.base_url);
    Ok(info)
}

/// 前端请求显示主窗口（window.show 事件经 WS 到达前端，前端 invoke 此命令）。
#[tauri::command]
fn show_main_window(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(win) = app.get_webview_window("main") {
        win.show().map_err(|e| e.to_string())?;
        win.set_focus().map_err(|e| e.to_string())?;
    }
    Ok(())
}

/// 前端请求隐藏主窗口（关闭确认弹窗的"最小化到托盘"/"悬浮窗模式"选项）。
#[tauri::command]
fn hide_main_window(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(win) = app.get_webview_window("main") {
        win.hide().map_err(|e| e.to_string())?;
    }
    Ok(())
}

/// 前端请求退出整个应用（floating_ball.quit 事件 / 关闭确认弹窗"退出程序" → 前端 invoke）。
#[tauri::command]
async fn quit_app(app: tauri::AppHandle, state: tauri::State<'_, AppState>) -> Result<(), String> {
    log::info!("[tauri] 用户请求退出应用");
    // 先 clone Arc 再 await，避免 tauri::State 跨 await 的 Send 问题
    let sidecar = state.sidecar.clone();
    let backend = state.backend.clone();
    quit_everything(&sidecar, &backend, &app).await;
    Ok(())
}

/// 加载 .env 文件。
///
/// 加载顺序（后者覆盖前者同名变量）：
/// 1) dotenvy 标准查找：从当前工作目录向上递归，会命中 `frontend/.env`（dev）或 exe 旁的 `.env`（prod）
/// 2) 项目根目录 `.env`：通过 `CARGO_MANIFEST_DIR`（= frontend/src-tauri）推导 `../../.env`
/// 3) 打包兜底：exe 同目录下的 `.env`
///
/// 设计说明：`dotenvy::dotenv()` 一旦在 `frontend/.env` 找到文件就停止向上，
/// 导致项目根 `.env` 里的 WINDOW_WIDTH 等共享配置不生效；因此这里显式补一次根目录加载。
fn load_dotenv() {
    use std::env;
    use std::path::{Path, PathBuf};

    // 1) 标准 dotenvy 查找（就近原则，保证 frontend/.env 的 VITE_* 先被吸收）
    let _ = dotenvy::dotenv();

    // 2) 显式加载项目根目录的 .env（共享配置：窗口尺寸、模型、TTS...）
    //    CARGO_MANIFEST_DIR = "d:/.../PersonalWindowGLM/frontend/src-tauri"
    //    → 往上两级就是项目根
    if let Ok(manifest_dir) = env::var("CARGO_MANIFEST_DIR") {
        let root_env: PathBuf = Path::new(&manifest_dir)
            .parent()        // frontend/
            .and_then(|p| p.parent())  // 项目根/
            .map(|p| p.join(".env"))
            .unwrap_or_else(|| PathBuf::from(".env"));
        if root_env.is_file() {
            log::debug!("[tauri] 加载项目根 .env: {}", root_env.display());
            let _ = dotenvy::from_path(&root_env);
        }
    }

    // 3) prod 兜底：当前 exe 所在目录
    if let Ok(exe_path) = env::current_exe() {
        if let Some(exe_dir) = exe_path.parent() {
            let candidate: PathBuf = exe_dir.join(".env");
            if candidate.is_file() {
                let _ = dotenvy::from_path(&candidate);
            }
        }
    }
}

/// 从环境变量解析窗口尺寸，失败时回退到默认值。
fn parse_window_size_from_env() -> (f64, f64, f64, f64) {
    use std::env;

    // 默认值（与 tauri.conf.json 保持一致的兜底）
    const DEFAULT_WIDTH: f64 = 1200.0;
    const DEFAULT_HEIGHT: f64 = 800.0;
    const DEFAULT_MIN_WIDTH: f64 = 800.0;
    const DEFAULT_MIN_HEIGHT: f64 = 600.0;

    let parse = |key: &str, fallback: f64| -> f64 {
        env::var(key)
            .ok()
            .and_then(|v| v.trim().parse::<f64>().ok())
            .map(|v| if v <= 0.0 { fallback } else { v })
            .unwrap_or(fallback)
    };

    let width = parse("WINDOW_WIDTH", DEFAULT_WIDTH);
    let height = parse("WINDOW_HEIGHT", DEFAULT_HEIGHT);
    let min_width = parse("WINDOW_MIN_WIDTH", DEFAULT_MIN_WIDTH);
    let min_height = parse("WINDOW_MIN_HEIGHT", DEFAULT_MIN_HEIGHT);

    (width, height, min_width, min_height)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    load_dotenv();

    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info"))
        .format_timestamp_secs()
        .init();

    let (win_w, win_h, win_min_w, win_min_h) = parse_window_size_from_env();
    log::info!(
        "[tauri] 窗口配置：{}x{} (最小 {}x{})",
        win_w, win_h, win_min_w, win_min_h
    );
    log::info!("[tauri] 启动 PersonalWindowGLM 外壳");

    let sidecar = Arc::new(SidecarManager::new());
    let backend = Arc::new(RwLock::new(BackendInfo {
        base_url: String::new(),
        ws_url: String::new(),
        token: String::new(),
        ready: false,
    }));

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            // 单例：第二次启动时把已有窗口唤起
            if let Some(win) = app.get_webview_window("main") {
                let _ = win.show();
                let _ = win.set_focus();
            }
        }))
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_process::init())
        .manage(AppState {
            sidecar: sidecar.clone(),
            backend: backend.clone(),
        })
        .setup({
            let sidecar = sidecar.clone();
            let backend = backend.clone();
            move |app| {
                let app_handle = app.handle().clone();
                let sidecar_for_health = sidecar.clone();
                let backend_for_health = backend.clone();

                // 动态设置主窗口尺寸（优先读取 .env 配置，缺失则回退到 tauri.conf.json 默认值）
                if let Some(win) = app.get_webview_window("main") {
                    // LogicalSize 使用逻辑像素，匹配用户在 Windows 显示设置中的"分辨率"直觉
                    let logical_size = tauri::LogicalSize {
                        width: win_w,
                        height: win_h,
                    };
                    let min_logical_size = tauri::LogicalSize {
                        width: win_min_w,
                        height: win_min_h,
                    };

                    let _ = win.set_min_size(Some(min_logical_size));
                    let _ = win.set_size(logical_size);

                    let scale_factor = win
                        .current_monitor()
                        .ok()
                        .flatten()
                        .map(|m| m.scale_factor())
                        .unwrap_or(1.0);
                    log::info!(
                        "[tauri] 主窗口尺寸已应用: {}x{} (min {}x{}, scale={})",
                        win_w, win_h, win_min_w, win_min_h, scale_factor
                    );
                }

                // 启动后端 sidecar（异步）
                let app_handle_spawn = app_handle.clone();
                tauri::async_runtime::spawn(async move {
                    if let Err(e) = start_sidecar(&sidecar, &backend, &app_handle_spawn).await {
                        log::error!("[tauri] sidecar 启动失败: {e}");
                        show_backend_error_dialog(&app_handle_spawn, &e.to_string());
                    }
                });

                // 健康轮询 + 崩溃重启（独立异步任务）
                tauri::async_runtime::spawn(async move {
                    health_watch_loop(sidecar_for_health, backend_for_health, app_handle).await;
                });

                setup_tray(app.handle())?;
                Ok(())
            }
        })
        .on_window_event(|window, event| {
            // 关闭主窗口时先询问用户去向：完全退出 / 悬浮窗模式 / 最小化到托盘
            if let WindowEvent::CloseRequested { api, .. } = event {
                if window.label() == "main" {
                    // 阻止默认关闭，通知前端弹出确认弹窗，由用户选择后 invoke 对应命令
                    api.prevent_close();
                    let _ = window.app_handle().emit("close-requested", ());
                }
            }
        })
        .invoke_handler(tauri::generate_handler![
            get_backend_url,
            restart_backend,
            show_main_window,
            hide_main_window,
            quit_app,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

async fn start_sidecar(
    sidecar: &SidecarManager,
    backend: &RwLock<BackendInfo>,
    app: &tauri::AppHandle,
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    sidecar.start().await?;
    log::info!("[tauri] 等待 BACKEND_READY marker...");
    let info = sidecar.wait_for_ready(std::time::Duration::from_secs(15)).await?;
    log::info!("[tauri] 后端就绪: {}", info.base_url);

    let mut b = backend.write().await;
    *b = info.clone();
    drop(b);

    // 通知前端后端已就绪
    let _ = app.emit("backend-ready", info);
    Ok(())
}

/// 健康轮询 + 崩溃重启循环（见 3.13 节）。
async fn health_watch_loop(
    sidecar: Arc<SidecarManager>,
    backend: Arc<RwLock<BackendInfo>>,
    app: tauri::AppHandle,
) {
    let mut consecutive_failures: u32 = 0;
    let mut restart_count: u32 = 0;
    const MAX_RESTARTS: u32 = 3;
    const HEALTH_INTERVAL: std::time::Duration = std::time::Duration::from_secs(5);
    const MAX_HEALTH_FAILURES: u32 = 3;

    loop {
        tokio::time::sleep(HEALTH_INTERVAL).await;

        // 检查 sidecar 进程是否存活
        match sidecar.check_alive().await {
            Ok(false) => {
                log::warn!("[tauri] sidecar 进程已退出");
                consecutive_failures = 0;
                if restart_count >= MAX_RESTARTS {
                    log::error!("[tauri] 已达重启上限 {MAX_RESTARTS}，停止自动重启");
                    show_backend_error_dialog(
                        &app,
                        &format!(
                            "后端进程已退出且已达重启上限（{MAX_RESTARTS} 次）。\n请手动重启应用。"
                        ),
                    );
                    return;
                }
                restart_count += 1;
                log::info!("[tauri] 尝试重启后端（第 {restart_count}/{MAX_RESTARTS} 次）");
                if let Err(e) = sidecar.restart().await {
                    log::error!("[tauri] 重启失败: {e}");
                    continue;
                }
                match sidecar.wait_for_ready(std::time::Duration::from_secs(15)).await {
                    Ok(info) => {
                        let mut b = backend.write().await;
                        *b = info.clone();
                        let _ = app.emit("backend-ready", info);
                        log::info!("[tauri] 后端重启成功");
                    }
                    Err(e) => {
                        log::error!("[tauri] 重启后未收到 marker: {e}");
                    }
                }
                continue;
            }
            Ok(true) => {}
            Err(e) => {
                log::warn!("[tauri] check_alive 异常: {e}");
            }
        }

        // HTTP 健康检查
        let base_url = { backend.read().await.base_url.clone() };
        if base_url.is_empty() {
            continue;
        }
        let url = format!("{base_url}/api/health");
        match http_request_json("GET", &url, "").await {
            Ok(body) => {
                consecutive_failures = 0;
                // 悬浮球退出请求（WS floating_ball.quit 的兜底通道）：
                // 前端 WS 断线/未连接时，巡检也能感知并退出整个应用
                if body
                    .get("quit_requested")
                    .and_then(|v| v.as_bool())
                    .unwrap_or(false)
                {
                    log::info!("[tauri] 后端上报退出请求（悬浮球退出应用），退出整个应用");
                    quit_everything(&sidecar, &backend, &app).await;
                    return;
                }
            }
            Err(_) => {
                consecutive_failures += 1;
                log::warn!(
                    "[tauri] 健康检查失败 ({consecutive_failures}/{MAX_HEALTH_FAILURES})"
                );
                if consecutive_failures >= MAX_HEALTH_FAILURES {
                    log::warn!("[tauri] sidecar 卡死，kill + 重启");
                    consecutive_failures = 0;
                    if restart_count >= MAX_RESTARTS {
                        log::error!("[tauri] 已达重启上限，停止自动重启");
                        show_backend_error_dialog(&app, "后端连续无响应，已达重启上限。");
                        return;
                    }
                    restart_count += 1;
                    let _ = sidecar.restart().await;
                    match sidecar.wait_for_ready(std::time::Duration::from_secs(15)).await {
                        Ok(info) => {
                            let mut b = backend.write().await;
                            *b = info.clone();
                            let _ = app.emit("backend-ready", info);
                        }
                        Err(e) => {
                            log::error!("[tauri] 重启后未收到 marker: {e}");
                        }
                    }
                }
            }
        }
    }
}

/// 简易 HTTP 请求 + JSON 解析（避免引入 reqwest 依赖，用 tokio 的 process 调 curl 兜底不优雅，
/// 这里用 std::net + HTTP/1.0 手写最小请求；仅本机 127.0.0.1，足够）。
/// 返回解析后的 JSON body；连接失败 / 非 200 / 解析失败均视为 Err。
async fn http_request_json(
    method: &str,
    url: &str,
    token: &str,
) -> Result<serde_json::Value, String> {
    // 解析 http://127.0.0.1:PORT/api/health
    let parsed = url
        .strip_prefix("http://")
        .ok_or_else(|| "非 http URL".to_string())?;
    let (host_port, path) = parsed.split_once('/').unwrap_or((parsed, ""));
    let (host, port_str) = host_port
        .split_once(':')
        .ok_or_else(|| "缺少端口".to_string())?;
    let port: u16 = port_str.parse().map_err(|e: std::num::ParseIntError| e.to_string())?;
    let path = format!("/{path}");
    let method_owned = method.to_string();
    let token_owned = token.to_string();

    let host_owned = host.to_string();
    tokio::task::spawn_blocking(move || -> Result<serde_json::Value, String> {
        use std::io::{Read, Write};
        use std::net::TcpStream;
        use std::time::Duration;
        let mut stream = TcpStream::connect((host_owned.as_str(), port))
            .map_err(|e| e.to_string())?;
        stream
            .set_read_timeout(Some(Duration::from_secs(2)))
            .map_err(|e| e.to_string())?;
        let mut req = format!(
            "{method_owned} {path} HTTP/1.0\r\nHost: {host_owned}\r\nConnection: close\r\n"
        );
        if !token_owned.is_empty() {
            req.push_str(&format!("X-Backend-Token: {token_owned}\r\n"));
        }
        if method_owned == "POST" {
            req.push_str("Content-Length: 0\r\n");
        }
        req.push_str("\r\n");
        stream.write_all(req.as_bytes()).map_err(|e| e.to_string())?;
        let mut buf = Vec::with_capacity(256);
        stream.read_to_end(&mut buf).map_err(|e| e.to_string())?;
        let text = String::from_utf8_lossy(&buf);
        let status_line = text.lines().next().unwrap_or("");
        if !status_line.contains("200 OK") {
            return Err(format!("非 200 状态: {status_line}"));
        }
        // HTTP/1.0 响应：头与 body 以空行分隔
        let body = text
            .split_once("\r\n\r\n")
            .map(|(_, b)| b)
            .unwrap_or_default();
        serde_json::from_str(body).map_err(|e| format!("JSON 解析失败: {e}"))
    })
    .await
    .map_err(|e| e.to_string())?
}

/// 退出应用统一流程（quit_app 命令 / 托盘退出 / 健康巡检兜底共用）：
/// 1. POST /api/quit 请求后端优雅退出——BACKEND_EXTERNAL 模式（PyCharm 调试后端）
///    下这是终止后端（连同悬浮球子进程，经 lifespan 清理）的唯一手段，
///    否则 Tauri 退出后外部后端进程会残留；sidecar 模式下让 DB/调度器先清理。
/// 2. 等待后端退出（sidecar 模式查进程存活；外部模式轮询 /api/health 失联）。
/// 3. sidecar 模式 taskkill /F /T 强杀进程树兜底（外部模式 stop 为 no-op）。
/// 4. app.exit(0)。
async fn quit_everything(
    sidecar: &Arc<SidecarManager>,
    backend: &Arc<RwLock<BackendInfo>>,
    app: &tauri::AppHandle,
) {
    let (base_url, token) = {
        let b = backend.read().await;
        (b.base_url.clone(), b.token.clone())
    };

    // 1. 请求优雅退出（best-effort）
    let mut requested = false;
    if !base_url.is_empty() {
        let url = format!("{base_url}/api/quit");
        match http_request_json("POST", &url, &token).await {
            Ok(_) => {
                requested = true;
                log::info!("[tauri] 后端已收到优雅退出请求");
            }
            Err(e) => {
                log::warn!("[tauri] 请求后端优雅退出失败: {e}");
            }
        }
    }

    // 2. 等待后端自行退出（最多 ~5s），让 lifespan 完成清理
    if requested {
        let external = std::env::var("BACKEND_EXTERNAL").is_ok();
        let health_url = format!("{base_url}/api/health");
        for _ in 0..20 {
            let alive = if external {
                http_request_json("GET", &health_url, &token).await.is_ok()
            } else {
                sidecar.check_alive().await.unwrap_or(true)
            };
            if !alive {
                log::info!("[tauri] 后端已退出");
                break;
            }
            tokio::time::sleep(std::time::Duration::from_millis(250)).await;
        }
    }

    // 3. sidecar 模式兜底强杀（外部模式 no-op）
    sidecar.stop().await;
    // 4. 退出 Tauri
    app.exit(0);
}

fn show_backend_error_dialog(app: &tauri::AppHandle, msg: &str) {
    let message = msg.to_string();
    app.dialog()
        .message(message)
        .title("后端启动失败")
        .blocking_show();
}

/// 配置系统托盘（最小化到托盘 + 右键菜单：显示/退出）。
fn setup_tray(app: &tauri::AppHandle) -> Result<(), Box<dyn std::error::Error>> {
    use tauri::menu::{Menu, MenuItem};
    use tauri::tray::TrayIconBuilder;

    let show_item = MenuItem::with_id(app, "show", "显示主窗口", true, None::<&str>)?;
    let quit_item = MenuItem::with_id(app, "quit", "退出应用", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&show_item, &quit_item])?;

    TrayIconBuilder::new()
        .icon(app.default_window_icon().unwrap().clone())
        .tooltip("PersonalWindowGLM")
        .menu(&menu)
        .on_menu_event(move |app, event| match event.id.as_ref() {
            "show" => {
                if let Some(win) = app.get_webview_window("main") {
                    let _ = win.show();
                    let _ = win.set_focus();
                }
            }
            "quit" => {
                let state: tauri::State<AppState> = app.state();
                let sidecar = state.sidecar.clone();
                let backend = state.backend.clone();
                let handle = app.clone();
                tauri::async_runtime::spawn(async move {
                    quit_everything(&sidecar, &backend, &handle).await;
                });
            }
            _ => {}
        })
        .build(app)?;

    Ok(())
}
