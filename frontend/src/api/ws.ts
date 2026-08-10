/**
 * WebSocket 客户端：重连 + event_id 单调跟踪 + ?since= 重放对齐。
 *
 * 见 frontend-tauri-refactor.md 3.14 节。
 * - 断线指数退避（500ms → 30s）
 * - 重连带 ?since={lastEventId}，服务端重放 event_id > since 的所有事件
 * - 收到 replay.missed → 触发 onReplayMissed，上层改走 REST 重建
 * - event_id 去重（seenEventIds Set，窗口 2000 条）
 */

import type { WSEvent, WSEventName } from "@/types/events";
import { getWsUrl } from "./backend";

type EventListener = (event: WSEvent) => void;
type StatusListener = (status: WSStatus) => void;

export type WSStatus =
  | "connecting"
  | "open"
  | "closed"
  | "reconnecting"
  | "failed";

const BACKOFF_MS = [500, 1000, 2000, 5000, 10000, 30000];

export class WSClient {
  private ws: WebSocket | null = null;
  private conversationId: string;
  private lastEventId = 0;
  private seenIds = new Set<number>();
  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private status: WSStatus = "closed";
  private listeners = new Map<WSEventName, Set<EventListener>>();
  private statusListeners = new Set<StatusListener>();
  private onReplayMissed?: () => void;
  private intentionallyClosed = false;

  constructor(conversationId: string, onReplayMissed?: () => void) {
    this.conversationId = conversationId;
    this.onReplayMissed = onReplayMissed;
  }

  // ------------------------------------------------------------------
  // 订阅
  // ------------------------------------------------------------------

  on<T extends WSEvent>(eventName: WSEventName, listener: (e: T) => void): () => void {
    if (!this.listeners.has(eventName)) {
      this.listeners.set(eventName, new Set());
    }
    this.listeners.get(eventName)!.add(listener as EventListener);
    return () => this.listeners.get(eventName)?.delete(listener as EventListener);
  }

  onStatus(listener: StatusListener): () => void {
    this.statusListeners.add(listener);
    listener(this.status);
    return () => this.statusListeners.delete(listener);
  }

  private emit(event: WSEvent): void {
    // event_id 去重（系统事件 event_id=0 不去重）
    if (event.event_id > 0) {
      if (this.seenIds.has(event.event_id)) return;
      this.seenIds.add(event.event_id);
      // 维护窗口上限
      if (this.seenIds.size > 2000) {
        const first = this.seenIds.values().next().value;
        if (first !== undefined) this.seenIds.delete(first);
      }
      this.lastEventId = Math.max(this.lastEventId, event.event_id);
    }
    this.listeners.get(event.event)?.forEach((l) => l(event));
  }

  private setStatus(status: WSStatus): void {
    this.status = status;
    this.statusListeners.forEach((l) => l(status));
  }

  // ------------------------------------------------------------------
  // 连接
  // ------------------------------------------------------------------

  connect(): void {
    this.intentionallyClosed = false;
    this.doConnect();
  }

  private doConnect(): void {
    this.setStatus(this.reconnectAttempts === 0 ? "connecting" : "reconnecting");
    const url = `${getWsUrl()}?conversation_id=${encodeURIComponent(
      this.conversationId,
    )}&since=${this.lastEventId}`;

    try {
      this.ws = new WebSocket(url);
    } catch (err) {
      console.error("[WS] 构造失败:", err);
      this.scheduleReconnect();
      return;
    }

    this.ws.onopen = () => {
      this.reconnectAttempts = 0;
      this.setStatus("open");
    };

    this.ws.onmessage = (ev) => {
      try {
        const event = JSON.parse(ev.data) as WSEvent;
        console.debug("[WS] 收到消息", {
          event: event.event,
          event_id: event.event_id,
          run_id: event.run_id,
          data_keys: event.data ? Object.keys(event.data) : [],
        });
        // replay.missed：服务端告知 since 过期，需走 REST 重建
        if (event.event === "replay.missed") {
          console.warn(
            `[WS] replay.missed: lastEventId=${this.lastEventId}, 改走 REST 重建`,
          );
          // 重置 lastEventId，避免下次重连仍用过期值
          this.lastEventId = 0;
          this.seenIds.clear();
          this.onReplayMissed?.();
          return;
        }
        this.emit(event);
      } catch (err) {
        console.error("[WS] 解析消息失败:", err, ev.data);
      }
    };

    this.ws.onerror = (err) => {
      console.error("[WS] error:", err);
    };

    this.ws.onclose = () => {
      if (this.intentionallyClosed) {
        this.setStatus("closed");
        return;
      }
      this.scheduleReconnect();
    };
  }

  private scheduleReconnect(): void {
    const delay =
      BACKOFF_MS[Math.min(this.reconnectAttempts, BACKOFF_MS.length - 1)];
    this.reconnectAttempts++;
    this.setStatus("reconnecting");
    console.warn(
      `[WS] ${delay}ms 后第 ${this.reconnectAttempts} 次重连 (lastEventId=${this.lastEventId})`,
    );
    this.reconnectTimer = setTimeout(() => this.doConnect(), delay);
  }

  close(): void {
    this.intentionallyClosed = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this.setStatus("closed");
  }

  // ------------------------------------------------------------------
  // 状态查询
  // ------------------------------------------------------------------

  isConnected(): boolean {
    return this.status === "open";
  }

  getLastEventId(): number {
    return this.lastEventId;
  }
}
