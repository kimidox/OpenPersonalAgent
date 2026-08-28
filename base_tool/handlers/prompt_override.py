"""update_prompt 工具处理器（提示词自优化闭环）"""
from __future__ import annotations

from .base import ToolHandler
from ..context import ToolContext
from . import register_handler
from .. import prompt_overrides


class UpdatePromptHandler(ToolHandler):
    """工具提示词（description）编辑工具处理器

    支持 list/read/write/reset/rollback 五种操作，读写
    PersonalData/prompts/tools/ 下的描述覆盖文件，修改立即生效并持久化。
    """

    @property
    def name(self) -> str:
        """返回工具名称"""
        return "update_prompt"

    def execute(self, args: dict, ctx: ToolContext, registry) -> str:
        """编辑工具描述覆盖文件，实现提示词自优化

        Args:
            args: 工具参数字典，支持 action、tool_name、content
            ctx: 工具执行上下文
            registry: 工具注册表

        Returns:
            工具执行结果的字符串
        """
        action = args.get("action", "")
        tool_name = args.get("tool_name", "")
        content = args.get("content", "")

        valid_actions = ["list", "read", "write", "reset", "rollback"]
        if action not in valid_actions:
            return f"错误: action 无效，支持: {', '.join(valid_actions)}"

        if action != "list" and not tool_name:
            return f"错误: 缺少 tool_name 参数（action={action} 需要）"

        try:
            if action == "list":
                return self._handle_list()
            if action == "read":
                return self._handle_read(tool_name)
            if action == "write":
                return self._handle_write(tool_name, content)
            if action == "reset":
                return self._handle_reset(tool_name)
            return self._handle_rollback(tool_name)
        except Exception as exc:
            return f"错误: update_prompt 执行失败（action={action}, tool_name={tool_name}）: {exc}"

    def _handle_list(self) -> str:
        statuses = prompt_overrides.list_tool_override_status()
        lines = ["可优化工具描述列表："]
        for item in statuses:
            flags = []
            if item["customized"]:
                flags.append("已自定义")
            else:
                flags.append("默认")
            if item["has_backup"]:
                flags.append("可回滚")
            lines.append(f"- {item['tool_name']}（{'、'.join(flags)}）")
        lines.append("\n提示: 使用 read 查看当前描述，write 保存优化版本，rollback 回滚上次修改，reset 恢复出厂默认。")
        lines.append("✓ 操作成功。如果任务已完成，请调用 finish 结束。")
        return "\n".join(lines)

    def _handle_read(self, tool_name: str) -> str:
        description = prompt_overrides.read_tool_override(tool_name)
        if description is None:
            known = "、".join(prompt_overrides.get_known_tool_names())
            return f"错误: 未知工具 {tool_name}。支持的工具: {known}"
        has_backup = (prompt_overrides.get_tool_prompts_dir() / f"{tool_name}.md.bak").is_file()
        header = f"工具 {tool_name} 当前生效的 description：\n\n---\n{description}\n---\n"
        backup_note = "\n注意: 存在可回滚的上次修改快照，可用 rollback 恢复。" if has_backup else ""
        return header + backup_note + "\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"

    def _handle_write(self, tool_name: str, content: str) -> str:
        if not content or not content.strip():
            return "错误: content 不能为空"
        if prompt_overrides.save_tool_override(tool_name, content.strip()):
            brief = content.strip().split("\n")[0]
            return (
                f"已保存工具 {tool_name} 的描述优化，立即生效并持久化。\n"
                f"新的目录简要描述（正文第一行）: {brief}\n"
                f"修改前的版本已快照为 .bak，可随时用 rollback 回滚。\n\n"
                "✓ 操作成功。如果任务已完成，请调用 finish 结束。"
            )
        known = "、".join(prompt_overrides.get_known_tool_names())
        return f"错误: 保存失败（工具未知或内容无效）。支持的工具: {known}"

    def _handle_reset(self, tool_name: str) -> str:
        if prompt_overrides.reset_tool_override(tool_name):
            return (
                f"已将工具 {tool_name} 的描述重置为出厂默认值。\n"
                "重置前的版本已快照，如需找回可用 rollback。\n\n"
                "✓ 操作成功。如果任务已完成，请调用 finish 结束。"
            )
        return f"错误: 重置失败（未知工具 {tool_name}）"

    def _handle_rollback(self, tool_name: str) -> str:
        if prompt_overrides.rollback_tool_override(tool_name):
            return (
                f"已将工具 {tool_name} 的描述回滚为上一次修改前的版本，立即生效。\n\n"
                "✓ 操作成功。如果任务已完成，请调用 finish 结束。"
            )
        return f"错误: 回滚失败（工具 {tool_name} 不存在 .bak 快照，无可回滚版本）"


register_handler(UpdatePromptHandler())
