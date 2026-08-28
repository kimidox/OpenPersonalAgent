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
            "deleted_count": 0,
            "total_size": 0,
        }


# =====================================================================
# 持久化上传文件存储（会话引用的权威文件层）
# =====================================================================
# 与临时 FileStorage 的区别：
# - 固定目录（PersonalData/uploads），跨进程重启可用
# - manifest.json 磁盘索引：file_id -> 元数据
# - 解析文本 sidecar（<file_id>.txt），供 read_uploaded_file 工具与
#   占位符注入懒加载，避免每轮重复解析
# 仅使用标准库 + document_parser.parser_factory（懒导入）。

_UPLOADS_MANIFEST = "manifest.json"


def _get_uploads_storage() -> Path:
    """返回持久化上传目录（PersonalData/uploads），不存在时创建。"""
    from logger import get_module_logger

    logger = get_module_logger("file_storage")
    from config import WORKER_DIR

    uploads_dir = Path(WORKER_DIR) / "uploads"
    if not uploads_dir.exists():
        uploads_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"创建上传文件存储目录: {uploads_dir}")
    return uploads_dir


def _load_uploads_manifest() -> dict[str, Any]:
    """读取 manifest；损坏时返回空 dict（自愈为空索引）。"""
    manifest_path = _get_uploads_storage() / _UPLOADS_MANIFEST
    if not manifest_path.exists():
        return {}
    import json

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_uploads_manifest(manifest: dict[str, Any]) -> None:
    """原子写入 manifest（先写 .tmp 再 os.replace）。"""
    import json

    manifest_path = _get_uploads_storage() / _UPLOADS_MANIFEST
    tmp_path = manifest_path.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, manifest_path)


def save_upload(
    data: bytes,
    original_name: str,
    mime_type: Optional[str] = None,
    parsed_text: Optional[str] = None,
) -> dict[str, Any]:
    """持久化保存上传文件，返回含 file_id 的元数据字典。

    Args:
        data: 文件字节数据
        original_name: 原始文件名
        mime_type: MIME 类型（可选）
        parsed_text: 解析文本（可选，持久化为 sidecar 供懒加载）

    Returns:
        {"file_id", "file_name"(原始名), "file_path", "file_size", "mime_type"}
    """
    from logger import get_module_logger

    logger = get_module_logger("file_storage")

    uploads_dir = _get_uploads_storage()
    file_id = uuid.uuid4().hex
    stored_name = f"{file_id}_{original_name}"
    file_path = uploads_dir / stored_name

    with open(file_path, "wb") as f:
        f.write(data)

    if parsed_text is not None:
        with open(uploads_dir / f"{file_id}.txt", "w", encoding="utf-8") as f:
            f.write(parsed_text)

    manifest = _load_uploads_manifest()
    manifest[file_id] = {
        "file_id": file_id,
        "file_name": original_name,
        "stored_name": stored_name,
        "file_size": len(data),
        "mime_type": mime_type,
        "created_at": datetime.now().isoformat(),
        "has_parsed_text": parsed_text is not None,
    }
    _save_uploads_manifest(manifest)
    logger.info(
        f"上传文件已持久化: {original_name} (file_id: {file_id}, "
        f"大小: {len(data)} 字节, 含解析文本: {parsed_text is not None})"
    )
    return {
        "file_id": file_id,
        "file_name": original_name,
        "file_path": str(file_path),
        "file_size": len(data),
        "mime_type": mime_type,
    }


def get_upload_info(file_id: str) -> Optional[dict[str, Any]]:
    """查询上传文件元数据；不存在返回 None。"""
    return _load_uploads_manifest().get(file_id)


def persist_parsed_text(file_id: str, parsed_text: str) -> None:
    """把解析文本写入 sidecar 并更新 manifest（静默失败，仅记录日志）。"""
    from logger import get_module_logger

    logger = get_module_logger("file_storage")
    try:
        uploads_dir = _get_uploads_storage()
        with open(uploads_dir / f"{file_id}.txt", "w", encoding="utf-8") as f:
            f.write(parsed_text)
        manifest = _load_uploads_manifest()
        if file_id in manifest:
            manifest[file_id]["has_parsed_text"] = True
            _save_uploads_manifest(manifest)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"持久化解析文本失败: {file_id} - {e}")


def _parse_stored_file(file_path: Path) -> str:
    """用 parser_factory 解析文件并返回文本（失败时返回错误提示文本）。"""
    from logger import get_module_logger

    logger = get_module_logger("file_storage")
    try:
        from document_parser.parser_factory import parse_file

        result = parse_file(file_path)
        return (getattr(result, "content", None) or "").strip()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"解析上传文件失败: {file_path.name} - {e}")
        return f"[解析失败: {e}]"


def get_uploaded_text(file_id: str, *, reparse_if_missing: bool = True) -> Optional[str]:
    """获取上传文件的解析文本（懒加载）。

    优先读 sidecar（<file_id>.txt）；不存在且允许时用 parser_factory
    重新解析并持久化 sidecar。文件不存在返回 None。

    Args:
        file_id: 上传文件 ID
        reparse_if_missing: sidecar 缺失时是否重新解析并写回

    Returns:
        解析文本；文件不存在返回 None
    """
    from logger import get_module_logger

    logger = get_module_logger("file_storage")

    info = get_upload_info(file_id)
    if info is None:
        return None

    uploads_dir = _get_uploads_storage()
    sidecar = uploads_dir / f"{file_id}.txt"
    if sidecar.exists():
        with open(sidecar, "r", encoding="utf-8") as f:
            return f.read()

    file_path = uploads_dir / info.get("stored_name", "")
    if not file_path.exists():
        logger.warning(f"上传文件已丢失: {info.get('file_name')} ({file_id})")
        return None

    if not reparse_if_missing:
        return None

    # 懒解析并写回 sidecar（下次直接命中）
    text = _parse_stored_file(file_path)
    try:
        with open(sidecar, "w", encoding="utf-8") as f:
            f.write(text)
        manifest = _load_uploads_manifest()
        if file_id in manifest:
            manifest[file_id]["has_parsed_text"] = True
            _save_uploads_manifest(manifest)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"写回解析 sidecar 失败: {file_id} - {e}")
    return text


def get_upload_base64_url(file_id: str) -> Optional[str]:
    """读取上传文件的原始字节并编码为 data URL（供多模态消息使用）。

    Args:
        file_id: 上传文件 ID

    Returns:
        data:{mime};base64,... 格式的 URL；文件不存在返回 None
    """
    import base64

    info = get_upload_info(file_id)
    if info is None:
        return None
    file_path = _get_uploads_storage() / info.get("stored_name", "")
    if not file_path.exists():
        return None
    with open(file_path, "rb") as f:
        data = f.read()
    mime = info.get("mime_type") or "application/octet-stream"
    return f"data:{mime};base64,{base64.b64encode(data).decode('utf-8')}"


def delete_upload(file_id: str) -> bool:
    """删除上传文件（原始文件 + sidecar + manifest 条目）。"""
    manifest = _load_uploads_manifest()
    info = manifest.pop(file_id, None)
    if info is None:
        return False
    uploads_dir = _get_uploads_storage()
    for name in (info.get("stored_name", ""), f"{file_id}.txt"):
        p = uploads_dir / name
        if name and p.exists():
            try:
                p.unlink()
            except Exception:
                pass
    _save_uploads_manifest(manifest)
    return True


def list_uploads() -> list[dict[str, Any]]:
    """列出全部持久化上传文件元数据（按创建时间倒序）。"""
    manifest = _load_uploads_manifest()
    items = [v for v in manifest.values() if isinstance(v, dict)]
    items.sort(key=lambda x: str(x.get("created_at", "")), reverse=True)
    return items