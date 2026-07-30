"""scheduled_tasks 工具处理器"""
from __future__ import annotations

import json
from datetime import datetime

from .base import ToolHandler
from ..context import ToolContext
from . import register_handler


class CreateScheduledTaskHandler(ToolHandler):
    """创建定时任务处理器"""

    @property
    def name(self) -> str:
        """返回工具名称"""
        return "create_scheduled_task"

    def execute(self, args: dict, ctx: ToolContext, registry) -> str:
        """创建定时任务，支持一次性及重复执行

        Args:
            args: 工具参数字典，支持 title、trigger_time、content、repeat_type、execution_type、execution_chain、skill_ids
            ctx: ToolContext 执行上下文
            registry: 工具注册表

        Returns:
            工具执行结果的字符串
        """
        import scheduled_tasks as st_module

        title = args.get("title", "")
        trigger_time_str = args.get("trigger_time", "")
        content = args.get("content", "")
        repeat_type = args.get("repeat_type", "none")
        execution_type = args.get("execution_type", "notification")
        execution_chain = args.get("execution_chain", None)
        skill_ids_raw = args.get("skill_ids", None)

        if not title:
            return "错误: 缺少 title 参数"
        if not trigger_time_str:
            return "错误: 缺少 trigger_time 参数"

        try:
            trigger_time = datetime.fromisoformat(trigger_time_str)
        except ValueError:
            return f"错误: trigger_time 格式无效，应为 ISO 格式（YYYY-MM-DDTHH:MM:SS）"

        valid_repeat_types = ["none", "daily", "weekly", "monthly"]
        if repeat_type not in valid_repeat_types:
            return f"错误: repeat_type 无效，支持: {', '.join(valid_repeat_types)}"

        valid_execution_types = ["notification", "agent_conversation"]
        if execution_type not in valid_execution_types:
            return f"错误: execution_type 无效，支持: {', '.join(valid_execution_types)}"

        skill_ids = None
        if skill_ids_raw is not None:
            if isinstance(skill_ids_raw, str):
                try:
                    skill_ids = json.loads(skill_ids_raw)
                    if not isinstance(skill_ids, list):
                        return "错误: skill_ids 必须是字符串列表"
                except json.JSONDecodeError:
                    return "错误: skill_ids JSON 解析失败"
            elif isinstance(skill_ids_raw, list):
                skill_ids = skill_ids_raw
            else:
                return "错误: skill_ids 必须是字符串或列表"

        user_id = ctx.user_id or "default"
        source_conversation_id = getattr(ctx, "conversation_id", None)

        try:
            task = st_module.add_task(
                user_id=user_id,
                title=title,
                content=content,
                trigger_time=trigger_time,
                repeat_type=repeat_type,
                execution_type=execution_type,
                execution_chain=execution_chain,
                source_conversation_id=source_conversation_id,
                skill_ids=skill_ids,
            )
            task_info = task.to_dict()
            result = (
                f"定时任务创建成功！\n"
                f"- 任务ID: {task_info['task_id']}\n"
                f"- 标题: {task_info['title']}\n"
                f"- 内容: {task_info['content'] or '(无)'}\n"
                f"- 触发时间: {task_info['trigger_time']}\n"
                f"- 重复类型: {task_info['repeat_type']}\n"
                f"- 执行类型: {task_info['execution_type']}\n"
            )
            if execution_type == "agent_conversation":
                if task_info.get("skill_ids"):
                    result += f"- 关联技能: {', '.join(task_info['skill_ids'])}\n"
                if task_info.get("execution_chain"):
                    chain_preview = task_info["execution_chain"][:100]
                    if len(task_info["execution_chain"]) > 100:
                        chain_preview += "..."
                    result += f"- 执行链路: {chain_preview}\n"
            result += f"- 状态: {task_info['status']}\n\n"
            result += "✓ 操作成功。如果任务已完成，请调用 finish 结束。"
            return result
        except Exception as e:
            return f"错误: 创建定时任务失败: {e}"


class ListScheduledTasksHandler(ToolHandler):
    """列出定时任务处理器"""

    @property
    def name(self) -> str:
        """返回工具名称"""
        return "list_scheduled_tasks"

    def execute(self, args: dict, ctx: ToolContext, registry) -> str:
        """列出当前用户的定时任务，可按状态过滤

        Args:
            args: 工具参数字典，支持 status
            ctx: ToolContext 执行上下文
            registry: 工具注册表

        Returns:
            工具执行结果的字符串
        """
        import scheduled_tasks as st_module

        status = args.get("status", None)

        valid_statuses = ["pending", "triggered", "cancelled", "deleted"]
        if status and status not in valid_statuses:
            return f"错误: status 无效，支持: {', '.join(valid_statuses)}"

        user_id = ctx.user_id or "default"

        try:
            tasks = st_module.list_tasks(user_id=user_id, status=status)
            if not tasks:
                status_desc = f"状态为「{status}」的" if status else ""
                return f"当前没有{status_desc}定时任务。\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"

            task_list = []
            for task in tasks:
                task_info = task.to_dict()
                task_list.append(
                    f"- ID: {task_info['task_id']}\n"
                    f"  标题: {task_info['title']}\n"
                    f"  内容: {task_info['content'] or '(无)'}\n"
                    f"  触发时间: {task_info['trigger_time']}\n"
                    f"  重复类型: {task_info['repeat_type']}\n"
                    f"  状态: {task_info['status']}"
                )

            status_desc = f"（状态: {status})" if status else ""
            result = f"定时任务列表{status_desc}：\n\n" + "\n\n".join(task_list)
            result += "\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"
            return result
        except Exception as e:
            return f"错误: 获取定时任务列表失败: {e}"


class DeleteScheduledTaskHandler(ToolHandler):
    """删除定时任务处理器"""

    @property
    def name(self) -> str:
        """返回工具名称"""
        return "delete_scheduled_task"

    def execute(self, args: dict, ctx: ToolContext, registry) -> str:
        """删除指定的定时任务

        Args:
            args: 工具参数字典，支持 task_id
            ctx: ToolContext 执行上下文
            registry: 工具注册表

        Returns:
            工具执行结果的字符串
        """
        import scheduled_tasks as st_module

        task_id = args.get("task_id", "")

        if not task_id:
            return "错误: 缺少 task_id 参数"

        try:
            success = st_module.delete_task(task_id)
            if success:
                return f"定时任务已删除（ID: {task_id}）\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"
            else:
                return f"错误: 未找到任务（ID: {task_id}），可能已被删除"
        except Exception as e:
            return f"错误: 删除定时任务失败: {e}"


register_handler(CreateScheduledTaskHandler())
register_handler(ListScheduledTasksHandler())
register_handler(DeleteScheduledTaskHandler())
