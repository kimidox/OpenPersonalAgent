"""
文件上传管理模块

定义上传文件数据模型和支持的文件扩展名。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar, Optional


# 文档文件扩展名
DOCUMENT_EXTENSIONS = ["docx", "pdf", "md", "txt", "json", "xlsx", "xls"]

# 图片文件扩展名（用于视觉能力控制）
IMAGE_EXTENSIONS = ["png", "jpg", "jpeg", "gif", "webp", "bmp"]

# 所有支持的文件扩展名
SUPPORTED_EXTENSIONS = DOCUMENT_EXTENSIONS + IMAGE_EXTENSIONS


@dataclass
class UploadedFileInfo:
    """已上传文件信息"""

    file_id: str
    original_name: str
    file_path: Path
    file_size: int
    extension: str
    mime_type: Optional[str] = None
    upload_time: datetime = field(default_factory=datetime.now)
    parse_result: Optional[Any] = None
    parse_error: Optional[str] = None
    is_parsed: bool = False
    is_parsing: bool = False
    parse_progress: int = 0
    parse_status: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    mime_map: ClassVar[dict[str, str]] = {
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "pdf": "application/pdf",
        "md": "text/markdown",
        "txt": "text/plain",
        "json": "application/json",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xls": "application/vnd.ms-excel",
        # 图片 MIME 类型
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "webp": "image/webp",
        "bmp": "image/bmp",
    }

    @property
    def is_success(self) -> bool:
        """判断文件是否解析成功

        Returns:
            bool: 当文件已解析完成且无错误时返回 True，否则返回 False
        """
        return self.is_parsed and self.parse_error is None

    @property
    def content_preview(self) -> str:
        """获取解析内容的预览文本

        截取解析结果内容的前 200 个字符作为预览，超出部分用省略号表示。

        Returns:
            str: 内容预览文本；若无可预览内容则返回空字符串
        """
        if self.parse_result and hasattr(self.parse_result, "content"):
            content = self.parse_result.content
            if content:
                preview_len = 200
                return content[:preview_len] + "..." if len(content) > preview_len else content
        return ""

    @property
    def summary(self) -> str:
        """获取解析结果的摘要信息

        Returns:
            str: 文件摘要文本；若解析结果中无摘要则返回空字符串
        """
        if self.parse_result and hasattr(self.parse_result, "summary") and self.parse_result.summary:
            return self.parse_result.summary
        return ""

    def get_file_size_display(self) -> str:
        """获取文件大小的可读显示字符串

        根据文件大小自动选择合适的单位（B / KB / MB）进行显示。

        Returns:
            str: 格式化后的文件大小字符串，如 "1.5 KB"、"3.2 MB"
        """
        size = self.file_size
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        else:
            return f"{size / (1024 * 1024):.1f} MB"

    def to_dict(self) -> dict[str, Any]:
        """将文件信息转换为字典格式

        用于序列化和数据传输，将文件信息对象中的关键字段转换为可 JSON 化的字典。

        Returns:
            dict[str, Any]: 包含文件 ID、原始名称、路径、大小、扩展名、
                MIME 类型、上传时间、解析状态、错误信息和元数据的字典
        """
        return {
            "file_id": self.file_id,
            "original_name": self.original_name,
            "file_path": str(self.file_path),
            "file_size": self.file_size,
            "extension": self.extension,
            "mime_type": self.mime_type,
            "upload_time": self.upload_time.isoformat(),
            "is_parsed": self.is_parsed,
            "parse_error": self.parse_error,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UploadedFileInfo":
        """从字典创建 UploadedFileInfo 实例

        与 to_dict 方法互为逆操作，用于反序列化恢复文件信息对象。

        Args:
            data: 包含文件信息的字典，需包含 file_id、original_name、
                file_path、file_size、extension 等键

        Returns:
            UploadedFileInfo: 从字典数据重建的文件信息实例
        """
        file_path = Path(data.get("file_path")) if data.get("file_path") else None
        upload_time = datetime.fromisoformat(data["upload_time"]) if data.get("upload_time") else datetime.now()
        return cls(
            file_id=data["file_id"],
            original_name=data["original_name"],
            file_path=file_path,
            file_size=data["file_size"],
            extension=data["extension"],
            mime_type=data.get("mime_type"),
            upload_time=upload_time,
            is_parsed=data.get("is_parsed", False),
            parse_error=data.get("parse_error"),
            metadata=data.get("metadata", {}),
        )
