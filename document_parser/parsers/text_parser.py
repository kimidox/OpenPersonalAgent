from __future__ import annotations

import os
from pathlib import Path

from ..base_parser import BaseParser
from ..models import ParseResult


class TextParser(BaseParser):
    """纯文本文件解析器。"""

    SUPPORTED_EXTENSIONS = [".txt"]

    def parse(self, file_path: Path) -> ParseResult:
        """解析纯文本文件。

        Args:
            file_path: 要解析的文件路径

        Returns:
            ParseResult: 包含文本内容、元信息和摘要的解析结果
        """
        content = self._read_file(file_path)

        metadata = self._extract_metadata(file_path, content)
        summary = self._generate_summary(content)

        return ParseResult(
            content=content,
            metadata=metadata,
            summary=summary,
        )

    def _extract_metadata(self, file_path: Path, content: str) -> dict:
        """提取文本文件的元信息。

        Args:
            file_path: 文件路径
            content: 文件内容

        Returns:
            dict: 元信息字典
        """
        stat = file_path.stat()

        lines = content.splitlines()
        word_count = len(content.split())
        char_count = len(content)
        line_count = len(lines)

        return {
            "file_name": file_path.name,
            "file_size": stat.st_size,
            "created_time": stat.st_ctime,
            "modified_time": stat.st_mtime,
            "line_count": line_count,
            "word_count": word_count,
            "char_count": char_count,
            "encoding": self.encoding,
        }

    def _generate_summary(self, content: str) -> str:
        """生成文本摘要。

        Args:
            content: 文件内容

        Returns:
            str: 摘要文本
        """
        lines = content.strip().splitlines()
        if not lines:
            return "空文件"

        first_line = lines[0].strip()
        if len(first_line) > 100:
            return f"文本文件，首行内容: {first_line[:100]}..."
        elif len(lines) == 1:
            return f"单行文本: {first_line}"
        else:
            return f"文本文件，共 {len(lines)} 行，首行: {first_line}"