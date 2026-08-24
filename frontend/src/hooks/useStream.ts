/**
 * 流式状态机 hook：把 WS 事件流转换为 UI 可渲染的 run 状态。
 *
 * 复刻 ui_flet/views/main_window_mixins/stream_typing_mixin.py 的状态聚合：
 * - 一条 assistant 消息由 3 段组成：thinking / tool_call / content
 * - 各段独立累加 stream.delta
 * - run 结束时收到 message.complete，触发打字机 complete()
 * - run_id 守卫：message.complete 即便重复到达只处理一次
 * - 断线重连期间 isPaused=true，暂停打字机 tick
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { WSClient } from "@/api/ws";
import { useTypewriter } from "./useTypewriter";
import type {
  MessageCompleteData,
  StreamDeltaData,
  ToolResultData,
  ToolExecuteData,
  PlanData,
  TokenUsageData,
  AwaitUserData,
  AwaitUserSpec,
  LLMStateData,
  LLMWarningData,
  WSEvent,
} from "@/types/events";

export interface ToolCallInfo {
  // 工具调用流式累加的原始字符串（边输出边渲染）
  raw: string;
  // 工具执行结果（tool.execute.end 的 data，可能含返回值）
  result?: ToolExecuteData;
  // 是否已完成
  done: boolean;
}

export interface RunState {
  runId: string | null;
  thinking: string; // 完整思考文本
  toolCalls: ToolCallInfo[];
  // 当前正在流式输出的段（content / think / tool_call）
  content: string;
  isRunning: boolean;
  isPaused: boolean;
  awaitingUser: boolean;
  awaitUserSpec: AwaitUserSpec | null;
  tokenUsage: TokenUsageData["usage"] | null;
  plan: string | null;
  errorMessage: string | null;
  // 是否因 sidecar 重启被中断
  aborted: boolean;
  // LLM 通信状态（来自 llm.state 事件）
  llmState: LLMStateData | null;
  // LLM 警告（来自 llm.warning 事件）
  llmWarning: string | null;
}

export interface UseStreamReturn {
  state: RunState;
  // 打字机渲染输出（仅 content 段；thinking/toolCall 各自直接渲染全文）
  typedContent: string;
  isTyping: boolean;
  completeTyping: () => void;
  // 等待用户输入时调用（await.user 后用户回复 → 重新调 sendMessage）
  replyToAwait: (message: string) => Promise<void>;
}

interface UseStreamOptions {
  ws: WSClient | null;
  onSendMessage: (query: string) => Promise<void>;
  // 每轮模型发言开始时通知外部新建 assistant 卡片；
  // turn 为上一轮已累积的完整状态（content/thinking/toolCalls），
  // 供外部把上一张卡片补全后再开新卡（否则工具调用会在轮次边界丢失）
  onTurnStart?: (turn: {
    content: string;
    thinking: string;
    toolCalls: ToolCallInfo[];
  }) => void;
  // 工具执行结果通知外部追加独立 tool 卡片
  onToolResult?: (content: string, kind: string) => void;
}

export function useStream(options: UseStreamOptions): UseStreamReturn {
  const { ws, onSendMessage, onTurnStart, onToolResult } = options;

  const [state, setState] = useState<RunState>({
    runId: null,
    thinking: "",
    toolCalls: [],
    content: "",
    isRunning: false,
    isPaused: false,
    awaitingUser: false,
    awaitUserSpec: null,
    tokenUsage: null,
    plan: null,
    errorMessage: null,
    aborted: false,
    llmState: null,
    llmWarning: null,
  });

  // run_id 守卫（防止 message.complete 重复处理）
  const completedRuns = useRef(new Set<string>());
  // 当前 run 是否处于断线重连期间
  const pausedRef = useRef(false);
  // 当前 run 的 turn 计数（用于区分第一次和后续 turn.start）
  const turnCountRef = useRef(0);

  // 主内容打字机：isPaused 由 state 驱动，断线重连期间暂停 tick
  const typewriter = useTypewriter({ isPaused: state.isPaused });

  // 同步 isPaused 到 ref（供其他回调读取最新值）
  useEffect(() => {
    pausedRef.current = state.isPaused;
  }, [state.isPaused]);

  // ------------------------------------------------------------------
  // 事件处理
  // ------------------------------------------------------------------

  const handleStreamDelta = useCallback(
    (event: WSEvent<StreamDeltaData>) => {
      const { msg_type, content: chunk } = event.data;
      console.debug("[useStream] stream.delta", {
        msg_type,
        chunk_len: chunk?.length,
        runId: state.runId,
        event_run_id: event.run_id,
      });
      if (state.runId !== event.run_id) {
        // runId 为 null 时，从 stream.delta 事件兜底初始化（防止 agent.start 丢失）
        if (state.runId === null) {
          console.debug("[useStream] runId 为 null，从 stream.delta 兜底初始化", event.run_id);
          setState((s) => ({
            ...s,
            runId: event.run_id,
            isRunning: true,
          }));
        } else {
          console.warn("[useStream] stream.delta run_id 不匹配，忽略");
          return;
        }
      }
      if (msg_type === "assistant" || msg_type === "content") {
        typewriter.appendDelta(chunk);
      } else if (msg_type === "think") {
        setState((s) => ({ ...s, thinking: s.thinking + chunk }));
      } else if (msg_type === "tool_call") {
        setState((s) => {
          // 简化：累加到最后一个未完成 toolCall，或新建
          const calls = [...s.toolCalls];
          const last = calls[calls.length - 1];
          if (last && !last.done) {
            calls[calls.length - 1] = { ...last, raw: last.raw + chunk };
          } else {
            calls.push({ raw: chunk, done: false });
          }
          return { ...s, toolCalls: calls };
        });
      }
    },
    [state.runId, typewriter],
  );

  const handleTurnStart = useCallback(
    (event: WSEvent) => {
      if (state.runId !== event.run_id) return;
      turnCountRef.current += 1;
      // 第一次 turn.start 对应首张 assistant 卡片，由 startAssistantMessage 创建；
      // 后续 turn.start 表示模型新一轮发言，需独立成卡。
      if (turnCountRef.current > 1) {
        const hasContent =
          typewriter.fullText.trim() || state.thinking.trim() || state.toolCalls.length > 0;
        if (hasContent) {
          typewriter.complete();
          // 用 fullText 而不是 shownText，避免打字机尚未播完时旧卡片内容丢失；
          // thinking/toolCalls 必须一并带出：同步 effect 可能尚未把最后一帧写入 store，
          // 只回传 content 会导致上一张卡片的工具调用在轮次边界丢失（渲染为空卡片）
          onTurnStart?.({
            content: typewriter.fullText,
            thinking: state.thinking,
            toolCalls: state.toolCalls,
          });
          typewriter.reset();
        }
        setState((s) => ({ ...s, thinking: "", toolCalls: [] }));
      }
    },
    [state.runId, state.thinking, state.toolCalls, typewriter, onTurnStart],
  );

  const handleToolExecuteStart = useCallback((event: WSEvent<ToolExecuteData>) => {
    if (state.runId !== event.run_id) return;
    // 标记最后一个 toolCall 为已开始执行（仍累加 raw）
    setState((s) => {
      const calls = [...s.toolCalls];
      if (calls.length > 0) {
        calls[calls.length - 1] = {
          ...calls[calls.length - 1],
          result: event.data,
        };
      }
      return { ...s, toolCalls: calls };
    });
  }, [state.runId]);

  const handleToolExecuteEnd = useCallback((event: WSEvent<ToolExecuteData>) => {
    if (state.runId !== event.run_id) return;
    setState((s) => {
      const calls = [...s.toolCalls];
      if (calls.length > 0) {
        calls[calls.length - 1] = {
          ...calls[calls.length - 1],
          result: event.data,
          done: true,
        };
      }
      return { ...s, toolCalls: calls };
    });
  }, [state.runId]);

  const handleToolResult = useCallback(
    (event: WSEvent<ToolResultData>) => {
      if (state.runId !== event.run_id) return;
      // 工具结果作为独立卡片外抛，不再折叠进 assistant 卡片的 toolCalls
      onToolResult?.(event.data.content, event.data.kind);
    },
    [state.runId, onToolResult],
  );

  const handleTokenUsage = useCallback((event: WSEvent<TokenUsageData>) => {
    if (state.runId !== event.run_id) return;
    setState((s) => ({ ...s, tokenUsage: event.data.usage }));
  }, [state.runId]);

  const handleAwaitUser = useCallback((event: WSEvent<AwaitUserData>) => {
    if (state.runId !== event.run_id) return;
    const rawSpec = event.data.spec;
    let spec: AwaitUserSpec | null = null;
    if (rawSpec && typeof rawSpec === "object") {
      const s = rawSpec as AwaitUserSpec;
      spec = {
        question: typeof s.question === "string" ? s.question : "",
        context: typeof s.context === "string" ? s.context : undefined,
        choices: Array.isArray(s.choices) ? s.choices.filter((c) => typeof c === "string") : undefined,
        raw: typeof s.raw === "string" ? s.raw : undefined,
      };
    } else if (typeof rawSpec === "string") {
      spec = { question: "", raw: rawSpec };
    }
    setState((s) => ({ ...s, awaitingUser: true, awaitUserSpec: spec }));
  }, [state.runId]);

  const handlePlan = useCallback((event: WSEvent<PlanData>) => {
    if (state.runId !== event.run_id) return;
    setState((s) => ({ ...s, plan: event.data.content }));
  }, [state.runId]);

  const handleMessageComplete = useCallback(
    (event: WSEvent<MessageCompleteData>) => {
      // run_id 守卫：幂等
      console.debug("[useStream] message.complete", { run_id: event.run_id, awaiting_user: event.data.awaiting_user });
      if (completedRuns.current.has(event.run_id)) return;
      completedRuns.current.add(event.run_id);

      typewriter.complete();
      setState((s) => ({
        ...s,
        isRunning: false,
        awaitingUser: event.data.awaiting_user,
        // message.complete 时如果 awaiting_user 为 false，清空 spec
        awaitUserSpec: event.data.awaiting_user ? s.awaitUserSpec : null,
      }));
    },
    [typewriter],
  );

  const handleRunAborted = useCallback((event: WSEvent<{ reason: string }>) => {
    setState((s) => ({
      ...s,
      isRunning: false,
      aborted: true,
      errorMessage: `运行中断：${event.data.reason}`,
    }));
  }, []);

  const handleAgentStart = useCallback((event: WSEvent) => {
    // 新 run 启动：重置状态
    console.debug("[useStream] agent.start", { run_id: event.run_id });
    completedRuns.current.delete(event.run_id);
    turnCountRef.current = 0;
    typewriter.reset();
    setState({
      runId: event.run_id,
      thinking: "",
      toolCalls: [],
      content: "",
      isRunning: true,
      isPaused: false,
      awaitingUser: false,
      awaitUserSpec: null,
      tokenUsage: null,
      plan: null,
      errorMessage: null,
      aborted: false,
      llmState: null,
      llmWarning: null,
    });
  }, [typewriter]);

  const handleError = useCallback((event: WSEvent<{ message?: string }>) => {
    setState((s) => ({
      ...s,
      errorMessage: event.data.message ?? "未知错误",
    }));
  }, []);

  const handleLLMState = useCallback((event: WSEvent<LLMStateData>) => {
    setState((s) => ({ ...s, llmState: event.data, llmWarning: null }));
  }, []);

  const handleLLMWarning = useCallback((event: WSEvent<LLMWarningData>) => {
    setState((s) => ({
      ...s,
      llmWarning: event.data.message ?? event.data.warning_type,
    }));
  }, []);

  // ------------------------------------------------------------------
  // 订阅 WS 事件
  // ------------------------------------------------------------------
  // 用 ref 持有最新 handlers，避免 effect 依赖变化导致反复重订阅
  // （重订阅会触发 onStatus 立即回调 setState，引发无限循环）
  const handlersRef = useRef({
    handleAgentStart,
    handleTurnStart,
    handleStreamDelta,
    handleToolExecuteStart,
    handleToolExecuteEnd,
    handleToolResult,
    handleTokenUsage,
    handleAwaitUser,
    handlePlan,
    handleMessageComplete,
    handleRunAborted,
    handleError,
    handleLLMState,
    handleLLMWarning,
  });
  handlersRef.current = {
    handleAgentStart,
    handleTurnStart,
    handleStreamDelta,
    handleToolExecuteStart,
    handleToolExecuteEnd,
    handleToolResult,
    handleTokenUsage,
    handleAwaitUser,
    handlePlan,
    handleMessageComplete,
    handleRunAborted,
    handleError,
    handleLLMState,
    handleLLMWarning,
  };

  useEffect(() => {
    if (!ws) return;
    // 通过 () => handlersRef.current.xxx(e) 订阅，确保每次事件触发都读取最新 handler，
    // 避免 useEffect 按值捕获旧 handler 导致 state.runId/typewriter 过期。
    const unsubs = [
      ws.on("agent.start", (e) => handlersRef.current.handleAgentStart(e as WSEvent)),
      ws.on("turn.start", (e) => handlersRef.current.handleTurnStart(e as WSEvent)),
      ws.on("stream.delta", (e) => handlersRef.current.handleStreamDelta(e as WSEvent<StreamDeltaData>)),
      ws.on("tool.execute.start", (e) => handlersRef.current.handleToolExecuteStart(e as WSEvent<ToolExecuteData>)),
      ws.on("tool.execute.end", (e) => handlersRef.current.handleToolExecuteEnd(e as WSEvent<ToolExecuteData>)),
      ws.on("tool.result", (e) => handlersRef.current.handleToolResult(e as WSEvent<ToolResultData>)),
      ws.on("token.usage", (e) => handlersRef.current.handleTokenUsage(e as WSEvent<TokenUsageData>)),
      ws.on("await.user", (e) => handlersRef.current.handleAwaitUser(e as WSEvent<AwaitUserData>)),
      ws.on("plan", (e) => handlersRef.current.handlePlan(e as WSEvent<PlanData>)),
      ws.on("message.complete", (e) => handlersRef.current.handleMessageComplete(e as WSEvent<MessageCompleteData>)),
      ws.on("run.aborted", (e) => handlersRef.current.handleRunAborted(e as WSEvent<{ reason: string }>)),
      ws.on("error", (e) => handlersRef.current.handleError(e as WSEvent<{ message?: string }>)),
      ws.on("llm.state", (e) => handlersRef.current.handleLLMState(e as WSEvent<LLMStateData>)),
      ws.on("llm.warning", (e) => handlersRef.current.handleLLMWarning(e as WSEvent<LLMWarningData>)),
      // 系统事件（window.show / floating_ball.quit）由 App 层常驻 WS 统一处理，
      // 不在会话级 WS 上重复订阅
    ];

    // WS 状态变化 → 断线期间暂停打字机
    // 只在状态真正变化时 setState（onStatus 首次立即回调也会触发）
    let lastStatus: string | null = null;
    const unsubStatus = ws.onStatus((status) => {
      if (status === lastStatus) return;
      lastStatus = status;
      const paused = status === "reconnecting" || status === "closed";
      setState((s) => (s.isPaused === paused ? s : { ...s, isPaused: paused }));
    });

    return () => {
      unsubs.forEach((u) => u?.());
      unsubStatus();
    };
  }, [ws]);

  // ------------------------------------------------------------------
  // 对外 API
  // ------------------------------------------------------------------

  const replyToAwait = useCallback(
    async (message: string) => {
      setState((s) => ({ ...s, awaitingUser: false, awaitUserSpec: null }));
      await onSendMessage(message);
    },
    [onSendMessage],
  );

  return {
    state,
    typedContent: typewriter.shownText,
    isTyping: typewriter.isTyping,
    completeTyping: typewriter.complete,
    replyToAwait,
  };
}
