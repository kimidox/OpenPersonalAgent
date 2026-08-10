# 前端

Tauri + React + TypeScript 前端（见 `.trae/documents/frontend-tauri-refactor.md`）。

## 开发

```bash
# 1. 启动后端（开发模式，端口 8765）
cd ..
.venv\Scripts\python.exe -m backend_service.app --dev --port 8765

# 2. 启动前端（浏览器 dev，端口 1420）
cd frontend
npm install
npm run dev
```

打开 http://localhost:1420 即可。

## Tauri 打包（阶段 6）

需要先安装 Rust 工具链：

```bash
# 安装 Rust（首次）
# 见 https://rustup.rs

# 打包桌面应用
npm run tauri build
```

## 目录结构

```
src/
  api/         REST + WS 客户端
  components/  React 组件
  hooks/       useTypewriter / useStream
  store/       Zustand 全局状态
  types/       TypeScript 类型（与后端 schema 对齐）
  styles/      全局样式
src-tauri/     Tauri 配置（阶段 6 用）
```

## 关键特性

- **WS 重放**：断线重连后按 `event_id` 重放遗漏事件；过期场景自动改走 REST 重建
- **打字机**：流式字符渲染，断线期间暂停 tick
- **并发控制**：消息发送冲突时返回 409，前端提示
- **思考/工具调用三段式**：assistant 消息独立渲染 thinking / toolCall / content
