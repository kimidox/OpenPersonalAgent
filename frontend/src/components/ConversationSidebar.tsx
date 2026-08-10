import type { ConversationSummary } from "@/types/api";
import "./ConversationSidebar.css";

interface Props {
  conversations: ConversationSummary[];
  currentId: string | null;
  loading: boolean;
  onSelect: (id: string) => void | Promise<void>;
  onNew: () => void | Promise<void>;
}

export default function ConversationSidebar({
  conversations,
  currentId,
  loading,
  onSelect,
  onNew,
}: Props) {
  return (
    <aside className="conversation-sidebar">
      <div className="sidebar-header">
        <h3>会话</h3>
        <button className="new-conv-btn" onClick={onNew}>
          + 新建
        </button>
      </div>
      <div className="conv-list">
        {loading && conversations.length === 0 && (
          <div className="conv-empty">加载中...</div>
        )}
        {!loading && conversations.length === 0 && (
          <div className="conv-empty">暂无会话</div>
        )}
        {conversations.map((conv) => (
          <button
            key={conv.conversation_id}
            className={`conv-item ${conv.conversation_id === currentId ? "active" : ""}`}
            onClick={() => onSelect(conv.conversation_id)}
          >
            <div className="conv-title">
              {conv.title || "未命名会话"}
            </div>
            <div className="conv-meta">
              {conv.type}
              {conv.updated_at && ` · ${formatTime(conv.updated_at)}`}
            </div>
          </button>
        ))}
      </div>
    </aside>
  );
}

function formatTime(s: string): string {
  try {
    const d = new Date(s);
    return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours().toString().padStart(2, "0")}:${d
      .getMinutes()
      .toString()
      .padStart(2, "0")}`;
  } catch {
    return s;
  }
}
