from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from executor import Executor
    from memory.memory import Memory


@dataclass
class ToolContext:
    """原子工具执行上下文：工作目录与可选的桌面自动化执行器。"""

    work_dir: str
    executor: "Executor | None" = None
    memory: "Memory | None" = None
    user_id: str = "default"
