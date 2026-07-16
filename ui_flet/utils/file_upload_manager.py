"""
文件上传管理模块

定义上传文件数据模型和支持的文件扩展名。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


SUPPORTED_EXTENSIONS = ["docx", "pdf", "md", "txt", "json", "xlsx", "xls"]


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

    mime_map: dict[str, str] = field(
        default_factory=lambda: {
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "pdf": "application/pdf",
            "md": "text/markdown",
            "txt": "text/plain",
            "json": "application/json",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "xls": "application/vnd.ms-excel",
        },
        repr=False,
    )

    @property
    def is_success(self) -> bool:
        return self.is_parsed and self.parse_error is None

    @property
    def content_preview(self) -> str:
        if self.parse_result and hasattr(self.parse_result, "content"):
            content = self.parse_result.content
            if content:
                preview_len = 200
                return content[:preview_len] + "..." if len(content) > preview_len else content
        return ""

    @property
    def summary(self) -> str:
        if self.parse_result and hasattr(self.parse_result, "summary") and self.parse_result.summary:
            return self.parse_result.summary
        return ""

    def get_file_size_display(self) -> str:
        size = self.file_size
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        else:
            return f"{size / (1024 * 1024):.1f} MB"

    def to_dict(self) -> dict[str, Any]:
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
