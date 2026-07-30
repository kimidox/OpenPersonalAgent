"""设置页面第二轮字号/尺寸缩小脚本（基于字节偏移修正版）。"""
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


def _byte_offset(source_bytes: bytes, lineno: int, col_offset: int) -> int:
    lines = source_bytes.splitlines(keepends=True)
    offset = 0
    for i in range(lineno - 1):
        offset += len(lines[i])
    return offset + col_offset


def _get_node_span_bytes(source_bytes: bytes, node: ast.AST) -> tuple[int, int]:
    start = _byte_offset(source_bytes, node.lineno, node.col_offset)
    end = _byte_offset(source_bytes, node.end_lineno, node.end_col_offset)
    return start, end


def _int_constant_value(node: ast.expr) -> int | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    return None


def process_file(path: Path) -> str:
    source_bytes = path.read_bytes()
    source = source_bytes.decode("utf-8")
    tree = ast.parse(source)

    replacements: list[tuple[int, int, bytes]] = []
    bold_insertions: list[tuple[int, bytes]] = []

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

            start, end = _get_node_span_bytes(source_bytes, kw.value)
            replacements.append((start, end, str(new_val).encode("utf-8")))

        if func_name == "Text" and size_kw is not None and not has_weight:
            old_size = _int_constant_value(size_kw.value)
            if old_size == 16:
                _start, end = _get_node_span_bytes(source_bytes, size_kw)
                bold_insertions.append((end, b", weight=ft.FontWeight.BOLD"))

    adjusted_bold: list[tuple[int, bytes]] = []
    for pos, text in bold_insertions:
        delta = 0
        for start, end, new_text in replacements:
            if end <= pos:
                delta += len(new_text) - (end - start)
        adjusted_bold.append((pos + delta, text))

    all_changes = [(s, e, t, "replace") for s, e, t in replacements]
    all_changes += [(p, p, t, "insert") for p, t in adjusted_bold]
    all_changes.sort(key=lambda x: x[0], reverse=True)

    new_source = source_bytes
    for start, end, text, _ in all_changes:
        new_source = new_source[:start] + text + new_source[end:]

    path.write_bytes(new_source)

    return f"{path.name}: {len(replacements)} replacements, {len(bold_insertions)} bold additions"


if __name__ == "__main__":
    from logger import get_module_logger
    _logger = get_module_logger("resize_settings_v2")

    for arg in sys.argv[1:]:
        file_path = Path(arg)
        if file_path.exists():
            _logger.info(process_file(file_path))
        else:
            _logger.warning("File not found: %s", file_path)
