from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from database import get_session
from database.models import ScheduledTask as ScheduledTaskModel


RepeatType = Literal["none", "daily", "weekly", "monthly"]
NotificationType = Literal["system", "toast"]
TaskStatus = Literal["pending", "triggered", "cancelled", "deleted"]


@dataclass
class ScheduledTask:
    task_id: str
    user_id: str
    title: str
    content: str
    trigger_time: datetime
    repeat_type: RepeatType
    notification_type: NotificationType
    status: TaskStatus
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_orm(cls, row: ScheduledTaskModel) -> ScheduledTask:
        return cls(
            task_id=str(row.task_id),
            user_id=str(row.user_id),
            title=str(row.title) if row.title else "",
            content=str(row.content) if row.content else "",
            trigger_time=row.trigger_time if row.trigger_time else datetime.now(),
            repeat_type=str(row.repeat_type) if row.repeat_type else "none",
            notification_type=str(row.notification_type) if row.notification_type else "system",
            status=str(row.status) if row.status else "pending",
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "user_id": self.user_id,
            "title": self.title,
            "content": self.content,
            "trigger_time": self.trigger_time.isoformat() if self.trigger_time else None,
            "repeat_type": self.repeat_type,
            "notification_type": self.notification_type,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class TaskNotFoundError(Exception):
    pass


def add_task(
    user_id: str,
    title: str,
    content: str,
    trigger_time: datetime,
    repeat_type: RepeatType = "none",
    notification_type: NotificationType = "system",
) -> ScheduledTask:
    task_id = str(uuid.uuid4())
    with get_session() as db:
        task = ScheduledTaskModel(
            task_id=task_id,
            user_id=user_id,
            title=title,
            content=content,
            trigger_time=trigger_time,
            repeat_type=repeat_type,
            notification_type=notification_type,
            status="pending",
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        return ScheduledTask.from_orm(task)


def update_task(task_id: str, **kwargs) -> ScheduledTask:
    valid_fields = {"title", "content", "trigger_time", "repeat_type", "notification_type", "status"}
    update_fields = {k: v for k, v in kwargs.items() if k in valid_fields and v is not None}

    if not update_fields:
        raise ValueError("No valid fields to update")

    with get_session() as db:
        task = db.query(ScheduledTaskModel).filter(ScheduledTaskModel.task_id == task_id).first()
        if not task:
            raise TaskNotFoundError(f"Task with id {task_id} not found")

        for field, value in update_fields.items():
            setattr(task, field, value)

        task.updated_at = datetime.now()
        db.commit()
        db.refresh(task)
        return ScheduledTask.from_orm(task)


def delete_task(task_id: str) -> bool:
    with get_session() as db:
        task = db.query(ScheduledTaskModel).filter(ScheduledTaskModel.task_id == task_id).first()
        if not task:
            return False

        db.delete(task)
        db.commit()
        return True


def list_tasks(
    user_id: str | None = None,
    status: TaskStatus | None = None,
) -> list[ScheduledTask]:
    with get_session() as db:
        query = db.query(ScheduledTaskModel)

        if user_id:
            query = query.filter(ScheduledTaskModel.user_id == user_id)

        if status:
            query = query.filter(ScheduledTaskModel.status == status)

        query = query.order_by(ScheduledTaskModel.trigger_time.asc())
        rows = query.all()
        return [ScheduledTask.from_orm(row) for row in rows]


def get_pending_tasks() -> list[ScheduledTask]:
    now = datetime.now()
    with get_session() as db:
        rows = (
            db.query(ScheduledTaskModel)
            .filter(ScheduledTaskModel.status == "pending")
            .filter(ScheduledTaskModel.trigger_time <= now)
            .order_by(ScheduledTaskModel.trigger_time.asc())
            .all()
        )
        return [ScheduledTask.from_orm(row) for row in rows]


def get_task(task_id: str) -> ScheduledTask:
    with get_session() as db:
        task = db.query(ScheduledTaskModel).filter(ScheduledTaskModel.task_id == task_id).first()
        if not task:
            raise TaskNotFoundError(f"Task with id {task_id} not found")
        return ScheduledTask.from_orm(task)


def update_task_status(task_id: str, status: TaskStatus) -> ScheduledTask:
    with get_session() as db:
        task = db.query(ScheduledTaskModel).filter(ScheduledTaskModel.task_id == task_id).first()
        if not task:
            raise TaskNotFoundError(f"Task with id {task_id} not found")

        task.status = status
        task.updated_at = datetime.now()
        db.commit()
        db.refresh(task)
        return ScheduledTask.from_orm(task)