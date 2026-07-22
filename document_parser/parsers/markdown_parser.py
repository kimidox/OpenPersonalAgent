from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..base_parser import BaseParser
from ..models import ParseResult


class MarkdownParser(BaseParser):
    """Markdown 文件解析器。"""

    SUPPORTED_EXTENSIONS = [".md", ".markdown"]

    def parse(self, file_path: Path) -> ParseResult:
        """解析 Markdown 文件。

        Args:
            file_path: 要解析的文件路径

        Returns:
            ParseResult: 包含内容、元信息和摘要的解析结果
        """
        content = self._read_file(file_path)

        metadata = self._extract_metadata(file_path, content)
        summary = self._generate_summary(content)

        return ParseResult(
            content=content,
            metadata=metadata,
            summary=summary,
        )

    def _extract_metadata(self, file_path: Path, content: str) -> dict[str, Any]:
        """提取 Markdown 文件的元信息。

        Args:
            file_path: 文件路径
            content: 文件内容

        Returns:
            dict: 元信息字典
        """
        stat = file_path.stat()

        headings = self._extract_headings(content)
        links = self._extract_links(content)
        images = self._extract_images(content)
        code_blocks = self._extract_code_blocks(content)
        tables = self._extract_tables(content)

        lines = content.splitlines()
        word_count = len(content.split())
        char_count = len(content)

        return {
            "content_type": "text",
            "file_name": file_path.name,
            "file_size": stat.st_size,
            "created_time": stat.st_ctime,
            "modified_time": stat.st_mtime,
            "line_count": len(lines),
            "word_count": word_count,
            "char_count": char_count,
            "encoding": self.encoding,
            "headings": headings,
            "heading_count": len(headings),
            "link_count": len(links),
            "image_count": len(images),
            "code_block_count": len(code_blocks),
            "table_count": len(tables),
        }

    def _extract_headings(self, content: str) -> list[dict[str, Any]]:
        """提取 Markdown 标题。

        Args:
            content: 文件内容

        Returns:
            list: 标题列表，每个元素包含级别和文本
        """
        headings = []
        heading_pattern = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

        for match in heading_pattern.finditer(content):
            level = len(match.group(1))
            text = match.group(2).strip()
            headings.append({"level": level, "text": text})

        return headings

    def _extract_links(self, content: str) -> list[dict[str, str]]:
        """提取 Markdown 链接。

        Args:
            content: 文件内容

        Returns:
            list: 链接列表
        """
        links = []
        link_pattern = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")

        for match in link_pattern.finditer(content):
            links.append({"text": match.group(1), "url": match.group(2)})

        return links

    def _extract_images(self, content: str) -> list[dict[str, str]]:
        """提取 Markdown 图片。

        Args:
            content: 文件内容

        Returns:
            list: 图片列表
        """
        images = []
        image_pattern = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")

        for match in image_pattern.finditer(content):
            images.append({"alt": match.group(1), "url": match.group(2)})

        return images

    def _extract_code_blocks(self, content: str) -> list[dict[str, str]]:
        """提取 Markdown 代码块。

        Args:
            content: 文件内容

        Returns:
            list: 代码块列表
        """
        code_blocks = []
        code_block_pattern = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)

        for match in code_block_pattern.finditer(content):
            code_blocks.append(
                {"language": match.group(1) or "unknown", "code": match.group(2)}
            )

        return code_blocks

    def _extract_tables(self, content: str) -> list[dict[str, Any]]:
        """提取 Markdown 表格。

        Args:
            content: 文件内容

        Returns:
            list: 表格列表
        """
        tables = []
        table_pattern = re.compile(r"(\|.+\|[\r\n]+\|[-:| ]+\|[\r\n]+(?:\|.+\|[\r\n]*)+)", re.MULTILINE)

        for match in table_pattern.finditer(content):
            table_text = match.group(1)
            rows = [row.strip() for row in table_text.split("\n") if row.strip()]
            if len(rows) >= 2:
                header = [cell.strip() for cell in rows[0].split("|") if cell.strip()]
                tables.append({"rows": len(rows) - 1, "columns": len(header)})

        return tables

    def _generate_summary(self, content: str) -> str:
        """生成 Markdown 文件摘要。

        Args:
            content: 文件内容

        Returns:
            str: 摘要文本
        """
        headings = self._extract_headings(content)

        if not headings:
            lines = content.strip().splitlines()
            if lines:
                first_line = lines[0].strip()
                if len(first_line) > 100:
                    return f"Markdown 文件，无标题，首行: {first_line[:100]}..."
                return f"Markdown 文件，无标题，首行: {first_line}"
            return "空的 Markdown 文件"

        title = headings[0]["text"]
        level_counts = {}
        for h in headings:
            level = h["level"]
            level_counts[level] = level_counts.get(level, 0) + 1

        level_summary = ", ".join(
            f"H{level}: {count}个" for level, count in sorted(level_counts.items())
        )

        return f"Markdown 文件，标题: {title}，共 {len(headings)} 个标题 ({level_summary})"