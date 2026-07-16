from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from executor import Executor
    from memory.memory import Memory
    # PySide6 UI 已迁移到备份目录，保留类型提示
    from ui_pyside6_backup.utils.file_upload_controller import FileUploadController


@dataclass
class ToolContext:
    """原子工具执行上下文：工作目录与可选的桌面自动化执行器。"""

    work_dir: str
    executor: "Executor | None" = None
    memory: "Memory | None" = None
    user_id: str = "default"
    conversation_id: str | None = None
    file_upload_controller: "FileUploadController | None" = None
