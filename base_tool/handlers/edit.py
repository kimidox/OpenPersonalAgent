"""edit 工具处理器"""
from __future__ import annotations

from .base import ToolHandler
from ..context import ToolContext
from . import register_handler


def _find_all_matches(content: str, old_str: str) -> list[int]:
    """查找 old_str 在 content 中所有匹配的起始行号（1-based）。

    Returns:
        匹配的起始行号列表（1-based），按出现顺序排列。
        行号指匹配内容第一行在文件中的行号。
    """
    if not old_str or old_str not in content:
        return []

    lines = content.split("\n")
    match_start_lines = []
    start = 0

    while True:
        idx = content.find(old_str, start)
        if idx == -1:
            break
        # 计算该位置对应的行号（1-based）
        line_no = content[:idx].count("\n") + 1
        match_start_lines.append(line_no)
        start = idx + 1

    return match_start_lines


def _content_from_line(content: str, start_line: int) -> tuple[str, int]:
    """从 start_line 行开始截取内容，返回 (截取后的内容, 截取的字符偏移量)。

    Args:
        content: 完整文件内容
        start_line: 起始行号（1-based）

    Returns:
        (从 start_line 开始的内容, start_line 第一个字符在原始 content 中的偏移量)
    """
    if start_line <= 1:
        return content, 0

    lines = content.split("\n")
    if start_line > len(lines):
        return "", len(content)

    # 计算前 start_line-1 行的字符总数（含换行符）
    offset = 0
    for i in range(start_line - 1):
        offset += len(lines[i]) + 1  # +1 for the \n

    return content[offset:], offset


class EditHandler(ToolHandler):
    """文件编辑工具处理器

    实现文件内容替换（old_str -> new_str），支持：
    - 唯一性校验：匹配多次时拒绝替换并报告所有匹配行号
    - start_line 参数：从指定行号开始搜索
    - replace_all 参数：替换所有匹配项
    - 增强错误信息：包含匹配位置和行号
    """

    @property
    def name(self) -> str:
        """返回工具名称"""
        return "edit"

    def execute(self, args: dict, ctx: ToolContext, registry) -> str:
        """执行文件内容替换操作，将 old_str 替换为 new_str

        Args:
            args: 工具参数字典，支持 path、old_str、new_str、start_line、replace_all、skill_id
            ctx: ToolContext 执行上下文
            registry: 工具注册表

        Returns:
            工具执行结果的字符串
        """
        from ..dispatch import _resolve_safe, _splice_skill_path

        raw_path = args.get("path", "")
        old_str = args.get("old_str", "")
        new_str = args.get("new_str", "")
        start_line = args.get("start_line")
        replace_all = args.get("replace_all", False)
        skill_id = args.get("skill_id", "")

        if not old_str:
            return "错误: 缺少 old_str 参数"

        # 解析 start_line
        if start_line is not None:
            try:
                start_line = int(start_line)
                if start_line < 1:
                    return "错误: start_line 必须 >= 1"
            except (ValueError, TypeError):
                return "错误: start_line 必须是整数"

        # 解析 replace_all
        if isinstance(replace_all, str):
            replace_all = replace_all.lower() in ("true", "1", "yes")
        replace_all = bool(replace_all)

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

        total_lines = content.count("\n") + 1

        # 根据 start_line 截取搜索范围
        if start_line is not None:
            search_content, offset = _content_from_line(content, start_line)
            if not search_content:
                return f"错误: start_line={start_line} 超出文件范围（文件共 {total_lines} 行）"
        else:
            search_content = content
            offset = 0

        # 检查是否找到匹配
        if old_str not in search_content:
            if start_line is not None:
                return (
                    f"错误: 未找到要替换的内容（从第 {start_line} 行开始搜索）\n"
                    f"文件共 {total_lines} 行"
                )
            return f"错误: 未找到要替换的内容\n文件共 {total_lines} 行"

        # 查找所有匹配的行号
        match_lines = _find_all_matches(search_content, old_str)
        match_count = len(match_lines)

        # 将搜索范围内的行号转换为文件全局行号
        if start_line is not None and start_line > 1:
            global_match_lines = [ln + (start_line - 1) for ln in match_lines]
        else:
            global_match_lines = match_lines

        # 唯一性校验：匹配多次且未开启 replace_all 时拒绝替换
        if match_count > 1 and not replace_all:
            lines_info = ", ".join(str(ln) for ln in global_match_lines)
            return (
                f"错误: 要替换的内容在文件中匹配了 {match_count} 次，无法确定替换位置。\n"
                f"匹配行号: {lines_info}\n"
                f"建议:\n"
                f"  1. 扩大 old_str 范围，包含更多上下文使匹配唯一\n"
                f"  2. 使用 start_line 参数指定从哪一行开始搜索\n"
                f"  3. 如需替换所有匹配，设置 replace_all=true"
            )

        # 执行替换
        if replace_all:
            new_content = search_content.replace(old_str, new_str)
        else:
            new_content = search_content.replace(old_str, new_str, 1)

        # 如果使用了 start_line，需要将替换后的内容拼回原始文件
        if start_line is not None and start_line > 1:
            final_content = content[:offset] + new_content
        else:
            final_content = new_content

        try:
            target_path.write_text(final_content, encoding="utf-8")
            if replace_all and match_count > 1:
                return f"文件编辑成功: {target_path}（替换了 {match_count} 处匹配）\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"
            return f"文件编辑成功: {target_path}\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"
        except Exception as e:
            return f"错误: 写入文件失败: {e}"


register_handler(EditHandler())
