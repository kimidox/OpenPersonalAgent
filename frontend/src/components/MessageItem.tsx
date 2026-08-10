import { useState } from "react";
import type { DisplayMessage } from "@/store/chat";
import MarkdownRenderer from "./MarkdownRenderer";
import "./MessageItem.css";

interface Props {
  message: DisplayMessage;
  isPaused: boolean;
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
    return (
      <div className="message-item user">
        <div className="message-bubble user-bubble">
          <div className="message-content">{message.content}</div>
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
