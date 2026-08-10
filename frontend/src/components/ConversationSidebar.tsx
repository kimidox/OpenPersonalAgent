import { useCallback, useEffect, useRef, useState } from "react";
import type { ConversationSummary } from "@/types/api";
import "./ConversationSidebar.css";

interface Props {
  conversations: ConversationSummary[];
  currentId: string | null;
  loading: boolean;
  onSelect: (id: string) => void | Promise<void>;
  onNew: () => void | Promise<void>;
  onDelete: (id: string) => void | Promise<void>;
  onRename: (id: string, title: string) => void | Promise<void>;
}

interface ContextMenuState {
  visible: boolean;
  x: number;
  y: number;
  conversationId: string | null;
  title: string;
}

interface RenameDialogState {
  visible: boolean;
  conversationId: string | null;
  initialTitle: string;
}

interface DeleteDialogState {
  visible: boolean;
  conversationId: string | null;
  title: string;
}

export default function ConversationSidebar({
  conversations,
  currentId,
  loading,
  onSelect,
  onNew,
  onDelete,
  onRename,
}: Props) {
  const [contextMenu, setContextMenu] = useState<ContextMenuState>({
    visible: false,
    x: 0,
    y: 0,
    conversationId: null,
    title: "",
  });
  const [renameDialog, setRenameDialog] = useState<RenameDialogState>({
    visible: false,
    conversationId: null,
    initialTitle: "",
  });
  const [deleteDialog, setDeleteDialog] = useState<DeleteDialogState>({
    visible: false,
    conversationId: null,
    title: "",
  });
  const [renameInput, setRenameInput] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);

  const menuRef = useRef<HTMLDivElement>(null);
  const renameInputRef = useRef<HTMLInputElement>(null);

  // 点击外部关闭右键菜单
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setContextMenu((m) => ({ ...m, visible: false }));
      }
    };
    if (contextMenu.visible) {
      document.addEventListener("mousedown", handleClickOutside);
      return () => document.removeEventListener("mousedown", handleClickOutside);
    }
  }, [contextMenu.visible]);

  // ESC 关闭菜单和对话框
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setContextMenu((m) => ({ ...m, visible: false }));
        setRenameDialog((d) => ({ ...d, visible: false }));
        setDeleteDialog((d) => ({ ...d, visible: false }));
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, []);

  // 重命名对话框打开时自动聚焦输入框
  useEffect(() => {
    if (renameDialog.visible && renameInputRef.current) {
      renameInputRef.current.focus();
      renameInputRef.current.select();
    }
  }, [renameDialog.visible]);

  const handleContextMenu = useCallback(
    (e: React.MouseEvent, conv: ConversationSummary) => {
      e.preventDefault();
      e.stopPropagation();
      setContextMenu({
        visible: true,
        x: e.clientX,
        y: e.clientY,
        conversationId: conv.conversation_id,
        title: conv.title || "未命名会话",
      });
    },
    [],
  );

  const handleRenameClick = useCallback(() => {
    if (!contextMenu.conversationId) return;
    setRenameDialog({
      visible: true,
      conversationId: contextMenu.conversationId,
      initialTitle: contextMenu.title,
    });
    setRenameInput(contextMenu.title);
    setActionError(null);
    setContextMenu((m) => ({ ...m, visible: false }));
  }, [contextMenu.conversationId, contextMenu.title]);

  const handleDeleteClick = useCallback(() => {
    if (!contextMenu.conversationId) return;
    setDeleteDialog({
      visible: true,
      conversationId: contextMenu.conversationId,
      title: contextMenu.title,
    });
    setActionError(null);
    setContextMenu((m) => ({ ...m, visible: false }));
  }, [contextMenu.conversationId, contextMenu.title]);

  const handleRenameConfirm = useCallback(async () => {
    if (!renameDialog.conversationId) return;
    const newTitle = renameInput.trim() || "未命名会话";
    setActionError(null);
    try {
      await onRename(renameDialog.conversationId, newTitle);
      setRenameDialog({ visible: false, conversationId: null, initialTitle: "" });
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      console.error("[ConversationSidebar] 重命名失败:", err);
      setActionError(`重命名失败：${msg}`);
    }
  }, [renameDialog.conversationId, renameInput, onRename]);

  const handleDeleteConfirm = useCallback(async () => {
    if (!deleteDialog.conversationId) return;
    setActionError(null);
    try {
      await onDelete(deleteDialog.conversationId);
      setDeleteDialog({ visible: false, conversationId: null, title: "" });
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      console.error("[ConversationSidebar] 删除失败:", err);
      setActionError(`删除失败：${msg}`);
    }
  }, [deleteDialog.conversationId, onDelete]);

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
            onContextMenu={(e) => handleContextMenu(e, conv)}
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

      {/* 右键菜单 */}
      {contextMenu.visible && (
        <div
          ref={menuRef}
          className="conv-context-menu"
          style={{ left: contextMenu.x, top: contextMenu.y }}
        >
          <div
            className="context-menu-item"
            onClick={handleRenameClick}
          >
            <span className="context-menu-icon">✎</span>
            <span>修改会话名称</span>
          </div>
          <div
            className="context-menu-item context-menu-danger"
            onClick={handleDeleteClick}
          >
            <span className="context-menu-icon">🗑</span>
            <span>删除会话</span>
          </div>
        </div>
      )}

      {/* 重命名对话框 */}
      {renameDialog.visible && (
        <div
          className="modal-overlay"
          onClick={() => {
            setRenameDialog((d) => ({ ...d, visible: false }));
            setActionError(null);
          }}
        >
          <div className="modal-dialog" onClick={(e) => e.stopPropagation()}>
            <h3 className="modal-title">修改会话名称</h3>
            <input
              ref={renameInputRef}
              type="text"
              className="modal-input"
              value={renameInput}
              onChange={(e) => setRenameInput(e.target.value)}
              placeholder="请输入新的会话名称"
              maxLength={60}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleRenameConfirm();
              }}
            />
            {actionError && (
              <div className="modal-error-tip">{actionError}</div>
            )}
            <div className="modal-actions">
              <button
                className="modal-btn modal-btn-cancel"
                onClick={() => {
                  setRenameDialog((d) => ({ ...d, visible: false }));
                  setActionError(null);
                }}
              >
                取消
              </button>
              <button
                className="modal-btn modal-btn-confirm"
                onClick={handleRenameConfirm}
              >
                确定
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 删除确认对话框 */}
      {deleteDialog.visible && (
        <div
          className="modal-overlay"
          onClick={() => {
            setDeleteDialog((d) => ({ ...d, visible: false }));
            setActionError(null);
          }}
        >
          <div className="modal-dialog" onClick={(e) => e.stopPropagation()}>
            <h3 className="modal-title">确认删除</h3>
            <p className="modal-content-text">
              确定要删除会话 <strong>「{deleteDialog.title}」</strong> 吗？
            </p>
            {actionError && (
              <div className="modal-error-tip">{actionError}</div>
            )}
            <div className="modal-actions">
              <button
                className="modal-btn modal-btn-cancel"
                onClick={() => {
                  setDeleteDialog((d) => ({ ...d, visible: false }));
                  setActionError(null);
                }}
              >
                取消
              </button>
              <button
                className="modal-btn modal-btn-danger"
                onClick={handleDeleteConfirm}
              >
                删除
              </button>
            </div>
          </div>
        </div>
      )}
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
