import { useEffect, useRef, useState } from "react";
import type { DisplayMessage } from "@/store/chat";
import type { AwaitUserSpec } from "@/types/events";
import MessageItem from "./MessageItem";
import AwaitUserCard from "./AwaitUserCard";
import "./MessageList.css";

interface Props {
  messages: DisplayMessage[];
  isTyping: boolean;
  isPaused: boolean;
  runError: string | null;
  onReplyAwait: (message: string) => Promise<void>;
}

export default function MessageList({
  messages,
  isTyping,
  isPaused,
  runError,
  onReplyAwait,
}: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const lastAwaiting = messages.some((m) => m.awaitingUser);
  // 从最后一条 awaitingUser=true 的消息中提取 spec
  const lastAwaitSpec: AwaitUserSpec | null = (() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].awaitingUser && messages[i].awaitUserSpec) {
        return messages[i].awaitUserSpec;
      }
    }
    return null;
  })() ?? null;

  // 自动滚动到底部（仅在用户已滚动到底时）
  useEffect(() => {
    if (!autoScroll) return;
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messages, isTyping, autoScroll]);

  function handleScroll() {
    const el = scrollRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 50;
    setAutoScroll(atBottom);
  }

  if (messages.length === 0) {
    return (
      <div className="message-list empty">
        <div className="msg-empty-hint">输入消息开始对话</div>
      </div>
    );
  }

  return (
    <div className="message-list" ref={scrollRef} onScroll={handleScroll}>
      <div className="message-list-inner">
        {messages.map((msg) => (
          <MessageItem key={msg.localId} message={msg} isPaused={isPaused} />
        ))}
        {isPaused && (
          <div className="reconnect-hint">连接中断，正在重连...</div>
        )}
        {runError && !lastAwaiting && (
          <div className="run-error-inline">{runError}</div>
        )}
        {lastAwaiting && (
          <AwaitUserCard spec={lastAwaitSpec} onReply={onReplyAwait} />
        )}
      </div>
    </div>
  );
}
