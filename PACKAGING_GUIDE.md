# 打包指南（Tauri + Python Sidecar）

本文档介绍 PersonalWindowGLM 当前的打包方式。项目已重构为 **Tauri 2 + React 前端 + Python 后端 sidecar** 架构，旧的纯 PyInstaller 单体打包（`PersonalWindowGLM.spec` / 单文件模式 / `build.bat`）已废弃移除。

---

## 目录

1. [架构与产物](#架构与产物)
2. [前置要求](#前置要求)
3. [一键打包](#一键打包)
4. [手动分步打包](#手动分步打包)
5. [不进安装包的内容](#不进安装包的内容)
6. [打包后验证清单](#打包后验证清单)
7. [常见问题](#常见问题)

---

## 架构与产物

打包分两级：

```
第 1 级：PyInstaller（onedir）            第 2 级：Tauri（NSIS 安装包）
┌────────────────────────────┐    ┌──────────────────────────────────┐
│ dist-sidecar/backend_service/ │   │ PersonalWindowGLM_0.1.0_x64-setup.exe │
│  ├─ backend_service.exe      │ →  │  ├─ PersonalWindowGLM.exe（Rust 外壳+React 前端）│
│  └─ _internal/（Python 运行时 │    │  └─ backend_service/（第 1 级产物整个目录）    │
│      + 全部依赖 + Skills）    │    │     （经 tauri.conf.json resources 打入） │
└────────────────────────────┘    └──────────────────────────────────┘
```

启动链（安装后）：

1. Tauri 主进程启动，[sidecar.rs](./frontend/src-tauri/src/sidecar.rs) 从安装目录 `backend_service/backend_service.exe` 以 `--port {动态端口} --token {随机token}` 拉起后端
2. 后端完成初始化后在 stdout 输出 `BACKEND_READY {"port":...,"token":...,"pid":...}`，Rust 解析握手（上限 15s）
3. 后端再 spawn 悬浮球子进程（PySide6 + live2d-py，打包在同一 exe 内）
4. 前端通过 HTTP REST（命令）+ WebSocket（流式事件）与后端通信

关键文件：

| 文件 | 作用 |
|------|------|
| [backend_service.spec](./backend_service.spec) | PyInstaller 配置（onedir，含 hiddenimports 清单） |
| [tauri.conf.json](./frontend/src-tauri/tauri.conf.json) | `bundle.resources` 把后端目录打入安装包 |
| [sidecar.rs](./frontend/src-tauri/src/sidecar.rs) | 后端进程生命周期（拉起/握手/健康检查/重启/清理） |
| [build_release.ps1](./build_release.ps1) | 一键打包脚本 |

## 前置要求

| 工具 | 版本 | 说明 |
|------|------|------|
| Python | 3.11 | 需已安装 `requirements.txt` 全部依赖 + `pyinstaller` |
| Node.js | 18+ | `frontend/node_modules` 已安装（`npm install`） |
| Rust | MSVC 工具链 | `stable-x86_64-pc-windows-msvc` |
| NSIS | 自动下载 | Tauri 首次打包时自动下载，无需手动安装 |

```bash
pip install pyinstaller          # 若未安装
```

> UPX 压缩为可选项（spec 中 `upx=True`，未安装时自动跳过）。实测：后端目录 870MB 经 NSIS(lzma) 压缩后安装包约 167MB；UPX 只影响磁盘占用不影响安装包大小。

## 一键打包

```powershell
powershell -File build_release.ps1
```

脚本依次执行：PyInstaller 打包后端 → `npm run tauri build` 产出 NSIS 安装包。

后端代码无改动时可跳过第 1 步加速：

```powershell
powershell -File build_release.ps1 -SkipBackend
```

产物位置：

```
frontend/src-tauri/target/release/bundle/nsis/PersonalWindowGLM_0.1.0_x64-setup.exe
```

> 脚本结束时会在控制台列出产物路径和体积。

## 手动分步打包

### 第 1 步：PyInstaller 打包后端（项目根目录）

```bash
python -m PyInstaller backend_service.spec --noconfirm --distpath dist-sidecar
```

产物：`dist-sidecar/backend_service/{backend_service.exe, _internal/}`（约 870MB，含 PySide6/OpenCV/onnxruntime/pandas 等全部依赖与内置 Skills）。

### 第 2 步：Tauri 构建安装包

```bash
cd frontend
npm run tauri build
```

`tauri.conf.json` 中相关配置：

```json
"bundle": {
  "targets": ["nsis"],
  "resources": {
    "../../dist-sidecar/backend_service": "backend_service/"
  }
}
```

> **顺序必须先 1 后 2**：Tauri 构建时校验 resources 路径存在，若 `dist-sidecar/backend_service` 尚未生成会直接报错 `resource path doesn't exist`。

### 开发期调试（不打包）

```bash
# 前端 Tauri dev + 后端 dev 模式（Rust 直接拉 python）
cd frontend && npm run tauri:dev

# 后端 PyInstaller 产物 + tauri dev（验证打包后的后端行为）
python -m PyInstaller backend_service.spec --noconfirm --distpath dist-sidecar
cd frontend && npm run dev     # 另开终端，Rust 侧无 BACKEND_DEV 时自动找 dist-sidecar 产物
```

## 不进安装包的内容

| 内容 | 位置 | 说明 |
|------|------|------|
| 用户数据/数据库/日志 | `%APPDATA%/OpenPersonalAgent/` | 运行时按需创建，开发/打包同一份数据 |
| `.env` 应用配置 | `%APPDATA%/OpenPersonalAgent/.env` | **不打包**（避免泄露开发机密钥）；首次在设置页保存后生成 |
| ASR/TTS 模型（~430MB） | `%APPDATA%/OpenPersonalAgent/model/` | 首次使用语音功能时自动下载，见 [MODEL_DOWNLOAD.md](./MODEL_DOWNLOAD.md) |
| llama.cpp server | 用户自备 | 本地 Qwen3 模式需自行部署（须带 `--jinja`），或配置云端 API |

## 打包后验证清单

在干净 Windows 环境（无 Python/Node）安装后逐项验证：

1. 安装启动 → 后端 sidecar 随启随停，托盘后台模式正常
2. 流式对话 / 思考 / 工具调用 / await_user 卡片 / token 用量显示正常
3. 悬浮球 + Live2D 正常显示
4. 强杀后端进程 → Tauri 弹窗并自动重启（上限 3 次/会话）
5. 悬浮球菜单"退出应用" → 任务管理器确认后端、悬浮球、Tauri 进程全部消失
6. 首用语音功能触发模型下载到 `%APPDATA%/OpenPersonalAgent/model/`

## 常见问题

### Q1: 安装后启动弹"后端启动失败"？

看弹窗附带的 `[backend:stdout]` 日志行：
- `ModuleNotFoundError` → spec 缺 hiddenimport，补到 [backend_service.spec](./backend_service.spec) 的 `hiddenimports`
- `找不到后端可执行文件: backend_service/backend_service.exe` → 安装目录资源缺失，检查 `tauri.conf.json` 的 `resources` 配置

### Q2: 等待 marker 超时（15s）？

冒烟测试本机约 4s 出 marker。若持续超时，手动运行安装目录的 `backend_service\backend_service.exe --port 18799 --token test` 观察 stdout：能否正常输出 `BACKEND_READY {...}`。

### Q3: tauri build 报 `resource path doesn't exist`？

先执行第 1 步 PyInstaller 打包（构建顺序必须 PyInstaller → Tauri）。

### Q4: 安装包体积太大？

后端 `_internal/` 约 870MB 是依赖现状（PySide6/OpenCV/onnxruntime-gpu/pandas/scipy）。可行优化：
- 安装 `onnxruntime`（CPU 版）替代 `onnxruntime-gpu`，可省数百 MB（前提是不需要 GPU 推理）
- spec 的 `excludes` 排除未用模块
- UPX 压缩（影响启动速度，慎用）

### Q5: 杀毒软件误报？

PyInstaller + 未签名 exe 常见误报。正式分发需代码签名证书。

### Q6: 如何调试打包问题？

- 后端日志：`%APPDATA%/OpenPersonalAgent/PersonalData/logs/`
- Rust 侧日志：控制台启动 `PersonalWindowGLM.exe` 查看 `[backend:stdout]` / `[backend:stderr]` 输出
- spec 打 debug 包：`console=True` 已保留（marker 走 stdout，不能关；stdio 均为管道不会闪黑框）

---

## 更新日志

- v4.0.0（2026-08）：移除旧纯 PyInstaller 单体打包（PersonalWindowGLM.spec / onefile / build.bat）；确立 Tauri NSIS + PyInstaller onedir sidecar 两级打包；新增 build_release.ps1 一键脚本
