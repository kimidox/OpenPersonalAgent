from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


@dataclass
class FileInfo:
    """文件信息数据类。"""

    file_id: str
    original_name: str
    stored_path: Path
    file_size: int
    mime_type: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式。"""
        return {
            "file_id": self.file_id,
            "original_name": self.original_name,
            "stored_path": str(self.stored_path),
            "file_size": self.file_size,
            "mime_type": self.mime_type,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
        }


class FileStorage:
    """
    文件存储服务。

    管理上传文件的存储和生命周期，使用临时目录存储文件。
    支持文件保存、获取、删除、清理等操作。
    """

    def __init__(
        self,
        storage_dir: Optional[Path | str] = None,
        prefix: str = "doc_parser_",
    ):
        """
        初始化文件存储服务。

        参数：
            storage_dir: 存储目录路径，如果为 None 则使用系统临时目录
            prefix: 存储目录名称前缀
        """
        if storage_dir is None:
            self._storage_dir = Path(tempfile.gettempdir()) / f"{prefix}{uuid.uuid4().hex[:8]}"
        else:
            self._storage_dir = Path(storage_dir)

        self._files: dict[str, FileInfo] = {}
        self._ensure_storage_dir()

    def _ensure_storage_dir(self) -> None:
        """确保存储目录存在。"""
        self._storage_dir.mkdir(parents=True, exist_ok=True)

    @property
    def storage_dir(self) -> Path:
        """获取存储目录路径。"""
        return self._storage_dir

    def _generate_file_id(self) -> str:
        """生成唯一的文件 ID。"""
        return uuid.uuid4().hex

    def _get_mime_type(self, file_path: Path) -> Optional[str]:
        """根据文件扩展名获取 MIME 类型。"""
        mime_map: dict[str, str] = {
            ".txt": "text/plain",
            ".pdf": "application/pdf",
            ".doc": "application/msword",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".xls": "application/vnd.ms-excel",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".ppt": "application/vnd.ms-powerpoint",
            ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            ".md": "text/markdown",
            ".json": "application/json",
            ".csv": "text/csv",
            ".html": "text/html",
            ".xml": "application/xml",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
        }
        return mime_map.get(file_path.suffix.lower())

    def save(
        self,
        source_path: Path | str,
        original_name: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> FileInfo:
        """
        保存文件到存储目录。

        参数：
            source_path: 源文件路径
            original_name: 原始文件名，如果为 None 则使用源文件名
            metadata: 额外的元数据

        返回：
            FileInfo 对象
        """
        source = Path(source_path)
        if not source.exists():
            raise FileNotFoundError(f"源文件不存在: {source_path}")

        file_id = self._generate_file_id()
        original_name = original_name or source.name

        stored_name = f"{file_id}_{original_name}"
        stored_path = self._storage_dir / stored_name

        shutil.copy2(source, stored_path)

        file_info = FileInfo(
            file_id=file_id,
            original_name=original_name,
            stored_path=stored_path,
            file_size=stored_path.stat().st_size,
            mime_type=self._get_mime_type(source),
            metadata=metadata or {},
        )

        self._files[file_id] = file_info
        return file_info

    def save_bytes(
        self,
        data: bytes,
        original_name: str,
        mime_type: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> FileInfo:
        """
        保存字节数据到存储目录。

        参数：
            data: 文件字节数据
            original_name: 原始文件名
            mime_type: MIME 类型
            metadata: 额外的元数据

        返回：
            FileInfo 对象
        """
        file_id = self._generate_file_id()
        stored_name = f"{file_id}_{original_name}"
        stored_path = self._storage_dir / stored_name

        with open(stored_path, "wb") as f:
            f.write(data)

        file_info = FileInfo(
            file_id=file_id,
            original_name=original_name,
            stored_path=stored_path,
            file_size=len(data),
            mime_type=mime_type,
            metadata=metadata or {},
        )

        self._files[file_id] = file_info
        return file_info

    def get(self, file_id: str) -> Optional[FileInfo]:
        """
        获取文件信息。

        参数：
            file_id: 文件 ID

        返回：
            FileInfo 对象，如果不存在则返回 None
        """
        return self._files.get(file_id)

    def get_path(self, file_id: str) -> Optional[Path]:
        """
        获取文件存储路径。

        参数：
            file_id: 文件 ID

        返回：
            文件路径，如果不存在则返回 None
        """
        file_info = self._files.get(file_id)
        if file_info is None:
            return None
        if not file_info.stored_path.exists():
            return None
        return file_info.stored_path

    def read(self, file_id: str) -> Optional[bytes]:
        """
        读取文件内容。

        参数：
            file_id: 文件 ID

        返回：
            文件字节数据，如果不存在则返回 None
        """
        file_path = self.get_path(file_id)
        if file_path is None:
            return None
        with open(file_path, "rb") as f:
            return f.read()

    def delete(self, file_id: str) -> bool:
        """
        删除文件。

        参数：
            file_id: 文件 ID

        返回：
            是否删除成功
        """
        file_info = self._files.get(file_id)
        if file_info is None:
            return False

        try:
            if file_info.stored_path.exists():
                file_info.stored_path.unlink()
            del self._files[file_id]
            return True
        except Exception:
            return False

    def list_files(self) -> list[FileInfo]:
        """
        列出所有已存储的文件。

        返回：
            FileInfo 列表
        """
        return list(self._files.values())

    def clear(self) -> int:
        """
        清理所有存储的文件。

        返回：
            删除的文件数量
        """
        count = 0
        for file_info in list(self._files.values()):
            try:
                if file_info.stored_path.exists():
                    file_info.stored_path.unlink()
                count += 1
            except Exception:
                pass
        self._files.clear()
        return count

    def cleanup_old_files(self, max_age_hours: int = 24) -> int:
        """
        清理过期的文件。

        参数：
            max_age_hours: 最大保留时间（小时）

        返回：
            删除的文件数量
        """
        now = datetime.now()
        count = 0

        for file_id, file_info in list(self._files.items()):
            age = (now - file_info.created_at).total_seconds() / 3600
            if age > max_age_hours:
                try:
                    if file_info.stored_path.exists():
                        file_info.stored_path.unlink()
                    del self._files[file_id]
                    count += 1
                except Exception:
                    pass

        return count

    def get_storage_size(self) -> int:
        """
        获取存储目录的总大小（字节）。

        返回：
            总字节数
        """
        total = 0
        for file_info in self._files.values():
            if file_info.stored_path.exists():
                total += file_info.stored_path.stat().st_size
        return total

    def __len__(self) -> int:
        """返回存储的文件数量。"""
        return len(self._files)

    def __contains__(self, file_id: str) -> bool:
        """检查文件是否存在。"""
        return file_id in self._files

    def __enter__(self) -> FileStorage:
        """上下文管理器入口。"""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """上下文管理器退出，自动清理文件。"""
        self.clear()
        if self._storage_dir.exists():
            try:
                self._storage_dir.rmdir()
            except Exception:
                pass