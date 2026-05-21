from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .searcher import MemorySearcher, MemorySegmentData


class LongTermMemory:
    """长期记忆管理类，基于 SQLite + FTS5 实现语义检索。"""

    def __init__(
        self,
        memory_file_path: str | None = None,
        user_id: str | None = None,
        searcher: MemorySearcher | None = None,
    ) -> None:
        self._file_path = Path(memory_file_path) if memory_file_path else None
        self._user_id = user_id or "default"
        self._searcher = searcher or MemorySearcher()

    def read(self) -> str:
        """读取所有长期记忆内容（向后兼容）。"""
        segments = self._searcher.get_all(
            memory_type=MemorySearcher.LONG_TERM,
            related_id=self._user_id,
        )
        if not segments:
            return ""
        parts = []
        for seg in segments:
            timestamp = seg.created_at.strftime("%Y-%m-%d %H:%M:%S") if seg.created_at else ""
            parts.append(f"## [{timestamp}]\n{seg.content}")
        return "\n".join(parts)

    def search(self, query: str, limit: int = 5) -> list[MemorySegmentData]:
        """检索与查询相关的长期记忆片段。"""
        return self._searcher.search(
            query=query,
            memory_type=MemorySearcher.LONG_TERM,
            related_id=self._user_id,
            limit=limit,
        )

    def append(self, content: str, metadata: dict[str, Any] | None = None) -> None:
        """追加内容到长期记忆。"""
        self._searcher.add_segment(
            memory_type=MemorySearcher.LONG_TERM,
            content=content,
            related_id=self._user_id,
            metadata=metadata,
        )

    def update(self, content: str) -> None:
        """更新（覆盖）长期记忆内容。"""
        self._searcher.delete_by_related_id(
            memory_type=MemorySearcher.LONG_TERM,
            related_id=self._user_id,
        )
        self.append(content)

    def _ensure_file_exists(self) -> None:
        """确保文件存在（仅用于向后兼容的文件迁移）。"""
        if self._file_path and not self._file_path.exists():
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            self._file_path.touch()

    def migrate_from_file(self) -> int:
        """从旧文件迁移记忆到数据库。"""
        if not self._file_path or not self._file_path.exists():
            return 0

        content = self._file_path.read_text(encoding="utf-8")
        if not content.strip():
            return 0

        segments = self._parse_memory_file(content)
        migrated = 0
        for seg_content, timestamp in segments:
            self.append(seg_content, metadata={"migrated_from": str(self._file_path), "original_timestamp": timestamp})
            migrated += 1

        backup_path = self._file_path.with_suffix(".md.bak")
        self._file_path.rename(backup_path)

        return migrated

    def _parse_memory_file(self, content: str) -> list[tuple[str, str]]:
        """解析 MEMORY.md 文件格式，返回 (内容, 时间戳) 列表。"""
        import re

        segments = []
        pattern = r"##\s*\[([^\]]+)\]\s*\n(.*?)(?=##\s*\[|$)"
        matches = re.findall(pattern, content, re.DOTALL)

        for timestamp, seg_content in matches:
            seg_content = seg_content.strip()
            if seg_content:
                segments.append((seg_content, timestamp.strip()))

        if not matches and content.strip():
            segments.append((content.strip(), ""))

        return segments
