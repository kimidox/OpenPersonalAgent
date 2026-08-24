import { useEffect, useState } from "react";
import ChatPage from "./components/ChatPage";
import CloseConfirmDialog from "./components/CloseConfirmDialog";
import SettingsPage from "./settings/SettingsPage";
import { onConnectionChange } from "./api/client";

type Page = "chat" | "settings";

export default function App() {
  const [online, setOnline] = useState(true);
  const [page, setPage] = useState<Page>("chat");

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
