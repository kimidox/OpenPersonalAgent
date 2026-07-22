from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any

from ..base_parser import BaseParser
from ..models import ParseResult

# 配置日志
logger = logging.getLogger(__name__)


class ImageParser(BaseParser):
    """图片文件解析器。

    支持读取常见图片格式并进行 base64 编码，
    提取图片元信息并生成摘要。
    """

    SUPPORTED_EXTENSIONS = [".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"]

    # MIME 类型映射
    MIME_MAP: dict[str, str] = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }

    def parse(self, file_path: Path) -> ParseResult:
        """解析图片文件。

        读取图片文件内容并进行 base64 编码，
        提取元信息并生成摘要。

        Args:
            file_path: 要解析的图片文件路径

        Returns:
            ParseResult: 包含 base64 编码内容、元信息和摘要的解析结果
        """
        logger.info(f"开始解析图片文件: {file_path}")

        # 验证文件
        error = self.validate_file(file_path)
        if error:
            logger.error(f"文件验证失败: {error}")
            return ParseResult.from_error(error, file_path=file_path)

        try:
            # 读取图片文件并进行 base64 编码
            base64_content = self._read_and_encode_image(file_path)

            # 提取元信息
            metadata = self._extract_metadata(file_path)

            # 生成摘要
            summary = self._generate_summary(metadata)

            logger.info(f"图片文件解析成功: {file_path}")

            return ParseResult(
                content=base64_content,
                metadata=metadata,
                summary=summary,
            )

        except FileNotFoundError as e:
            error_msg = f"文件不存在: {file_path}"
            logger.error(error_msg)
            return ParseResult.from_error(error_msg, file_path=file_path)

        except PermissionError as e:
            error_msg = f"无权限读取文件: {file_path}"
            logger.error(error_msg)
            return ParseResult.from_error(error_msg, file_path=file_path)

        except Exception as e:
            error_msg = f"解析图片文件时发生错误: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return ParseResult.from_error(error_msg, file_path=file_path)

    def _read_and_encode_image(self, file_path: Path) -> str:
        """读取图片文件并进行 base64 编码。

        Args:
            file_path: 图片文件路径

        Returns:
            str: base64 编码后的字符串

        Raises:
            FileNotFoundError: 文件不存在
            PermissionError: 无权限读取文件
            IOError: 读取文件失败
        """
        logger.debug(f"读取图片文件: {file_path}")

        with open(file_path, "rb") as f:
            image_data = f.read()

        # 进行 base64 编码
        base64_encoded = base64.b64encode(image_data).decode("utf-8")

        logger.debug(f"图片编码完成，原始大小: {len(image_data)} 字节，编码后长度: {len(base64_encoded)}")

        return base64_encoded

    def _extract_metadata(self, file_path: Path) -> dict[str, Any]:
        """提取图片文件的元信息。

        Args:
            file_path: 图片文件路径

        Returns:
            dict: 包含文件名、大小、扩展名、MIME 类型等信息的字典
        """
        logger.debug(f"提取图片元信息: {file_path}")

        stat = file_path.stat()
        extension = file_path.suffix.lower()

        metadata: dict[str, Any] = {
            "content_type": "base64_image",
            "file_name": file_path.name,
            "file_size": stat.st_size,
            "extension": extension,
            "mime_type": self._get_mime_type(extension),
            "created_time": stat.st_ctime,
            "modified_time": stat.st_mtime,
        }

        logger.debug(f"提取的元信息: {metadata}")

        return metadata

    def _get_mime_type(self, extension: str) -> str:
        """根据文件扩展名获取 MIME 类型。

        Args:
            extension: 文件扩展名（包含点号，如 '.png'）

        Returns:
            str: MIME 类型字符串
        """
        mime_type = self.MIME_MAP.get(extension.lower())

        if mime_type is None:
            logger.warning(f"未知的图片扩展名: {extension}，使用默认 MIME 类型")
            return "application/octet-stream"

        return mime_type

    def _generate_summary(self, metadata: dict[str, Any]) -> str:
        """生成图片文件的简要摘要。

        Args:
            metadata: 图片元信息

        Returns:
            str: 摘要文本
        """
        file_name = metadata.get("file_name", "未知文件")
        file_size = metadata.get("file_size", 0)
        mime_type = metadata.get("mime_type", "未知类型")

        # 格式化文件大小
        size_str = self._format_file_size(file_size)

        # 从 MIME 类型中提取格式描述
        format_desc = mime_type.split("/")[-1].upper()

        summary = f"图片文件: {file_name}，格式: {format_desc}，大小: {size_str}"

        logger.debug(f"生成的摘要: {summary}")

        return summary

    def _format_file_size(self, size_bytes: int) -> str:
        """将文件大小格式化为易读的字符串。

        Args:
            size_bytes: 文件大小（字节）

        Returns:
            str: 格式化后的文件大小字符串
        """
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.2f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.2f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"