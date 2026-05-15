from __future__ import annotations

from datetime import datetime
from pathlib import Path


class LongTermMemory:
    """长期记忆管理类，负责 MEMORY.md 文件的读写操作。"""

    def __init__(self, memory_file_path: str) -> None:
        self._file_path = Path(memory_file_path)

    def read(self) -> str:
        """读取长期记忆内容，如果文件不存在返回空字符串。"""
        if not self._file_path.exists():
            return ""
        return self._file_path.read_text(encoding="utf-8")

    def append(self, content: str) -> None:
        """追加内容到长期记忆，在内容前添加时间戳标记。"""
        self._ensure_file_exists()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        timestamped_content = f"\n## [{timestamp}]\n{content}"
        with self._file_path.open("a", encoding="utf-8") as f:
            f.write(timestamped_content)

    def update(self, content: str) -> None:
        """更新（覆盖）长期记忆内容。"""
        self._ensure_file_exists()
        self._file_path.write_text(content, encoding="utf-8")

    def _ensure_file_exists(self) -> None:
        """确保文件存在，不存在则创建。"""
        if not self._file_path.exists():
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            self._file_path.touch()
