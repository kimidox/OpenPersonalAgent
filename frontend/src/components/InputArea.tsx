import { useState } from "react";
import FileUploadArea from "./FileUploadArea";
import type { FileAttachment } from "@/types/api";
import "./InputArea.css";

interface Props {
  onSend: (query: string, attachments?: FileAttachment[]) => void | Promise<void>;
  onStop: () => void | Promise<void>;
  isRunning: boolean;
  awaitingUser: boolean;
  disabled?: boolean;
  enableThinking?: boolean;
  onThinkingChange?: (enabled: boolean) => void;
}

export default function InputArea({
  onSend,
  onStop,
  isRunning,
  awaitingUser,
  disabled,
  enableThinking = false,
  onThinkingChange,
}: Props) {
  const [text, setText] = useState("");
  const [attachments, setAttachments] = useState<FileAttachment[]>([]);

  function handleUploaded(attachment: FileAttachment) {
    setAttachments((prev) => [...prev, attachment]);
  }

  function removeAttachment(index: number) {
    setAttachments((prev) => prev.filter((_, i) => i !== index));
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!text.trim() || disabled) return;
    const hasAttachments = attachments.length > 0;
    onSend(text, hasAttachments ? attachments : undefined);
    setText("");
    setAttachments([]);
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    // Ctrl/Cmd+Enter 发送
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      handleSubmit(e as unknown as React.FormEvent);
    }
  }

  return (
    <div className="input-area">
      <form onSubmit={handleSubmit} className="input-form">
        {attachments.length > 0 && (
          <div className="attachments-list">
            {attachments.map((att, i) => (
              <div key={att.file_id + i} className="attachment-chip">
                <span>{att.summary}</span>
                <button
                  type="button"
                  className="attachment-remove"
                  onClick={() => removeAttachment(i)}
                  aria-label="移除附件"
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        )}
        <textarea
          className="input-text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={
            disabled
              ? "请先选择会话"
              : awaitingUser
              ? "等待你回复..."
              : isRunning
              ? "正在生成回复...（可输入 steering 指令）"
              : "输入消息，Ctrl+Enter 发送"
          }
          rows={3}
          disabled={disabled}
        />
        <div className="input-actions">
          <div className="input-actions-left">
            <FileUploadArea
              onUploaded={handleUploaded}
              disabled={disabled || isRunning}
            />
            <label className="thinking-toggle-inline">
              <input
                type="checkbox"
                checked={enableThinking}
                onChange={(e) => onThinkingChange?.(e.target.checked)}
                disabled={disabled}
              />
              深度思考
            </label>
          </div>
          <div className="input-actions-right">
            {isRunning ? (
              <button type="button" onClick={onStop} className="stop-btn">
                停止
              </button>
            ) : (
              <button
                type="submit"
                className="send-btn"
                disabled={disabled || !text.trim()}
              >
                发送
              </button>
            )}
          </div>
        </div>
      </form>
    </div>
  );
}
