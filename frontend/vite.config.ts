import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// Tauri 重构前端配置（见 .trae/documents/frontend-tauri-refactor.md）
// - dev: 浏览器独立运行（连接后端 :8765），无 Tauri 依赖
// - build: 输出 dist/，Tauri 阶段 6 打包时嵌入
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  // Tauri Webview 用固定端口 1420；浏览器 dev 用 5173
  server: {
    port: 1420,
    strictPort: !!process.env.TAURI_ENV_PLATFORM,
    proxy: {
      // 开发期：把 /api 与 /ws 转发到后端，避免 CORS
      "/api": "http://127.0.0.1:8765",
      "/ws": {
        target: "ws://127.0.0.1:8765",
        ws: true,
      },
    },
  },
  build: {
    target: "es2022",
    outDir: "dist",
  },
});
