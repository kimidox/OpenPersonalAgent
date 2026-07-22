from __future__ import annotations

from pathlib import Path
from typing import Any

from ..base_parser import BaseParser
from ..models import ParseResult


class PDFParser(BaseParser):
    """PDF 文档解析器（使用 pdfplumber）。"""

    SUPPORTED_EXTENSIONS = [".pdf"]

    def parse(self, file_path: Path) -> ParseResult:
        """解析 PDF 文档。

        Args:
            file_path: 要解析的文件路径

        Returns:
            ParseResult: 包含内容、元信息和摘要的解析结果
        """
        try:
            import pdfplumber
        except ImportError:
            return ParseResult.from_error(
                "缺少依赖: pdfplumber。请运行 'pip install pdfplumber' 安装。",
                file_path=file_path,
            )

        try:
            pdf = pdfplumber.open(str(file_path))
        except Exception as e:
            return ParseResult.from_error(f"无法打开 PDF 文档: {e}", file_path=file_path)

        try:
            content_parts = []
            metadata = self._extract_metadata(file_path, pdf)

            for page_num, page in enumerate(pdf.pages, start=1):
                page_content = self._process_page(page, page_num)
                if page_content:
                    content_parts.append(page_content)

            content = "\n\n".join(content_parts)

            summary = self._generate_summary(pdf, content)

            return ParseResult(
                content=content,
                metadata=metadata,
                summary=summary,
            )
        finally:
            pdf.close()

    def _process_page(self, page, page_num: int) -> str:
        """处理单个 PDF 页面。

        Args:
            page: pdfplumber 页面对象
            page_num: 页码

        Returns:
            str: 处理后的页面内容
        """
        parts = []

        parts.append(f"--- 第 {page_num} 页 ---\n")

        text = page.extract_text()
        if text:
            text = self._clean_text(text)
            if text.strip():
                parts.append(text)

        tables = page.extract_tables()
        if tables:
            for table in tables:
                table_md = self._process_table(table)
                if table_md:
                    parts.append("\n" + table_md)

        return "\n".join(parts) if parts else ""

    def _clean_text(self, text: str) -> str:
        """清理提取的文本。

        Args:
            text: 原始文本

        Returns:
            str: 清理后的文本
        """
        lines = text.split("\n")
        cleaned_lines = []
        for line in lines:
            line = line.strip()
            if line:
                cleaned_lines.append(line)
        return "\n".join(cleaned_lines)

    def _process_table(self, table: list[list[str | None]]) -> str:
        """将表格转换为 Markdown 格式。

        Args:
            table: 表格数据（二维列表）

        Returns:
            str: Markdown 格式的表格
        """
        if not table or not table[0]:
            return ""

        rows_data = []
        for row in table:
            cells = []
            for cell in row:
                if cell is None:
                    cell_text = ""
                else:
                    cell_text = str(cell).strip().replace("\n", " ").replace("|", "\\|")
                cells.append(cell_text)
            rows_data.append(cells)

        if not rows_data:
            return ""

        max_cols = max(len(row) for row in rows_data)
        normalized_rows = []
        for row in rows_data:
            while len(row) < max_cols:
                row.append("")
            normalized_rows.append(row)

        header = normalized_rows[0]
        body = normalized_rows[1:] if len(normalized_rows) > 1 else []

        md_lines = []
        md_lines.append("| " + " | ".join(header) + " |")
        md_lines.append("| " + " | ".join(["---"] * max_cols) + " |")

        for row in body:
            if any(cell.strip() for cell in row):
                md_lines.append("| " + " | ".join(row) + " |")

        return "\n".join(md_lines) + "\n"

    def _extract_metadata(self, file_path: Path, pdf) -> dict[str, Any]:
        """提取 PDF 文档的元信息。

        Args:
            file_path: 文件路径
            pdf: pdfplumber PDF 对象

        Returns:
            dict: 元信息字典
        """
        stat = file_path.stat()

        metadata = {
            "content_type": "text",
            "file_name": file_path.name,
            "file_size": stat.st_size,
            "created_time": stat.st_ctime,
            "modified_time": stat.st_mtime,
            "page_count": len(pdf.pages),
        }

        if pdf.metadata:
            pdf_meta = pdf.metadata

            if pdf_meta.get("Title"):
                metadata["pdf_title"] = pdf_meta["Title"]
            if pdf_meta.get("Author"):
                metadata["pdf_author"] = pdf_meta["Author"]
            if pdf_meta.get("Subject"):
                metadata["pdf_subject"] = pdf_meta["Subject"]
            if pdf_meta.get("Keywords"):
                metadata["pdf_keywords"] = pdf_meta["Keywords"]
            if pdf_meta.get("Creator"):
                metadata["pdf_creator"] = pdf_meta["Creator"]
            if pdf_meta.get("Producer"):
                metadata["pdf_producer"] = pdf_meta["Producer"]
            if pdf_meta.get("CreationDate"):
                metadata["pdf_created"] = pdf_meta["CreationDate"]
            if pdf_meta.get("ModDate"):
                metadata["pdf_modified"] = pdf_meta["ModDate"]

        total_chars = 0
        total_words = 0
        total_tables = 0

        for page in pdf.pages:
            text = page.extract_text() or ""
            total_chars += len(text)
            total_words += len(text.split())
            tables = page.extract_tables()
            if tables:
                total_tables += len(tables)

        metadata["char_count"] = total_chars
        metadata["word_count"] = total_words
        metadata["table_count"] = total_tables

        return metadata

    def _generate_summary(self, pdf, content: str) -> str:
        """生成 PDF 文档摘要。

        Args:
            pdf: pdfplumber PDF 对象
            content: 解析后的内容

        Returns:
            str: 摘要文本
        """
        page_count = len(pdf.pages)

        title = None
        if pdf.metadata and pdf.metadata.get("Title"):
            title = pdf.metadata["Title"]

        if title:
            return f"PDF 文档，标题: {title}，共 {page_count} 页"
        else:
            first_page_text = ""
            if pdf.pages:
                first_page = pdf.pages[0]
                text = first_page.extract_text() or ""
                first_page_text = text.strip()[:100]

            if first_page_text:
                return f"PDF 文档，无标题，首段: {first_page_text}...，共 {page_count} 页"
            return f"PDF 文档，共 {page_count} 页"