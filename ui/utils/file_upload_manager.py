from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


SUPPORTED_EXTENSIONS = ["docx", "pdf", "md", "txt", "json", "xlsx", "xls"]


@dataclass
class UploadedFileInfo:
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
    metadata: dict[str, Any] = field(default_factory=dict)

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