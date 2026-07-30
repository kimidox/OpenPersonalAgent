"""edit 工具处理器"""
from __future__ import annotations

from .base import ToolHandler
from ..context import ToolContext
from . import register_handler


class EditHandler(ToolHandler):
    """文件编辑工具处理器

    实现文件内容替换（old_str -> new_str）。
    """

    @property
    def name(self) -> str:
        """返回工具名称"""
        return "edit"

    def execute(self, args: dict, ctx: ToolContext, registry) -> str:
        """执行文件内容替换操作，将 old_str 替换为 new_str

        Args:
            args: 工具参数字典，支持 path、old_str、new_str、skill_id
            ctx: ToolContext 执行上下文
            registry: 工具注册表

        Returns:
            工具执行结果的字符串
        """
        from ..dispatch import _resolve_safe, _splice_skill_path

        raw_path = args.get("path", "")
        old_str = args.get("old_str", "")
        new_str = args.get("new_str", "")
        skill_id = args.get("skill_id", "")

        if not old_str:
            return "错误: 缺少 old_str 参数"

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

        if not target_path.exists():
            return f"错误: 文件不存在: {target_path}"
        if not target_path.is_file():
            return f"错误: 不是文件: {target_path}"

        try:
            content = target_path.read_text(encoding="utf-8")
        except Exception as e:
            return f"错误: 读取文件失败: {e}"

        if old_str not in content:
            return f"错误: 未找到要替换的内容"

        new_content = content.replace(old_str, new_str, 1)

        try:
            target_path.write_text(new_content, encoding="utf-8")
            return f"文件编辑成功: {target_path}\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"
        except Exception as e:
            return f"错误: 写入文件失败: {e}"


register_handler(EditHandler())
