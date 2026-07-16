"""设置页面第二轮字号/尺寸缩小脚本。"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

SIZE_MAP = {
    18: 16,
    16: 14,
    15: 13,
    14: 12,
    13: 12,
    12: 11,
    11: 10,
}

ICON_SIZE_MAP = {
    20: 18,
    18: 16,
    16: 14,
}

PADDING_MAP = {
    30: 20,
    24: 16,
    22: 16,
    18: 12,
    15: 12,
    12: 10,
}

HEIGHT_MAP = {
    30: 20,
    24: 16,
    22: 16,
    20: 14,
    18: 12,
    15: 12,
    12: 10,
}

SPACING_MAP = {
    18: 12,
    15: 12,
    12: 10,
}


def _char_offset(source: str, lineno: int, col_offset: int) -> int:
    lines = source.splitlines(keepends=True)
    offset = 0
    for i in range(lineno - 1):
        offset += len(lines[i])
    return offset + col_offset


def _get_node_span(source: str, node: ast.AST) -> tuple[int, int]:
    start = _char_offset(source, node.lineno, node.col_offset)
    end = _char_offset(source, node.end_lineno, node.end_col_offset)
    return start, end


def _int_constant_value(node: ast.expr) -> int | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    return None


def _add_bold_after_kw(source: str, kw: ast.keyword) -> tuple[int, str]:
    start, end = _get_node_span(source, kw)
    return end, ", weight=ft.FontWeight.BOLD"


def process_file(path: Path) -> list[str]:
    source_bytes = path.read_bytes()
    source = source_bytes.decode("utf-8")
    tree = ast.parse(source)

    # (start, end, new_text)
    replacements: list[tuple[int, int, str]] = []
    # (insert_pos, text)
    bold_insertions: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        func_name: str | None = None
        if isinstance(node.func, ast.Attribute):
            func_name = node.func.attr
        elif isinstance(node.func, ast.Name):
            func_name = node.func.id

        if func_name not in ("Text", "IconButton", "Container", "Column", "Row"):
            continue

        has_weight = False
        size_kw: ast.keyword | None = None

        for kw in node.keywords:
            if func_name == "Text" and kw.arg == "weight":
                has_weight = True
            if func_name == "Text" and kw.arg == "size":
                size_kw = kw

            old_val = _int_constant_value(kw.value)
            if old_val is None:
                continue

            new_val: int | None = None
            if func_name == "Text" and kw.arg == "size":
                new_val = SIZE_MAP.get(old_val)
            elif func_name == "IconButton" and kw.arg == "icon_size":
                new_val = ICON_SIZE_MAP.get(old_val)
            elif func_name == "Container" and kw.arg == "padding":
                new_val = PADDING_MAP.get(old_val)
            elif func_name == "Container" and kw.arg == "height":
                new_val = HEIGHT_MAP.get(old_val)
            elif func_name in ("Column", "Row") and kw.arg == "spacing":
                new_val = SPACING_MAP.get(old_val)

            if new_val is None:
                continue

            start, end = _get_node_span(source, kw.value)
            replacements.append((start, end, str(new_val)))

        # size=16 -> 14 且没有 weight 时添加 BOLD
        if func_name == "Text" and size_kw is not None and not has_weight:
            old_size = _int_constant_value(size_kw.value)
            if old_size == 16:
                insert_pos, text = _add_bold_after_kw(source, size_kw)
                bold_insertions.append((insert_pos, text))

    # 计算 bold 插入位置因替换带来的偏移
    adjusted_bold: list[tuple[int, str]] = []
    for pos, text in bold_insertions:
        delta = 0
        for start, end, new_text in replacements:
            if end <= pos:
                delta += len(new_text) - (end - start)
        adjusted_bold.append((pos + delta, text))

    # 按位置降序应用，避免偏移问题
    all_changes = [(s, e, t, "replace") for s, e, t in replacements]
    all_changes += [(p, p, t, "insert") for p, t in adjusted_bold]
    all_changes.sort(key=lambda x: x[0], reverse=True)

    new_source = source
    for start, end, text, _ in all_changes:
        new_source = new_source[:start] + text + new_source[end:]

    path.write_bytes(new_source.encode("utf-8"))

    return [f"{path.name}: {len(replacements)} replacements, {len(bold_insertions)} bold additions"]


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        file_path = Path(arg)
        if file_path.exists():
            for line in process_file(file_path):
                print(line)
        else:
            print(f"File not found: {file_path}")
