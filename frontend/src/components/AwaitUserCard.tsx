import { useState } from "react";
import type { AwaitUserSpec } from "@/types/events";
import "./AwaitUserCard.css";

interface Props {
  spec: AwaitUserSpec | null;
  onReply: (message: string) => Promise<void>;
}

export default function AwaitUserCard({ spec, onReply }: Props) {
  const [text, setText] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    await submitReply(text);
  }

  async function submitReply(message: string) {
    if (submitting) return;
    setSubmitting(true);
    try {
      await onReply(message);
      setText("");
    } finally {
      setSubmitting(false);
    }
  }

  const question = spec?.question?.trim();
  const context = spec?.context?.trim();
  const choices =
    Array.isArray(spec?.choices) && spec!.choices!.length > 0 ? spec!.choices! : null;

  const displayQuestion = question || "等待你的回复";

  return (
    <div className="await-user-card">
      <div className="await-icon">✋</div>
      <div className="await-body">
        <div className="await-title">{displayQuestion}</div>

        {context && (
          <div className="await-context">{context}</div>
        )}

        {choices ? (
          <div className="await-choices">
            {choices.map((choice, i) => (
              <button
                key={i}
                type="button"
                className="await-choice-btn"
                onClick={() => submitReply(choice)}
                disabled={submitting}
              >
                {choice}
              </button>
            ))}
          </div>
        ) : null}

        <form onSubmit={handleSubmit} className="await-form">
          <input
            type="text"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={choices ? "或输入自定义回复，回车提交" : "输入回复，回车提交"}
            className="await-input"
            disabled={submitting}
            autoFocus
          />
          <button type="submit" className="await-submit" disabled={submitting || !text.trim()}>
            回复
          </button>
        </form>
      </div>
    </div>
  );
}
