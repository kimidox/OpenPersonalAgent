import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { initBackendConfig } from "./api/backend";
import "./styles/global.css";

// 阶段 6：Tauri 模式下先 invoke 拿后端 URL/token，再渲染
// 浏览器 dev 模式直接返回（vite proxy 转发）
initBackendConfig().finally(() => {
  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  );
});
