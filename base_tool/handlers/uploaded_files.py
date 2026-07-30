"""uploaded_files 工具处理器"""
from __future__ import annotations

from .base import ToolHandler
from ..context import ToolContext
from . import register_handler


class UploadedFilesHandler(ToolHandler):
    """已上传文件管理工具处理器

    支持 list/get_content/get_metadata 三种操作。
    """

    @property
    def name(self) -> str:
        """返回工具名称"""
        return "uploaded_files"

    def execute(self, args: dict, ctx: ToolContext, registry) -> str:
        """管理已上传文件，支持 list/get_content/get_metadata 三种操作

        Args:
            args: 工具参数字典，支持 action、file_name
            ctx: ToolContext 执行上下文
            registry: 工具注册表

        Returns:
            工具执行结果的字符串
        """
        action = args.get("action", "")
        file_name = args.get("file_name", "")

        if ctx.file_upload_controller is None:
            return "错误: 当前会话没有文件上传功能可用"

        controller = ctx.file_upload_controller

        if action == "list":
            all_files = controller.get_all_files()
            if not all_files:
                return "当前没有已上传的文件。\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"

            file_list = []
            for f in all_files:
                status = "解析成功" if f.is_success else ("解析失败" if f.parse_error else ("解析中..." if f.is_parsing else "待解析"))
                file_list.append(
                    f"- 文件名: {f.original_name}\n"
                    f"  文件ID: {f.file_id}\n"
                    f"  类型: {f.extension.upper()}\n"
                    f"  大小: {f.get_file_size_display()}\n"
                    f"  上传时间: {f.upload_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"  状态: {status}"
                )
                if f.parse_error:
                    file_list[-1] += f"\n  错误: {f.parse_error}"
                if f.summary:
                    summary_preview = f.summary[:100] + "..." if len(f.summary) > 100 else f.summary
                    file_list[-1] += f"\n  摘要预览: {summary_preview}"

            result = f"已上传文件列表（共 {len(all_files)} 个）：\n\n" + "\n\n".join(file_list)
            result += "\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"
            return result

        elif action == "get_content":
            if not file_name:
                return "错误: get_content 操作需要提供 file_name 参数"

            all_files = controller.get_all_files()
            target_file = None
            for f in all_files:
                if f.original_name == file_name or f.file_id == file_name:
                    target_file = f
                    break

            if target_file is None:
                available_names = [f.original_name for f in all_files]
                return f"错误: 未找到文件「{file_name}」。可用文件: {', '.join(available_names) if available_names else '无'}"

            if not target_file.is_success:
                if target_file.is_parsing:
                    return f"文件「{file_name}」正在解析中，请稍后再试。"
                elif target_file.parse_error:
                    return f"错误: 文件「{file_name}」解析失败: {target_file.parse_error}"
                else:
                    return f"错误: 文件「{file_name}」尚未解析完成"

            parse_result = target_file.parse_result
            if parse_result is None:
                return f"错误: 文件「{file_name}」没有解析结果"

            content = parse_result.content or ""
            result = f"【文件内容: {target_file.original_name}】\n"
            result += f"类型: {target_file.extension.upper()}\n"
            result += f"大小: {target_file.get_file_size_display()}\n"
            result += f"上传时间: {target_file.upload_time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            result += f"--- 文件内容 ---\n{content}\n"

            if parse_result.summary:
                result += f"\n--- 内容摘要 ---\n{parse_result.summary}\n"

            result += "\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"
            return result

        elif action == "get_metadata":
            if not file_name:
                return "错误: get_metadata 操作需要提供 file_name 参数"

            all_files = controller.get_all_files()
            target_file = None
            for f in all_files:
                if f.original_name == file_name or f.file_id == file_name:
                    target_file = f
                    break

            if target_file is None:
                available_names = [f.original_name for f in all_files]
                return f"错误: 未找到文件「{file_name}」。可用文件: {', '.join(available_names) if available_names else '无'}"

            metadata_info = {
                "文件名": target_file.original_name,
                "文件ID": target_file.file_id,
                "文件类型": target_file.extension.upper(),
                "MIME类型": target_file.mime_type or "未知",
                "文件大小": target_file.get_file_size_display(),
                "原始路径": str(target_file.file_path),
                "上传时间": target_file.upload_time.strftime("%Y-%m-%d %H:%M:%S"),
                "解析状态": "成功" if target_file.is_success else ("失败" if target_file.parse_error else ("解析中" if target_file.is_parsing else "待解析")),
            }

            if target_file.parse_error:
                metadata_info["解析错误"] = target_file.parse_error

            if target_file.parse_result and hasattr(target_file.parse_result, "metadata"):
                extra_meta = target_file.parse_result.metadata
                if extra_meta:
                    for key, value in extra_meta.items():
                        metadata_info[f"解析元数据.{key}"] = value

            result_lines = [f"【文件元信息: {target_file.original_name}】"]
            for key, value in metadata_info.items():
                result_lines.append(f"- {key}: {value}")

            result = "\n".join(result_lines)
            result += "\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"
            return result

        else:
            return f"错误: 未知的 action: {action}，支持 list/get_content/get_metadata"


register_handler(UploadedFilesHandler())
