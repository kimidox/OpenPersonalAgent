"""file_operation 工具处理器"""
from __future__ import annotations

from .base import ToolHandler
from ..context import ToolContext
from . import register_handler


class FileOperationHandler(ToolHandler):
    """文件操作工具处理器

    支持 read/write/delete/list 四种文件操作。
    当 skill_id 存在时，解析路径相对于 Skill 工作目录。
    """

    @property
    def name(self) -> str:
        """返回工具名称"""
        return "file_operation"

    def execute(self, args: dict, ctx: ToolContext, registry) -> str:
        """执行文件操作，支持 read/write/delete/list 四种操作

        Args:
            args: 工具参数字典，支持 action、path、content、skill_id
            ctx: ToolContext 执行上下文
            registry: 工具注册表

        Returns:
            工具执行结果的字符串
        """
        from ..dispatch import _resolve_safe, _splice_skill_path

        action = args.get("action", "")
        raw_path = args.get("path", "")
        skill_id = args.get("skill_id", "")

        if skill_id and registry:
            try:
                skill_relative_path = _splice_skill_path(raw_path or ".", str(skill_id), registry)
                target_path = _resolve_safe(ctx, skill_relative_path)
            except ValueError as e:
                return f"错误: {e}"
        else:
            try:
                target_path = _resolve_safe(ctx, raw_path)
            except ValueError as e:
                return f"错误: {e}"

        if action == "read":
            if not target_path.exists():
                return f"错误: 文件不存在: {target_path}"
            if not target_path.is_file():
                return f"错误: 不是文件: {target_path}"
            try:
                content = target_path.read_text(encoding="utf-8")
                return content + "\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"
            except Exception as e:
                return f"错误: 读取文件失败: {e}"

        elif action == "write":
            content = args.get("content", "")
            try:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_text(content, encoding="utf-8")
                return f"文件写入成功: {target_path}\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"
            except Exception as e:
                return f"错误: 写入文件失败: {e}"

        elif action == "delete":
            if not target_path.exists():
                return f"错误: 文件不存在: {target_path}"
            if not target_path.is_file():
                return f"错误: 不是文件: {target_path}"
            try:
                target_path.unlink()
                return f"文件删除成功: {target_path}\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"
            except Exception as e:
                return f"错误: 删除文件失败: {e}"

        elif action == "list":
            if not target_path.exists():
                return f"错误: 目录不存在: {target_path}"
            if not target_path.is_dir():
                return f"错误: 不是目录: {target_path}"
            try:
                items = list(target_path.iterdir())
                result_lines = []
                for item in sorted(items):
                    if item.is_dir():
                        result_lines.append(f"[DIR]  {item.name}/")
                    else:
                        result_lines.append(f"[FILE] {item.name}")
                return "\n".join(result_lines) if result_lines else "(空目录)"
            except Exception as e:
                return f"错误: 列出目录失败: {e}"

        else:
            return f"错误: 未知的 action: {action}，支持 read/write/delete/list"


register_handler(FileOperationHandler())
