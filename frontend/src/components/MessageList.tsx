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
  // 是否允许重新生成（run 进行中为 false）
  canRegenerate?: boolean;
  onRegenerate?: () => void;
  // TTS 模型已加载时显示朗读按钮
  ttsLoaded?: boolean;
}

export default function MessageList({
  messages,
  isTyping,
  isPaused,
  runError,
  onReplyAwait,
  canRegenerate,
  onRegenerate,
  ttsLoaded,
}: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const lastAwaiting = messages.some((m) => m.awaitingUser);
  // 最后一张 assistant 卡片 id（重新生成按钮只出现在这张卡片上）
  let lastAssistantLocalId: string | null = null;
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].role === "assistant") {
      lastAssistantLocalId = messages[i].localId;
      break;
    }
  }
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
          <MessageItem
            key={msg.localId}
            message={msg}
            isPaused={isPaused}
            isLastAssistant={msg.localId === lastAssistantLocalId}
            canRegenerate={canRegenerate}
            onRegenerate={onRegenerate}
            ttsLoaded={ttsLoaded}
          />
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
