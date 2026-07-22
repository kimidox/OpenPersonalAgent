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


def ensure_image_storage_dir() -> Path:
    """
    确保图片存储目录存在，不存在时自动创建。

    使用 config.IMAGE_STORAGE_DIR 作为存储路径。

    返回：
        图片存储目录的 Path 对象
    """
    from config import IMAGE_STORAGE_DIR
    from logger import get_module_logger

    logger = get_module_logger("file_storage")

    image_dir = Path(IMAGE_STORAGE_DIR)

    if not image_dir.exists():
        try:
            image_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"创建图片存储目录: {image_dir}")
        except Exception as e:
            logger.error(f"创建图片存储目录失败: {e}")
            raise

    return image_dir


def save_image_from_base64(data_url: str, original_name: str = None) -> dict:
    """
    将 base64 编码的图片数据 URL 保存为文件。

    接受 data:image/png;base64,... 格式的数据 URL，
    提取 MIME 类型和 base64 数据，解码并保存为文件。

    参数：
        data_url: 数据 URL，格式为 data:image/png;base64,... 或 data:image/jpeg;base64,...
        original_name: 原始文件名（可选），用于提取文件扩展名

    返回：
        字典包含：
        - file_path: 文件的绝对路径（str）
        - file_name: 生成的唯一文件名（str）
        - mime_type: 图片的 MIME 类型（str）

    异常：
        ValueError: 数据 URL 格式无效
        RuntimeError: 保存文件失败
    """
    import base64
    import re
    from logger import get_module_logger

    logger = get_module_logger("file_storage")

    # 验证数据 URL 格式
    if not data_url or not data_url.startswith("data:"):
        raise ValueError("无效的数据 URL 格式，必须以 'data:' 开头")

    # 解析数据 URL
    # 格式: data:image/png;base64,iVBORw0KGgo...
    pattern = r"^data:([^;]+);base64,(.+)$"
    match = re.match(pattern, data_url)

    if not match:
        raise ValueError("无法解析数据 URL，期望格式: data:image/png;base64,...")

    mime_type = match.group(1)
    base64_data = match.group(2)

    # 验证 MIME 类型是否为图片
    if not mime_type.startswith("image/"):
        raise ValueError(f"不支持的 MIME 类型: {mime_type}，期望图片类型")

    # 提取图片格式扩展名
    image_format = mime_type.split("/")[-1]  # 如 png, jpeg, gif 等

    # 扩展名映射（处理特殊格式）
    format_to_ext = {
        "png": ".png",
        "jpeg": ".jpg",
        "jpg": ".jpg",
        "gif": ".gif",
        "webp": ".webp",
        "bmp": ".bmp",
    }
    ext = format_to_ext.get(image_format, f".{image_format}")

    # 如果提供了原始文件名，尝试使用原始扩展名
    if original_name:
        original_ext = Path(original_name).suffix.lower()
        if original_ext in [".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"]:
            ext = original_ext

    # 生成唯一文件名（使用 UUID）
    unique_id = uuid.uuid4().hex
    file_name = f"{unique_id}{ext}"

    # 确保存储目录存在
    image_dir = ensure_image_storage_dir()
    file_path = image_dir / file_name

    try:
        # 解码 base64 数据
        image_data = base64.b64decode(base64_data)

        # 保存文件
        with open(file_path, "wb") as f:
            f.write(image_data)

        logger.info(f"图片已保存: {file_name} (MIME: {mime_type}, 大小: {len(image_data)} 字节)")

        return {
            "file_path": str(file_path),
            "file_name": file_name,
            "mime_type": mime_type,
        }

    except Exception as e:
        logger.error(f"保存图片文件失败: {e}")
        raise RuntimeError(f"保存图片文件失败: {e}")


def load_image_as_base64(file_path: str) -> str:
    """
    读取图片文件并编码为 base64 数据 URL。

    参数：
        file_path: 图片文件的路径（绝对路径或相对路径）

    返回：
        data:image/png;base64,... 格式的数据 URL

    异常：
        FileNotFoundError: 文件不存在
        RuntimeError: 读取文件失败
    """
    import base64
    from logger import get_module_logger

    logger = get_module_logger("file_storage")

    # 转换为 Path 对象
    path = Path(file_path)

    # 检查文件是否存在
    if not path.exists():
        raise FileNotFoundError(f"图片文件不存在: {file_path}")

    try:
        # 读取文件内容
        with open(path, "rb") as f:
            image_data = f.read()

        # 编码为 base64
        base64_data = base64.b64encode(image_data).decode("utf-8")

        # 根据 MIME 类型映射
        ext_to_mime = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
        }

        # 获取 MIME 类型
        ext = path.suffix.lower()
        mime_type = ext_to_mime.get(ext, "application/octet-stream")

        # 构建数据 URL
        data_url = f"data:{mime_type};base64,{base64_data}"

        logger.debug(f"图片已编码: {path.name} -> {mime_type} ({len(image_data)} 字节)")

        return data_url

    except Exception as e:
        logger.error(f"读取图片文件失败: {file_path}, 错误: {e}")
        raise RuntimeError(f"读取图片文件失败: {e}")


def cleanup_old_images(days: int = None) -> dict:
    """
    清理过期的图片文件。

    扫描图片存储目录，删除超过指定天数的图片文件。
    使用 config.IMAGE_CLEANUP_DAYS 作为默认清理周期。

    参数：
        days: 文件保留天数，默认使用 config.IMAGE_CLEANUP_DAYS

    返回：
        字典包含：
        - deleted_count: 删除的文件数量（int）
        - total_size: 删除的文件总大小（字节）（int）
    """
    import os
    from datetime import datetime, timedelta
    from logger import get_module_logger

    logger = get_module_logger("file_storage")

    # 使用默认清理周期
    if days is None:
        from config import IMAGE_CLEANUP_DAYS
        days = IMAGE_CLEANUP_DAYS

    # 确保图片存储目录存在
    image_dir = ensure_image_storage_dir()

    # 计算截止时间
    cutoff_time = datetime.now() - timedelta(days=days)

    deleted_count = 0
    total_size = 0

    try:
        # 扫描目录中的所有文件
        for file_path in image_dir.iterdir():
            # 跳过子目录
            if not file_path.is_file():
                continue

            # 检查文件修改时间
            file_mtime = datetime.fromtimestamp(file_path.stat().st_mtime)

            # 如果文件超过指定天数，删除它
            if file_mtime < cutoff_time:
                try:
                    file_size = file_path.stat().st_size
                    file_path.unlink()
                    deleted_count += 1
                    total_size += file_size
                    logger.debug(f"删除过期图片: {file_path.name} (大小: {file_size} 字节)")
                except Exception as e:
                    logger.warning(f"删除文件失败: {file_path}, 错误: {e}")

        logger.info(
            f"图片清理完成: 删除 {deleted_count} 个文件，释放 {total_size} 字节 (保留周期: {days} 天)"
        )

        return {
            "deleted_count": deleted_count,
            "total_size": total_size,
        }

    except Exception as e:
        logger.error(f"清理图片文件时发生错误: {e}")
        return {
            "deleted_count": deleted_count,
            "total_size": total_size,
        }