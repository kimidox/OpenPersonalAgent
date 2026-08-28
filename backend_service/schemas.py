"""Pydantic 请求/响应模型（阶段 1 仅覆盖消息/会话/健康检查所需）。"""
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


# =====================================================================
# 会话
# =====================================================================

class ConversationSummary(BaseModel):
    """会话列表项。"""
    conversation_id: str
    title: str | None = None
    type: str = "agent_conversation"
    active_skill_ids: list[str] = Field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None


class ConversationDetail(ConversationSummary):
    """会话详情（含消息记录）。"""
    messages: list[dict[str, Any]] = Field(default_factory=list)


class CreateConversationRequest(BaseModel):
    conversation_type: str = "agent_conversation"
    default_skills: list[dict[str, Any]] | None = None


class CreateConversationResponse(BaseModel):
    conversation_id: str
    title: str


class UpdateConversationTitleRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)


# =====================================================================
# 消息发送
# =====================================================================

class SendMessageRequest(BaseModel):
    """POST /api/conversations/{id}/messages 请求体。

    `queued_ok` 默认 True（主窗口路径）。
    悬浮球路径应传 False（避免静默堆积）。
    """
    query: str = Field(..., min_length=1)
    enable_thinking: bool = False
    # deprecated: 文件内容改由 query 中 <File:fid/> 占位符 + 后端持久层注入，
    # 此字段仅为旧客户端兼容保留，收到时仍走 _consume_uploaded_files_content
    uploaded_files_content: str | dict | None = None
    queued_ok: bool = True
    source: Literal["main", "floating_ball", "scheduler"] = "main"


class SendMessageStartedResponse(BaseModel):
    status: Literal["started"]
    run_id: str


class SendMessageQueuedResponse(BaseModel):
    status: Literal["queued"]
    run_id: str
    position: int


class StopRunResponse(BaseModel):
    stopped: bool
    run_id: str | None = None


# =====================================================================
# Agent 状态
# =====================================================================

class AgentStatus(BaseModel):
    is_running: bool
    active_run_id: str | None = None
    active_conversation_id: str | None = None
    queue_size: int = 0


# =====================================================================
# 健康检查
# =====================================================================

class HealthResponse(BaseModel):
    status: Literal["ok"]
    uptime_s: float
    skill_agent_ready: bool
    scheduler_running: bool
    active_runs: int
    queue_size: int
    ws_clients: int
    # 悬浮球请求退出应用（quit_application）后置 True，
    # Tauri 健康巡检读到后停止 sidecar 并退出（WS 断线时的兜底通道）
    quit_requested: bool = False


class ReadyResponse(BaseModel):
    ready: bool
