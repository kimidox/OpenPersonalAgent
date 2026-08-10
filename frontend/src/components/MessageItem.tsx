import { useState } from "react";
import type { DisplayMessage } from "@/store/chat";
import { parseQueryFiles, type ParsedFileEntry } from "@/utils/fileTags";
import MarkdownRenderer from "./MarkdownRenderer";
import "./MessageItem.css";

interface Props {
  message: DisplayMessage;
  isPaused: boolean;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function FileTagCard({ file }: { file: ParsedFileEntry }) {
  const sizeStr = formatFileSize(new Blob([file.content]).size);
  return (
    <div className="file-attachment-card">
      <div className="file-attachment-icon">📎</div>
      <div className="file-attachment-info">
        <div className="file-attachment-name">{file.filename}</div>
        <div className="file-attachment-meta">
          <span>{sizeStr}</span>
        </div>
      </div>
    </div>
  );
}

function ToolResultCard({ message }: { message: DisplayMessage }) {
  const [expanded, setExpanded] = useState(false);
  const kind = message.toolResultKind || "tool";
  const summaryText = message.content
    ? `${message.content.slice(0, 80)}${message.content.length > 80 ? "..." : ""}`
    : "(无内容)";

  return (
    <div className="message-item tool">
      <div className="message-bubble tool-bubble">
        <button
          type="button"
          className="tool-summary"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
        >
          <span className="tool-kind">{kind}</span>
          <span className="tool-summary-text">{summaryText}</span>
          <span className="tool-toggle">{expanded ? "收起" : "展开"}</span>
        </button>
        {expanded && <pre className="tool-result">{message.content}</pre>}
      </div>
    </div>
  );
}

export default function MessageItem({ message, isPaused }: Props) {
  if (message.role === "user") {
    // 解析 query 中的 <Files> 标签，分离原生文本和文件列表
    const { text, files } = parseQueryFiles(message.content);
    return (
      <div className="message-item user">
        <div className="message-bubble user-bubble">
          {files.length > 0 && (
            <div className="attachments-block">
              {files.map((f, i) => (
                <FileTagCard key={i} file={f} />
              ))}
            </div>
          )}
          <div className="message-content">{text}</div>
        </div>
      </div>
    );
  }

  if (message.role === "tool") {
    return <ToolResultCard message={message} />;
  }

  // assistant
  const isStreaming = message.isStreaming;
  const showCursor = isStreaming && !isPaused;

  return (
    <div className="message-item assistant">
      <div className="message-bubble assistant-bubble">
        {message.thinking && (
          <details className="thinking-block" open={isStreaming && !message.content}>
            <summary>思考过程</summary>
            <div className="thinking-content">{message.thinking}</div>
          </details>
        )}

        {message.toolCalls && message.toolCalls.length > 0 && (
          <div className="tool-calls">
            {message.toolCalls.map((tc, i) => (
              <details key={i} className="tool-call-block">
                <summary>
                  {tc.raw ? `工具调用：${tc.raw.slice(0, 80)}${tc.raw.length > 80 ? "..." : ""}` : "工具调用"}
                  {tc.done && <span className="tool-done"> ✓</span>}
                </summary>
                {tc.raw && <pre className="tool-raw">{tc.raw}</pre>}
                {tc.result != null && (
                  <pre className="tool-result">
                    {typeof tc.result === "string"
                      ? tc.result
                      : JSON.stringify(tc.result, null, 2)}
                  </pre>
                )}
              </details>
            ))}
          </div>
        )}

        {message.content && (
          <div className="message-content">
            <MarkdownRenderer content={message.content} />
            {showCursor && <span className="typing-cursor">▋</span>}
          </div>
        )}

        {!message.content && !message.thinking && (!message.toolCalls || message.toolCalls.length === 0) && (
          <div className="message-content placeholder">
            {isStreaming ? "正在思考..." : "(空)"}
          </div>
        )}

        {message.aborted && (
          <div className="aborted-tag">运行中断，请重发</div>
        )}
      </div>
    </div>
  );
}
