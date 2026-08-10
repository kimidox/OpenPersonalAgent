"""会话路由：list / get / create / delete / patch title（最小集）。

调用 SkillAgent / memory 的同步方法，路由用 `def`（threadpool，3.9 节）。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from backend_service.deps import get_memory, require_skill_agent
from backend_service.schemas import (
    ConversationDetail,
    ConversationSummary,
    CreateConversationRequest,
    CreateConversationResponse,
    UpdateConversationTitleRequest,
)

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


def _conv_to_summary(conv: Any) -> ConversationSummary:
    """Conversation 领域对象 → ConversationSummary。"""
    return ConversationSummary(
        conversation_id=conv.conversation_id,
        title=conv.title,
        type=getattr(conv, "type", "agent_conversation"),
        active_skill_ids=list(getattr(conv, "active_skill_ids", []) or []),
        created_at=str(conv.created_at) if conv.created_at else None,
        updated_at=str(conv.updated_at) if conv.updated_at else None,
    )


@router.get("", response_model=list[ConversationSummary])
def list_conversations(
    agent=Depends(require_skill_agent),
) -> list[ConversationSummary]:
    """列出所有已保存会话。"""
    conversations = agent.list_saved_conversations()
    return [_conv_to_summary(c) for c in conversations]


@router.post("", response_model=CreateConversationResponse, status_code=status.HTTP_201_CREATED)
def create_conversation(
    body: CreateConversationRequest,
    agent=Depends(require_skill_agent),
) -> CreateConversationResponse:
    """创建新会话。"""
    conversation_id, title = agent.start_new_conversation(
        conversation_type=body.conversation_type,
        default_skills=body.default_skills,
    )
    if not conversation_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="创建会话失败",
        )
    return CreateConversationResponse(conversation_id=conversation_id, title=title)


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    conversation_id: str,
    agent=Depends(require_skill_agent),
) -> ConversationDetail:
    """获取会话信息 + 消息记录。"""
    conversations = agent.list_saved_conversations()
    target = next(
        (c for c in conversations if c.conversation_id == conversation_id),
        None,
    )
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"会话不存在: {conversation_id}",
        )
    messages = agent.message_records_for_conversation(conversation_id)
    summary = _conv_to_summary(target)
    return ConversationDetail(**summary.model_dump(), messages=messages)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(
    conversation_id: str,
    memory=Depends(get_memory),
) -> None:
    """删除会话（仅 memory 层；阶段 2 补 SkillAgent 侧清理）。"""
    if memory is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Memory 未就绪",
        )
    try:
        # Memory 抽象基类已定义 clear_conversation（@abstractmethod）：删除会话行 + 全部消息
        memory.clear_conversation(conversation_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"删除会话失败: {e}",
        )


@router.patch("/{conversation_id}", response_model=ConversationSummary)
def update_conversation_title(
    conversation_id: str,
    body: UpdateConversationTitleRequest,
    agent=Depends(require_skill_agent),
    memory=Depends(get_memory),
) -> ConversationSummary:
    """修改会话标题。"""
    if memory is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Memory 未就绪",
        )
    try:
        # 先检查会话是否存在
        conversations = agent.list_saved_conversations()
        target = next(
            (c for c in conversations if c.conversation_id == conversation_id),
            None,
        )
        if target is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"会话不存在: {conversation_id}",
            )

        # 调用 memory 更新标题
        update_fn = getattr(memory, "update_conversation_title", None)
        if callable(update_fn):
            update_fn(conversation_id, body.title)
        else:
            # 回退：直接在领域对象上更新
            setattr(target, "title", body.title)

        # 返回更新后的摘要
        updated = _conv_to_summary(target)
        updated.title = body.title
        return updated
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"修改会话标题失败: {e}",
        )
