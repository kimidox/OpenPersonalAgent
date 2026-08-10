import { useState } from "react";
import FileUploadArea from "./FileUploadArea";
import "./InputArea.css";

interface Props {
  onSend: (query: string) => void | Promise<void>;
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
  const [uploadedSummary, setUploadedSummary] = useState<string | null>(null);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!text.trim() || disabled) return;
    onSend(text);
    setText("");
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
        {uploadedSummary && (
          <div className="uploaded-summary">{uploadedSummary}</div>
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
              onUploaded={(summary) => setUploadedSummary(summary)}
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
