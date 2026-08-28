import { useEffect, useMemo, useState } from "react";
import FileUploadArea from "./FileUploadArea";
import SlashReferenceMenu, { type SlashEntry } from "./SlashReferenceMenu";
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
  // 「/」强制引用占位：选中后以图标 chip 形式展示，发送时还原为 /skill:id 标记
  const [slashRefs, setSlashRefs] = useState<SlashEntry[]>([]);

  // 「/」强制引用菜单：输入以 "/" 开头且未输入空格时弹出
  const slashKeyword = useMemo(() => {
    if (!text.startsWith("/")) return null;
    const m = text.slice(1).match(/^(\S*)/);
    return m ? m[1] : "";
  }, [text]);
  // 选中/关闭后抑制菜单，直到 "/" 前缀消失后重新进入
  const [slashDismissed, setSlashDismissed] = useState(false);
  useEffect(() => {
    if (slashKeyword === null) setSlashDismissed(false);
  }, [slashKeyword]);
  const slashMenuOpen = slashKeyword !== null && !disabled && !slashDismissed;

  function handleSlashSelect(entry: SlashEntry) {
    // 以占位 chip 代替裸文本标记；移除当前 "/" 关键字
    const rest = text.replace(/^\/\S*/, "");
    setText(rest);
    setSlashRefs((prev) =>
      prev.some((r) => r.kind === entry.kind && r.id === entry.id)
        ? prev
        : [...prev, entry],
    );
    setSlashDismissed(true);
  }

  function removeSlashRef(index: number) {
    setSlashRefs((prev) => prev.filter((_, i) => i !== index));
  }

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
    // 占位 chip 还原为 /skill:id / /cli:name 标记前缀，随消息发送
    const refPrefix = slashRefs.map((r) => `/${r.kind}:${r.id}`).join(" ");
    const outgoing = refPrefix ? `${refPrefix} ${text}` : text;
    onSend(outgoing, hasAttachments ? attachments : undefined);
    setText("");
    setAttachments([]);
    setSlashRefs([]);
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
        {slashMenuOpen && slashKeyword !== null && (
          <SlashReferenceMenu
            filter={slashKeyword}
            onSelect={handleSlashSelect}
            onClose={() => setSlashDismissed(true)}
          />
        )}
        {slashRefs.length > 0 && (
          <div className="attachments-list">
            {slashRefs.map((ref, i) => (
              <div
                key={`${ref.kind}:${ref.id}`}
                className={`slash-ref-chip ${ref.kind}`}
                title={`${ref.kind === "skill" ? "Skill" : "CLI"}：${ref.label}`}
              >
                <svg
                  className="slash-ref-icon"
                  viewBox="0 0 16 16"
                  aria-hidden="true"
                >
                  {ref.kind === "skill" ? (
                    <path d="M9 1 3 9h4l-1 6 6-8H8l1-6z" />
                  ) : (
                    <>
                      <rect x="2" y="2" width="12" height="12" rx="2" />
                      <path d="M5.5 6l5 5M10.5 6l-5 5" />
                    </>
                  )}
                </svg>
                <span>{ref.label}</span>
                <button
                  type="button"
                  className="attachment-remove"
                  onClick={() => removeSlashRef(i)}
                  aria-label="移除引用"
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        )}
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
              : "输入消息，Ctrl+Enter 发送；输入 / 强制引用 Skill 或 CLI"
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
