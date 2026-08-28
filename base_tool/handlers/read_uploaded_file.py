"""read_uploaded_file 工具处理器

读取用户上传文件的解析文本（持久层懒加载）。
与 uploaded_files 工具的区别：后者依赖会话内存态 file_upload_controller，
本工具直接读 PersonalData/uploads 持久层（manifest + sidecar），
跨会话、跨进程重启可用，是历史消息占位符短标记的配套读取通道。
"""
from __future__ import annotations

from .base import ToolHandler
from ..context import ToolContext
from . import register_handler


class ReadUploadedFileHandler(ToolHandler):
    """按 file_id 读取用户上传文件的解析文本。"""

    @property
    def name(self) -> str:
        """返回工具名称"""
        return "read_uploaded_file"

    def execute(self, args: dict, ctx: ToolContext, registry) -> str:
        """读取上传文件解析文本

        Args:
            args: 工具参数字典，支持 file_id
            ctx: ToolContext 执行上下文（本工具不依赖会话状态）
            registry: 工具注册表

        Returns:
            工具执行结果的字符串
        """
        file_id = str(args.get("file_id", "")).strip()
        if not file_id:
            return "错误: read_uploaded_file 需要 file_id 参数"

        from document_parser.file_storage import get_upload_info, get_uploaded_text

        info = get_upload_info(file_id)
        if info is None:
            return f"错误: 未找到上传文件（file_id: {file_id}）。请确认用户消息中引用的 file_id 是否正确"

        file_name = info.get("file_name") or file_id
        text = get_uploaded_text(file_id)
        if text is None:
            return f"错误: 文件「{file_name}」已丢失或不可读（file_id: {file_id}）"

        result = f"【上传文件内容: {file_name}】（file_id: {file_id}）\n"
        result += f"--- 文件内容 ---\n{text}\n"
        return result


register_handler(ReadUploadedFileHandler())
