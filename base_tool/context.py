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
    _skip_ask_user_for_run_command: bool = False  # 标志位：跳过 run_command 的二次确认

    def set_skip_ask_user_for_run_command(self, value: bool) -> None:
        """设置是否跳过 run_command 的二次确认标志。"""
        self._skip_ask_user_for_run_command = value

    def should_skip_ask_user_for_run_command(self) -> bool:
        """查询是否应跳过 run_command 的二次确认。"""
        return self._skip_ask_user_for_run_command
