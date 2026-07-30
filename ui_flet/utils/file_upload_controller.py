"""
文件上传控制器

提供文件校验、解析调度、状态管理以及给 LLM 的消息注入功能。
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from logger import get_logger
from ui_flet.utils.file_upload_manager import (
    UploadedFileInfo,
    SUPPORTED_EXTENSIONS,
    DOCUMENT_EXTENSIONS,
    IMAGE_EXTENSIONS,
)

logger = get_logger()


class FileUploadController:
    """文件上传控制器"""

    def __init__(self, max_files: int = 5) -> None:
        self._files: dict[str, UploadedFileInfo] = {}
        self._max_files = max_files
        self._vision_enabled: bool = True  # 默认启用视觉能力
        self._callbacks: dict[str, list[Callable[[], None]]] = {
            "file_added": [],
            "file_removed": [],
            "file_parse_started": [],
            "file_parse_finished": [],
            "file_parse_error": [],
            "files_changed": [],
            "upload_error": [],
        }

        try:
            import config
            self._max_file_size: int = getattr(config, "FILE_UPLOAD_MAX_SIZE_MB", 10) * 1024 * 1024
        except Exception:
            self._max_file_size = 10 * 1024 * 1024

    def register_callback(self, event: str, callback: Callable[[], None]) -> None:
        """注册状态变化回调"""
        if event in self._callbacks:
            self._callbacks[event].append(callback)

    def unregister_callback(self, event: str, callback: Callable[[], None]) -> None:
        """注销状态变化回调"""
        if event in self._callbacks and callback in self._callbacks[event]:
            self._callbacks[event].remove(callback)

    def _emit(self, event: str, file_info: Optional[UploadedFileInfo] = None) -> None:
        """触发指定事件的所有回调"""
        for callback in self._callbacks.get(event, []):
            try:
                if file_info is not None:
                    callback(file_info)
                else:
                    callback()
            except Exception:
                logger.exception(f"FileUploadController: {event} 回调异常")

    def get_supported_extensions(self) -> list[str]:
        """获取当前支持的文件扩展名

        如果视觉能力启用，返回所有支持的扩展名（包含图片）；
        如果禁用，只返回文档类型扩展名（不包含图片）。
        """
        if self._vision_enabled:
            return SUPPORTED_EXTENSIONS
        else:
            return DOCUMENT_EXTENSIONS

    def set_vision_enabled(self, enabled: bool) -> list[UploadedFileInfo]:
        """设置视觉能力启用状态

        Args:
            enabled: 是否启用视觉能力

        Returns:
            如果禁用视觉能力且有已上传图片，返回被清除的图片文件列表；
            否则返回空列表。
        """
        self._vision_enabled = enabled
        logger.info(f"FileUploadController: 视觉能力 {'启用' if enabled else '禁用'}")

        # 如果禁用视觉能力，清除已上传的图片文件
        removed_files: list[UploadedFileInfo] = []
        if not enabled:
            image_file_ids = [
                fid for fid, finfo in self._files.items()
                if finfo.extension.lower() in IMAGE_EXTENSIONS
            ]
            for file_id in image_file_ids:
                file_info = self._files[file_id]
                removed_files.append(file_info)
                del self._files[file_id]
                self._emit("file_removed", file_info)
                self._emit("files_changed", file_info)

            if removed_files:
                logger.info(f"FileUploadController: 已清除 {len(removed_files)} 个图片文件")

        return removed_files

    def is_vision_enabled(self) -> bool:
        """获取视觉能力启用状态"""
        return self._vision_enabled

    def get_file_filter(self) -> str:
        """获取文件选择器的过滤器字符串

        根据当前支持的扩展名生成适用于文件选择对话框的过滤器描述。

        Returns:
            str: 格式化的文件过滤器字符串，如 "支持的文件 (*.docx *.pdf ...)"
        """
        extensions = self.get_supported_extensions()
        filter_parts = [f"*.{ext}" for ext in extensions]
        return f"支持的文件 ({' '.join(filter_parts)})"

    def can_add_file(self) -> bool:
        """判断是否还可以添加更多文件

        Returns:
            bool: 当前文件数量未达到上限时返回 True，否则返回 False
        """
        return len(self._files) < self._max_files

    def get_remaining_slots(self) -> int:
        """获取剩余可上传文件数量"""
        return max(0, self._max_files - len(self._files))

    def validate_file(self, file_path: Path) -> Optional[str]:
        """校验文件是否满足上传条件

        依次检查文件是否存在、是否为文件、扩展名是否受支持、文件大小是否超限。

        Args:
            file_path: 待校验文件的路径

        Returns:
            Optional[str]: 校验通过返回 None；校验失败返回错误描述字符串
        """
        if not file_path.exists():
            return f"文件不存在: {file_path}"
        if not file_path.is_file():
            return f"路径不是文件: {file_path}"

        extension = file_path.suffix.lower().lstrip(".")
        if extension not in SUPPORTED_EXTENSIONS:
            return f"不支持的文件类型: {file_path.suffix}"

        file_size = file_path.stat().st_size
        if file_size > self._max_file_size:
            size_mb = file_size / (1024 * 1024)
            max_mb = self._max_file_size / (1024 * 1024)
            return f"文件过大 ({size_mb:.1f} MB)，最大支持 {max_mb:.0f} MB"

        return None

    def add_file(self, file_path: Path) -> Optional[UploadedFileInfo]:
        """添加文件到上传列表

        对文件进行校验和数量检查后创建文件信息对象，并自动触发异步解析。

        Args:
            file_path: 待添加文件的路径

        Returns:
            Optional[UploadedFileInfo]: 添加成功返回文件信息对象；
                校验失败或数量超限时返回 None
        """
        validation_error = self.validate_file(file_path)
        if validation_error:
            self._emit_upload_error(validation_error)
            return None

        if not self.can_add_file():
            self._emit_upload_error(f"最多只能上传 {self._max_files} 个文件")
            return None

        file_id = uuid.uuid4().hex
        extension = file_path.suffix.lower().lstrip(".")

        file_info = UploadedFileInfo(
            file_id=file_id,
            original_name=file_path.name,
            file_path=file_path,
            file_size=file_path.stat().st_size,
            extension=extension,
            mime_type=UploadedFileInfo.mime_map.get(extension),
            upload_time=datetime.now(),
        )

        self._files[file_id] = file_info
        self._emit("file_added", file_info)
        self._emit("files_changed", file_info)

        self._start_parse(file_id)
        return file_info

    def remove_file(self, file_id: str) -> None:
        """从上传列表中移除指定文件

        Args:
            file_id: 要移除的文件 ID
        """
        if file_id not in self._files:
            return

        file_info = self._files[file_id]
        del self._files[file_id]
        self._emit("file_removed", file_info)
        self._emit("files_changed", file_info)

    def clear_all_files(self) -> None:
        """清除所有已上传的文件"""
        for file_id in list(self._files.keys()):
            self.remove_file(file_id)

    def get_file(self, file_id: str) -> Optional[UploadedFileInfo]:
        """根据文件 ID 获取文件信息

        Args:
            file_id: 文件 ID

        Returns:
            Optional[UploadedFileInfo]: 对应的文件信息对象；不存在时返回 None
        """
        return self._files.get(file_id)

    def get_all_files(self) -> list[UploadedFileInfo]:
        """获取所有已上传文件的信息列表

        Returns:
            list[UploadedFileInfo]: 所有文件信息对象的列表
        """
        return list(self._files.values())

    def get_parsed_files(self) -> list[UploadedFileInfo]:
        """获取所有解析成功的文件列表

        Returns:
            list[UploadedFileInfo]: 所有解析成功（is_success 为 True）的文件信息列表
        """
        return [f for f in self._files.values() if f.is_success]

    def has_files(self) -> bool:
        """判断是否存在已上传的文件

        Returns:
            bool: 有文件时返回 True，否则返回 False
        """
        return len(self._files) > 0

    def file_count(self) -> int:
        """获取当前已上传文件的数量

        Returns:
            int: 文件数量
        """
        return len(self._files)

    def _start_parse(self, file_id: str) -> None:
        """启动文件异步解析流程"""
        file_info = self._files.get(file_id)
        if not file_info:
            return

        file_info.is_parsing = True
        file_info.is_parsed = False
        file_info.parse_error = None
        file_info.parse_progress = 0
        file_info.parse_status = "开始解析..."
        self._emit("file_parse_started", file_info)

        try:
            from document_parser import parse_file, ParserFactory

            if not ParserFactory.is_supported(file_info.file_path):
                error = f"不支持的文件类型: {file_info.file_path.suffix}"
                self._on_parse_error(file_id, error)
                return

            asyncio.create_task(self._parse_async(file_id, file_info.file_path))
        except Exception as e:
            logger.exception("FileUploadController: 启动解析失败")
            self._on_parse_error(file_id, str(e))

    async def _parse_async(self, file_id: str, file_path: Path) -> None:
        """异步解析文件"""
        try:
            from document_parser import parse_file

            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, parse_file, file_path)

            if result.is_success:
                self._on_parse_finished(file_id, result)
            else:
                self._on_parse_error(file_id, result.error or "解析失败")
        except Exception as e:
            self._on_parse_error(file_id, str(e))

    def _on_parse_finished(self, file_id: str, result: Any) -> None:
        """处理文件解析完成事件"""
        file_info = self._files.get(file_id)
        if not file_info:
            return

        file_info.is_parsing = False
        file_info.is_parsed = True
        file_info.parse_result = result
        file_info.parse_error = None
        file_info.parse_progress = 100
        file_info.parse_status = "解析完成"
        self._emit("file_parse_finished", file_info)
        logger.info(f"FileUploadController: 文件解析完成 {file_info.original_name}")

    def _on_parse_error(self, file_id: str, error: str) -> None:
        """处理文件解析失败事件"""
        file_info = self._files.get(file_id)
        if not file_info:
            return

        file_info.is_parsing = False
        file_info.is_parsed = False
        file_info.parse_result = None
        file_info.parse_error = error
        file_info.parse_progress = 0
        file_info.parse_status = "解析失败"
        self._emit("file_parse_error", file_info)
        logger.error(f"FileUploadController: 文件解析失败 {file_info.original_name}: {error}")

    def _emit_upload_error(self, message: str) -> None:
        """触发上传错误回调并记录日志"""
        logger.warning(f"FileUploadController: {message}")
        for callback in self._callbacks.get("upload_error", []):
            try:
                callback(message)
            except Exception:
                logger.exception("FileUploadController: upload_error 回调异常")

    def generate_file_summary(self, file_info: UploadedFileInfo) -> str:
        """生成单个文件的摘要文本

        包含文件名、类型、大小、摘要和内容预览信息。

        Args:
            file_info: 已上传文件的信息对象

        Returns:
            str: 格式化的文件摘要文本；文件未解析成功时返回空字符串
        """
        if not file_info.is_success:
            return ""

        result = file_info.parse_result
        if not result:
            return ""

        content = result.content or ""
        summary = result.summary or ""
        preview = content[:300] if len(content) > 300 else content

        summary_parts = [
            f"【文件: {file_info.original_name}】",
            f"类型: {file_info.extension.upper()}",
            f"大小: {file_info.get_file_size_display()}",
        ]

        if summary:
            summary_parts.append(f"摘要: {summary}")
        if preview:
            summary_parts.append(f"内容预览:\n{preview}")

        return "\n".join(summary_parts)

    def generate_combined_summary(self) -> str:
        """生成所有已解析文件的合并摘要文本

        将所有解析成功的文件的摘要信息合并为一段完整的文本，
        各文件之间用分隔线隔开。

        Returns:
            str: 合并后的摘要文本；无已解析文件时返回空字符串
        """
        parsed_files = self.get_parsed_files()
        if not parsed_files:
            return ""

        summaries = []
        for file_info in parsed_files:
            summary = self.generate_file_summary(file_info)
            if summary:
                summaries.append(summary)

        if not summaries:
            return ""

        header = f"已上传 {len(parsed_files)} 个文件，以下是文件内容摘要："
        return header + "\n\n" + "\n\n---\n\n".join(summaries)

    def generate_file_full_content(self, file_info: UploadedFileInfo) -> str:
        """生成单个文件的完整内容（XML 格式）

        将文件的解析内容包装为 <filename> 和 <file_content> 标签格式。

        Args:
            file_info: 已上传文件的信息对象

        Returns:
            str: XML 格式的文件完整内容；文件未解析成功或无内容时返回空字符串
        """
        if not file_info.is_success:
            return ""

        result = file_info.parse_result
        if not result:
            return ""

        content = result.content or ""
        if not content:
            return ""

        return f"<filename>{file_info.original_name}</filename>\n<file_content>\n{content}\n</file_content>"

    def generate_combined_full_content(self) -> str:
        """生成所有已解析文件的合并完整内容（XML 格式）

        将所有解析成功的文件内容合并，用 <user_upload_files> 标签包裹。

        Returns:
            str: XML 格式的所有文件完整内容；无已解析文件时返回空字符串
        """
        parsed_files = self.get_parsed_files()
        if not parsed_files:
            return ""

        contents = []
        for file_info in parsed_files:
            full_content = self.generate_file_full_content(file_info)
            if full_content:
                contents.append(full_content)

        if not contents:
            return ""

        files_content = "\n\n".join(contents)
        return f"<user_upload_files>\n{files_content}\n</user_upload_files>"

    @staticmethod
    def generate_full_content_from_list(files: list[UploadedFileInfo]) -> dict:
        """从文件列表生成完整内容（用于系统提示词），不依赖控制器内部状态

        Returns:
            dict: 包含以下字段的结构化数据：
                - text_content: str, XML 格式的文本内容（<user_upload_files>）
                - images: list, 图片数据列表，每项包含：
                    - file_name: str, 文件名
                    - base64_data: str, base64 编码的图片数据
                    - mime_type: str, MIME 类型（如 "image/png"）
        """
        text_contents = []
        images = []

        for file_info in files:
            if not file_info.is_success:
                continue
            result = file_info.parse_result
            if not result:
                continue
            content = result.content or ""
            if not content:
                continue

            # 检查是否为图片（通过 metadata.content_type 判断）
            content_type = result.metadata.get("content_type", "text")
            if content_type == "base64_image":
                # 提取图片数据
                images.append({
                    "file_name": file_info.original_name,
                    "base64_data": content,
                    "mime_type": result.metadata.get("mime_type", "application/octet-stream"),
                })
            else:
                # 文本内容，保持原有 XML 格式
                text_contents.append(
                    f"<filename>{file_info.original_name}</filename>\n"
                    f"<file_content>\n{content}\n</file_content>"
                )

        # 生成 text_content
        if text_contents:
            text_content = f"<user_upload_files>\n" + "\n\n".join(text_contents) + "\n</user_upload_files>"
        else:
            text_content = ""

        return {
            "text_content": text_content,
            "images": images,
        }

    def inject_summary_to_message(self, user_message: str) -> str:
        """将文件摘要注入到用户消息中

        在用户消息前附加所有已解析文件的合并摘要，用分隔线隔开。

        Args:
            user_message: 原始用户消息文本

        Returns:
            str: 注入文件摘要后的消息文本；无摘要时返回原始消息
        """
        combined_summary = self.generate_combined_summary()
        if not combined_summary:
            return user_message
        return f"{combined_summary}\n\n---\n\n用户消息:\n{user_message}"
