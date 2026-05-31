from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ParseResult:
    """解析结果数据类。"""

    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    summary: str | None = None
    error: str | None = None
    file_path: Path | None = None

    @classmethod
    def from_error(
        cls, error_message: str, file_path: Path | None = None
    ) -> "ParseResult":
        """从错误信息创建 ParseResult 实例。

        Args:
            error_message: 错误信息
            file_path: 文件路径

        Returns:
            ParseResult: 包含错误信息的解析结果
        """
        return cls(
            content="",
            metadata={},
            summary=None,
            error=error_message,
            file_path=file_path,
        )

    @property
    def is_success(self) -> bool:
        """检查解析是否成功。

        Returns:
            bool: 是否成功
        """
        return self.error is None