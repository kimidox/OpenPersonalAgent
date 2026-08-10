import { useCallback, useEffect, useRef, useState } from "react";
import { useChatStore, type DisplayMessage } from "@/store/chat";
import { api, APIError } from "@/api/client";
import { WSClient } from "@/api/ws";
import { useStream } from "@/hooks/useStream";
import type { FileAttachment } from "@/types/api";
import { buildQueryWithFiles } from "@/utils/fileTags";
import ConversationSidebar from "./ConversationSidebar";
import MessageList from "./MessageList";
import InputArea from "./InputArea";
import LLMStatusIndicator from "./LLMStatusIndicator";
import "./ChatPage.css";

export default function ChatPage() {
  const store = useChatStore();
  const {
    conversations,
    currentConversationId,
    messages,
    loadingConversations,
    loadingMessages,
    loadConversations,
    selectConversation,
    createConversation,
    deleteConversation,
    updateConversationTitle,
    appendUserMessage,
    startAssistantMessage,
    newAssistantMessage,
    updateAssistantMessage,
    completeAssistantMessage,
    appendToolResultMessage,
    setMessages,
  } = store;

  const [enableThinking, setEnableThinking] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  // 当前会话的 WS 客户端：用 state 而非 ref，使 ws 变化能触发 useStream 重新订阅
  const [ws, setWs] = useState<WSClient | null>(null);

  // 初始化：加载会话列表
  useEffect(() => {
    loadConversations();
  }, [loadConversations]);

  // handleSend 必须在 useStream 之前定义（useStream 的 onSendMessage 依赖它）
  const handleSend = useCallback(
    async (query: string, attachments?: FileAttachment[]) => {
      if (!currentConversationId) {
        setSendError("请先选择或创建会话");
        return;
      }
      if (!query.trim()) return;

      setSendError(null);

      // 构造带 <Files> 标签的完整 query：文件内容嵌入标签内
      const fullQuery = buildQueryWithFiles(query, attachments);
      // store 中存完整 query（含标签），渲染时由 MessageItem 解析剥离
      appendUserMessage(fullQuery);

      try {
        const resp = await api.sendMessage(currentConversationId, {
          query: fullQuery,
          enable_thinking: enableThinking,
          queued_ok: true,
          source: "main",
        });
        if (resp.status === "queued") {
          setSendError(`已排队，位置 ${resp.position}`);
        }
        startAssistantMessage(resp.run_id);
      } catch (err) {
        const msg = err instanceof APIError ? err.detail : String(err);
        setSendError(`发送失败：${msg}`);
      }
    },
    [
      currentConversationId,
      enableThinking,
      appendUserMessage,
      startAssistantMessage,
    ],
  );

  // 切换会话：重建 WS
  useEffect(() => {
    if (!currentConversationId) {
      setWs((prev) => {
        prev?.close();
        return null;
      });
      return;
    }

    // REST 重建回调（replay.missed 时由 WSClient 触发）
    const rebuildFromRest = async () => {
      try {
        const detail = await api.getConversation(currentConversationId);
        const restored: DisplayMessage[] = detail.messages
          .filter(
            (m) =>
              !(m.role === "assistant" && !m.content && m.metadata?.type === "tool_call"),
          )
          .map((m, i) => ({
            localId: `restored-${i}`,
            role: (m.role as "user" | "assistant" | "system" | "tool") ?? "assistant",
            content:
              typeof m.content === "string" ? m.content : JSON.stringify(m.content),
            timestamp: m.timestamp
              ? new Date(m.timestamp).getTime()
              : Date.now(),
          }));
        setMessages(restored);
      } catch (err) {
        console.error("[ChatPage] REST 重建失败:", err);
      }
    };

    const wsClient = new WSClient(currentConversationId, rebuildFromRest);
    setWs(wsClient);
    wsClient.connect();

    return () => {
      wsClient.close();
    };
  }, [currentConversationId, setMessages]);

  const handleTurnStart = useCallback(
    (currentContent: string) => {
      // 先把上一轮 assistant 卡片的 content 落盘，再新建一张空卡片
      updateAssistantMessage({ content: currentContent });
      newAssistantMessage();
    },
    [updateAssistantMessage, newAssistantMessage],
  );

  const handleToolResult = useCallback(
    (content: string, kind: string) => {
      appendToolResultMessage(content, kind);
    },
    [appendToolResultMessage],
  );

  const { state: runState, typedContent, isTyping, completeTyping, replyToAwait } =
    useStream({
      ws,
      onSendMessage: handleSend,
      onTurnStart: handleTurnStart,
      onToolResult: handleToolResult,
      // 阶段 5/6：悬浮球触发的系统事件 → Tauri invoke 控制 native 窗口
      onWindowShow: () => {
        console.log("[ChatPage] 收到 window.show 事件（悬浮球请求显示主窗口）");
        // Tauri 模式：invoke('show_main_window') → Rust 调 webview.show()+setFocus()
        // 浏览器 dev 模式：window.focus() 兜底
        if (typeof window !== "undefined" && "__TAURI_INTERNALS__" in window) {
          import("@tauri-apps/api/core")
            .then(({ invoke }) => invoke("show_main_window"))
            .catch((err) => console.error("[ChatPage] show_main_window 失败:", err));
        } else {
          try {
            window.focus();
          } catch {
            /* noop */
          }
        }
      },
      onFloatingBallQuit: () => {
        console.log("[ChatPage] 收到 floating_ball.quit 事件（悬浮球请求退出应用）");
        // Tauri 模式：invoke('quit_app') → Rust stop sidecar + app.exit(0)
        // 浏览器 dev 模式：仅记录日志（不打断开发）
        if (typeof window !== "undefined" && "__TAURI_INTERNALS__" in window) {
          import("@tauri-apps/api/core")
            .then(({ invoke }) => invoke("quit_app"))
            .catch((err) => console.error("[ChatPage] quit_app 失败:", err));
        }
      },
    });

  // 把 run 状态同步到 store 的 assistant 消息
  // 用 ref 跟踪已同步的 runId/content/thinking，避免相同内容重复同步触发无限循环
  const lastSyncRef = useRef<{
    runId: string | null;
    content: string;
    thinking: string;
  }>({ runId: null, content: "", thinking: "" });
  useEffect(() => {
    if (!runState.runId) return;
    const storeMessages = useChatStore.getState().messages;
    const last = storeMessages[storeMessages.length - 1];
    if (!last || !last.isStreaming) return;

    // 新 run 启动时重置同步标记
    if (lastSyncRef.current.runId !== runState.runId) {
      lastSyncRef.current = {
        runId: runState.runId,
        content: "",
        thinking: "",
      };
    }

    const contentChanged = lastSyncRef.current.content !== typedContent;
    const thinkingChanged = lastSyncRef.current.thinking !== runState.thinking;

    // 运行中仅当内容/思考发生变化时同步；结束时必须同步并标记完成
    if (!contentChanged && !thinkingChanged && runState.isRunning) return;

    lastSyncRef.current = {
      runId: runState.runId,
      content: typedContent,
      thinking: runState.thinking,
    };

    updateAssistantMessage({
      content: typedContent,
      thinking: runState.thinking,
      toolCalls: runState.toolCalls,
      awaitingUser: runState.awaitingUser,
      aborted: runState.aborted,
    });

    if (!runState.isRunning) {
      completeAssistantMessage();
    }
  }, [
    runState,
    typedContent,
    updateAssistantMessage,
    completeAssistantMessage,
  ]);

  // 思考模式开关
  useEffect(() => {
    api.agentThinking().then((r) => setEnableThinking(r.enabled)).catch(() => {});
  }, []);

  async function handleStop() {
    if (!currentConversationId) return;
    try {
      await api.stopConversation(currentConversationId);
      completeTyping();
    } catch (err) {
      console.error("[ChatPage] 停止失败:", err);
    }
  }

  async function handleNewConversation() {
    try {
      await createConversation();
    } catch (err) {
      console.error("[ChatPage] 新建会话失败:", err);
    }
  }

  async function handleThinkingChange(enabled: boolean) {
    setEnableThinking(enabled);
    try {
      await api.setAgentThinking(enabled);
    } catch (err) {
      console.error("[ChatPage] 切换思考模式失败:", err);
    }
  }

  const isRunning = runState.isRunning;

  return (
    <div className="chat-page">
      <ConversationSidebar
        conversations={conversations}
        currentId={currentConversationId}
        loading={loadingConversations}
        onSelect={selectConversation}
        onNew={handleNewConversation}
        onDelete={deleteConversation}
        onRename={updateConversationTitle}
      />
      <main className="chat-main">
        <header className="chat-header">
          <h2>
            {store.currentConversation?.title || "未选择会话"}
          </h2>
          {runState.errorMessage && (
            <span className="run-error">{runState.errorMessage}</span>
          )}
          <LLMStatusIndicator
            state={runState.llmState}
            warning={runState.llmWarning}
          />
        </header>

        {!currentConversationId ? (
          <div className="empty-state">
            <p>请从左侧选择会话，或点击"新建会话"开始对话。</p>
          </div>
        ) : loadingMessages ? (
          <div className="empty-state">加载消息中...</div>
        ) : (
          <MessageList
            messages={messages}
            isTyping={isTyping}
            isPaused={runState.isPaused}
            runError={runState.errorMessage}
            onReplyAwait={replyToAwait}
          />
        )}

        {sendError && <div className="send-error">{sendError}</div>}

        <InputArea
          onSend={handleSend}
          onStop={handleStop}
          isRunning={isRunning}
          awaitingUser={runState.awaitingUser}
          disabled={!currentConversationId}
          enableThinking={enableThinking}
          onThinkingChange={handleThinkingChange}
        />
      </main>
    </div>
  );
}
