"""WebSocket 连接管理：按 conversation_id 分组广播 + event_id 单调分配 + 事件重放。

设计要点（见 frontend-tauri-refactor.md 3.14）：
- 每个 conversation_id 维护独立的 event_id 计数器（单调递增，从 1 开始）。
- 每个 conversation_id 维护一个环形事件日志（5 分钟 / 1000 条上限），
  供客户端断线重连时按 `?since={lastEventId}` 重放。
- broadcast 是 async 函数，由 stream_bridge 通过
  `asyncio.run_coroutine_threadsafe(..., loop)` 从工作线程投递到事件循环。
- 同一 conversation_id 可多客户端订阅（广播）。
"""
from __future__ import annotations

import asyncio
import time
import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket

from backend_service.ws.events import WSEvent, replay_missed


# 事件日志保留策略
_EVENT_LOG_TTL_S = 300.0        # 5 分钟
_EVENT_LOG_MAX_PER_CONV = 1000  # 每 conversation 最多保留 1000 条


@dataclass
class _Client:
    """一个 WS 连接的内部表示。"""
    ws: WebSocket
    conversation_id: str
    seen_event_ids: set[int] = field(default_factory=set)


@dataclass
class _LoggedEvent:
    """事件日志条目（用于重放）。"""
    event_id: int
    payload: dict[str, Any]   # 已序列化的 dict（含 event_id）
    timestamp: float


class WSManager:
    """WebSocket 连接与事件日志管理（单例，由 deps 持有）。"""

    def __init__(self) -> None:
        # conversation_id -> 已连接客户端列表
        self._clients: dict[str, list[_Client]] = defaultdict(list)
        # conversation_id -> 事件日志（按 event_id 升序）
        self._event_log: dict[str, deque[_LoggedEvent]] = defaultdict(deque)
        # conversation_id -> 下一个 event_id（从 1 开始）
        self._next_event_id: dict[str, int] = defaultdict(int)
        # 保护 _clients / _event_log / _next_event_id 的锁
        # （broadcast 可能从工作线程经 run_coroutine_threadsafe 进入事件循环，
        #  但事件循环内仍可能并发处理多个 broadcast，锁保险）
        self._lock = threading.Lock()
        self._logger: Any = None  # 延迟注入，避免循环导入

    # ------------------------------------------------------------------
    # 日志与依赖
    # ------------------------------------------------------------------

    def set_logger(self, logger: Any) -> None:
        self._logger = logger

    def _log(self, level: str, msg: str) -> None:
        if self._logger is None:
            return
        getattr(self._logger, level)(msg)

    # ------------------------------------------------------------------
    # 连接生命周期
    # ------------------------------------------------------------------

    async def connect(
        self,
        ws: WebSocket,
        conversation_id: str,
        *,
        since: int = 0,
    ) -> None:
        """接受 WS 连接，可选先重放 since 之后的事件。

        Args:
            since: 客户端上次收到的最大 event_id；0 表示不重放。
        """
        await ws.accept()

        client = _Client(ws=ws, conversation_id=conversation_id)
        with self._lock:
            self._clients[conversation_id].append(client)

        self._log("info", f"WS 客户端已连接: conversation_id={conversation_id[:8]}..., since={since}")

        # 重放（若 since > 0）
        if since > 0:
            await self._replay(client, since)

    async def disconnect(self, ws: WebSocket, conversation_id: str) -> None:
        """移除客户端连接（不关闭 ws，由路由层负责）。"""
        with self._lock:
            clients = self._clients.get(conversation_id, [])
            self._clients[conversation_id] = [c for c in clients if c.ws is not ws]
            if not self._clients[conversation_id]:
                del self._clients[conversation_id]
        self._log("info", f"WS 客户端已断开: conversation_id={conversation_id[:8]}...")

    # ------------------------------------------------------------------
    # 重放
    # ------------------------------------------------------------------

    async def _replay(self, client: _Client, since: int) -> None:
        """向 client 重放 event_id > since 的事件。

        若 since 已不在事件日志窗口内（log 中最早 event_id > since+1，
        说明中间事件已过期）→ 发 replay.missed。
        """
        with self._lock:
            log = list(self._event_log.get(client.conversation_id, []))

        if not log:
            # 无任何事件可重放——客户端 since 可能已过期，或本会话无事件
            # 仍发 replay.missed 让客户端走 REST 重建
            missed = replay_missed(
                conversation_id=client.conversation_id,
                last_event_id=since,
            )
            # replay.missed 不分配 event_id（系统事件）
            await self._safe_send(client.ws, missed.to_dict())
            return

        earliest = log[0].event_id
        if since + 1 < earliest:
            # 中间事件已过期
            missed = replay_missed(
                conversation_id=client.conversation_id,
                last_event_id=since,
            )
            await self._safe_send(client.ws, missed.to_dict())
            return

        # 顺序重放 event_id > since 的事件
        for entry in log:
            if entry.event_id > since:
                await self._safe_send(client.ws, entry.payload)
        self._log("info", f"已重放 {sum(1 for e in log if e.event_id > since)} 条事件给 since={since}")

    # ------------------------------------------------------------------
    # 广播
    # ------------------------------------------------------------------

    async def broadcast(self, event: WSEvent) -> None:
        """把事件分配 event_id 后广播给该 conversation 的全部客户端，
        并写入事件日志供后续重放。

        - message.complete / run.aborted / replay.missed 等控制事件也走此通道。
        - 若该 conversation 无客户端连接，事件仍写入日志（重连后可重放）。
        - conversation_id 为空（系统事件如 window.show / floating_ball.quit）
          → 广播给全部已连接客户端（不写日志，因为 event_id 维度按 conversation_id）。
        """
        # 系统事件（conversation_id 为空）：广播给全部客户端，不分配 event_id
        if not event.conversation_id:
            payload = event.to_dict()
            with self._lock:
                all_clients = [c for clients in self._clients.values() for c in clients]
            for client in all_clients:
                await self._safe_send(client.ws, payload)
            return

        # 分配 event_id
        with self._lock:
            self._next_event_id[event.conversation_id] += 1
            event.event_id = self._next_event_id[event.conversation_id]
            payload = event.to_dict()
            # 写入日志
            log = self._event_log[event.conversation_id]
            log.append(_LoggedEvent(
                event_id=event.event_id,
                payload=payload,
                timestamp=event.timestamp,
            ))
            self._trim_log_locked(event.conversation_id, log)
            clients = list(self._clients.get(event.conversation_id, []))

        # 广播（连接级发送，单连接失败不影响其他）
        for client in clients:
            await self._safe_send(client.ws, payload)

    def _trim_log_locked(self, conversation_id: str, log: deque[_LoggedEvent]) -> None:
        """按 TTL 与上限裁剪事件日志（调用方持有锁）。"""
        now = time.time()
        # 1. 数量上限
        while len(log) > _EVENT_LOG_MAX_PER_CONV:
            log.popleft()
        # 2. TTL
        while log and now - log[0].timestamp > _EVENT_LOG_TTL_S:
            log.popleft()

    async def _safe_send(self, ws: WebSocket, payload: dict[str, Any]) -> None:
        """单连接发送，异常吞掉并记录（连接可能已半关闭）。"""
        try:
            await ws.send_json(payload)
        except Exception as e:  # WebSocketDisconnect / RuntimeError 等
            self._log("warning", f"WS 发送失败: {type(e).__name__}: {e}")

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------

    def client_count(self, conversation_id: str) -> int:
        with self._lock:
            return len(self._clients.get(conversation_id, []))

    def total_clients(self) -> int:
        with self._lock:
            return sum(len(v) for v in self._clients.values())

    def latest_event_id(self, conversation_id: str) -> int:
        """返回该 conversation 当前最大 event_id（无事件返回 0）。"""
        with self._lock:
            return self._next_event_id.get(conversation_id, 0)


# 模块级单例（由 deps 持有引用，此处保留以便测试直接 import）
ws_manager = WSManager()
