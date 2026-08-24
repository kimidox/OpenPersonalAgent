import { useEffect, useState } from "react";
import ChatPage from "./components/ChatPage";
import CloseConfirmDialog from "./components/CloseConfirmDialog";
import SettingsPage from "./settings/SettingsPage";
import { onConnectionChange } from "./api/client";
import { WSClient } from "./api/ws";
import { getBaseUrl, isTauri } from "./api/backend";

type Page = "chat" | "settings";

// 系统事件 WS 的伪会话 ID（后端 /ws/stream 要求 conversation_id 非空；
// 系统事件广播给全部已连接客户端，与具体会话无关）
const SYSTEM_CONVERSATION_ID = "__system__";

/**
 * 常驻系统事件 WS：悬浮球触发的 window.show / floating_ball.quit。
 *
 * 会话级 WS 只在选中会话后才建立；若把系统事件挂在会话 WS 上，
 * 未选中会话时悬浮球的"显示主窗口/退出应用"会被静默丢弃。
 * 因此在 App 层用独立客户端常驻订阅（含自动重连）。
 */
function useSystemWs(): void {
  useEffect(() => {
    let ws: WSClient | null = null;
    let pollTimer: ReturnType<typeof setInterval> | null = null;
    let disposed = false;

    const invokeTauri = async (cmd: string) => {
      if (!isTauri()) return;
      try {
        const { invoke } = await import("@tauri-apps/api/core");
        await invoke(cmd);
      } catch (err) {
        console.error(`[App] invoke ${cmd} 失败:`, err);
      }
    };

    const connect = () => {
      if (disposed) return;
      ws = new WSClient(SYSTEM_CONVERSATION_ID);
      ws.on("window.show", () => {
        console.log("[App] 收到 window.show 事件（悬浮球请求显示主窗口）");
        void invokeTauri("show_main_window");
      });
      ws.on("floating_ball.quit", () => {
        console.log("[App] 收到 floating_ball.quit 事件（悬浮球请求退出应用）");
        void invokeTauri("quit_app");
      });
      ws.connect();
    };

    if (isTauri()) {
      // Tauri 模式：等 Rust 注入后端 URL（backend-ready）后再连接
      pollTimer = setInterval(() => {
        if (getBaseUrl()) {
          if (pollTimer) clearInterval(pollTimer);
          pollTimer = null;
          connect();
        }
      }, 500);
    } else {
      // 浏览器 dev 模式：vite proxy 转发，立即连接
      connect();
    }

    return () => {
      disposed = true;
      if (pollTimer) clearInterval(pollTimer);
      ws?.close();
    };
  }, []);
}

export default function App() {
  const [online, setOnline] = useState(true);
  const [page, setPage] = useState<Page>("chat");

  useSystemWs();

  useEffect(() => {
    return onConnectionChange((o) => setOnline(o));
  }, []);

  return (
    <div className="app-root">
      {!online && (
        <div className="connection-banner">
          后端连接中断，正在重试...
        </div>
      )}
      <nav className="app-nav">
        <button
          className={`nav-btn ${page === "settings" ? "active" : ""}`}
          onClick={() => setPage("settings")}
        >
          设置
        </button>
      </nav>
      {page === "chat" ? <ChatPage /> : <SettingsPage onBack={() => setPage("chat")} />}
      {/* 关闭主窗口确认弹窗（Tauri 拦截 CloseRequested 后触发） */}
      <CloseConfirmDialog />
    </div>
  );
}
