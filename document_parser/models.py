from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ParseResult:
    """解析结果数据类。

    Attributes:
        content: 解析后的内容。对于文本文件，存储文本内容；对于图片文件，存储 base64 编码的图片数据。
        metadata: 元信息字典。可包含以下标准字段：
            - content_type: 内容类型标识，如 "text" 或 "base64_image"
            - file_name: 文件名
            - file_size: 文件大小（字节）
            - mime_type: MIME 类型（如 "image/png"）
            - extension: 文件扩展名
            - created_time: 创建时间戳
            - modified_time: 修改时间戳
        summary: 内容摘要
        error: 错误信息，如果解析失败
        file_path: 文件路径
    """

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