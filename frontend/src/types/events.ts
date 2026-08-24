/**
 * 后端 WS 事件类型（与 backend_service/ws/events.py 对齐）。
 *
 * 公共字段：event / event_id / conversation_id / run_id / timestamp / data
 * 重放语义见 frontend-tauri-refactor.md 3.14 节。
 */

export type WSEventName =
  | "agent.start"
  | "agent.end"
  | "turn.start"
  | "turn.end"
  | "tool.execute.start"
  | "tool.execute.end"
  | "steering.received"
  | "followup.received"
  | "error"
  | "stream.delta"
  | "tool.result"
  | "token.usage"
  | "await.user"
  | "plan"
  | "llm.state"
  | "llm.warning"
  | "message.complete"
  | "run.queued"
  | "run.aborted"
  | "replay.missed"
  | "recording.delta"
  | "window.show"
  | "floating_ball.quit";

export interface WSEvent<T = unknown> {
  event: WSEventName;
  event_id: number;
  conversation_id: string;
  run_id: string;
  timestamp: number;
  data: T;
}

// stream.delta 的 data
export interface StreamDeltaData {
  // 后端理论上会映射为 assistant，但保留 content 兜底
  msg_type: "assistant" | "content" | "think" | "tool_call";
  chunk_type: "content" | "think" | "tool_call";
  content: string;
  is_final: boolean;
}

export interface ToolResultData {
  content: string;
  kind: "tool" | "base_tool";
}

export interface TokenUsageData {
  usage: Record<string, unknown> | { raw: string };
}

export interface AwaitUserSpec {
  question: string;
  context?: string;
  choices?: string[];
  raw?: string;
}

export interface AwaitUserData {
  spec: AwaitUserSpec | Record<string, unknown> | { raw: string };
}

export interface PlanData {
  content: string;
}

export interface LLMStateData {
  state: string;
  model: string | null;
  session_id: string | null;
  duration_ms: number;
  error_message: string | null;
}

export interface LLMWarningData {
  warning_type: string;
  state: string;
  duration_ms: number;
  message: string;
}

export interface MessageCompleteData {
  result: string;
  awaiting_user: boolean;
}

export interface RunAbortedData {
  reason: string;
}

export interface ReplayMissedData {
  last_event_id: number;
}

export interface ToolExecuteData {
  // AgentEvent.data 透传，结构由 SkillAgent 决定
  [key: string]: unknown;
}
