import { useState } from "react";
import "./AwaitUserCard.css";

interface Props {
  onReply: (message: string) => Promise<void>;
}

export default function AwaitUserCard({ onReply }: Props) {
  const [text, setText] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    setSubmitting(true);
    try {
      await onReply(text);
      setText("");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="await-user-card">
      <div className="await-icon">✋</div>
      <div className="await-body">
        <div className="await-title">等待你的回复</div>
        <form onSubmit={handleSubmit} className="await-form">
          <input
            type="text"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="输入回复，回车提交"
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
