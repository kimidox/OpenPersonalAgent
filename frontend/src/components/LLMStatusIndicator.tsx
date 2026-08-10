/**
 * LLM 通信状态指示器。
 *
 * 复刻 ui_flet/components/llm_status_indicator.py：
 * 5 种状态映射（IDLE / SENDING_REQUEST / WAITING_FOR_RESPONSE / RECEIVING_STREAM / COMMUNICATION_ENDED）。
 *
 * 数据来源：
 * - WS 事件 `llm.state`（msg_type=llm_state_update）→ 实时状态
 * - WS 事件 `llm.warning` → 警告覆盖
 *
 * 使用方式：在 ChatPage header 中渲染，由父组件传入当前 state。
 */

import type { LLMStateData } from "@/types/events";

export type LLMStatusKind =
  | "idle"
  | "sending"
  | "waiting"
  | "receiving"
  | "ended";

interface Props {
  state: LLMStateData | null;
  warning?: string | null;
}

const STATUS_MAP: Record<
  string,
  { kind: LLMStatusKind; label: string; icon: string }
> = {
  IDLE: { kind: "idle", label: "空闲", icon: "○" },
  SENDING_REQUEST: { kind: "sending", label: "正在发送请求", icon: "↑" },
  WAITING_FOR_RESPONSE: { kind: "waiting", label: "等待响应中", icon: "⏳" },
  RECEIVING_STREAM: { kind: "receiving", label: "正在接收响应", icon: "✨" },
  COMMUNICATION_ENDED: { kind: "ended", label: "通信结束", icon: "✓" },
};

export default function LLMStatusIndicator({ state, warning }: Props) {
  if (!state && !warning) return null;

  const stateName = state?.state ?? "IDLE";
  const mapping = STATUS_MAP[stateName] ?? STATUS_MAP.IDLE;
  const durationMs = state?.duration_ms ?? 0;

  if (warning) {
    return (
      <span className="llm-status-indicator ended" title={warning}>
        <span className="status-icon">⚠</span>
        <span className="status-text">{warning}</span>
      </span>
    );
  }

  return (
    <span className={`llm-status-indicator ${mapping.kind}`}>
      <span className="status-icon">{mapping.icon}</span>
      <span className="status-text">
        {mapping.label}
        {durationMs > 0 && ` (${durationMs}ms)`}
      </span>
    </span>
  );
}
