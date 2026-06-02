from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from ..base_parser import BaseParser
from ..models import ParseResult


class ExcelParser(BaseParser):
    """Excel 文件解析器，支持 .xlsx 和 .xls 格式。"""

    SUPPORTED_EXTENSIONS = [".xlsx", ".xls"]

    def __init__(
        self,
        encoding: str | None = None,
        max_rows_per_sheet: int = 1000,
        include_index: bool = False,
    ):
        """初始化 Excel 解析器。

        Args:
            encoding: 文件编码，默认 UTF-8
            max_rows_per_sheet: 每个 Sheet 最大读取行数，默认 1000
            include_index: 是否包含 DataFrame 索引列，默认 False
        """
        super().__init__(encoding)
        self.max_rows_per_sheet = max_rows_per_sheet
        self.include_index = include_index

    def parse(self, file_path: Path) -> ParseResult:
        """解析 Excel 文件。

        Args:
            file_path: 要解析的文件路径

        Returns:
            ParseResult: 包含 Markdown 表格内容、元信息和摘要的解析结果
        """
        try:
            # Determine engine based on file extension
            ext = file_path.suffix.lower()
            if ext == ".xlsx":
                engine = "openpyxl"
            elif ext == ".xls":
                engine = "xlrd"
            else:
                engine = None
            excel_file = pd.ExcelFile(file_path, engine=engine)
        except Exception as e:
            return ParseResult.from_error(f"无法读取 Excel 文件: {e}", file_path=file_path)

        sheet_names = excel_file.sheet_names
        all_content = []
        all_metadata = self._extract_base_metadata(file_path)
        sheet_metadata = []

        for sheet_name in sheet_names:
            try:
                df = pd.read_excel(
                    excel_file,
                    sheet_name=sheet_name,
                    nrows=self.max_rows_per_sheet,
                )
            except Exception as e:
                all_content.append(f"## Sheet: {sheet_name}\n\n")
                all_content.append(f"*读取失败: {e}*\n\n")
                continue

            if df.empty:
                all_content.append(f"## Sheet: {sheet_name}\n\n")
                all_content.append("*空表格*\n\n")
                sheet_metadata.append({
                    "name": sheet_name,
                    "rows": 0,
                    "columns": 0,
                    "column_names": [],
                })
                continue

            sheet_md = self._dataframe_to_markdown(df, sheet_name)
            all_content.append(sheet_md)

            sheet_meta = self._extract_sheet_metadata(df, sheet_name)
            sheet_metadata.append(sheet_meta)

        all_metadata["sheets"] = sheet_metadata
        all_metadata["sheet_count"] = len(sheet_names)
        all_metadata["sheet_names"] = sheet_names

        content = "\n".join(all_content)
        summary = self._generate_summary(sheet_names, sheet_metadata)

        return ParseResult(
            content=content,
            metadata=all_metadata,
            summary=summary,
        )

    def _dataframe_to_markdown(self, df: pd.DataFrame, sheet_name: str) -> str:
        """将 DataFrame 转换为 Markdown 表格格式。

        Args:
            df: pandas DataFrame
            sheet_name: Sheet 名称

        Returns:
            str: Markdown 格式的表格文本
        """
        lines = [f"## Sheet: {sheet_name}", ""]

        column_names = df.columns.tolist()
        cleaned_columns = [str(col) if pd.notna(col) else "" for col in column_names]

        header = "| " + " | ".join(cleaned_columns) + " |"
        separator = "| " + " | ".join(["---"] * len(cleaned_columns)) + " |"

        lines.append(header)
        lines.append(separator)

        for _, row in df.iterrows():
            row_values = []
            for val in row:
                if pd.isna(val):
                    row_values.append("")
                elif isinstance(val, (int, float)):
                    if isinstance(val, float) and val != val:
                        row_values.append("")
                    else:
                        row_values.append(str(val))
                else:
                    row_values.append(str(val).replace("\n", " ").replace("\r", ""))
            lines.append("| " + " | ".join(row_values) + " |")

        lines.append("")
        row_count = len(df)
        col_count = len(df.columns)
        lines.append(f"*共 {row_count} 行 × {col_count} 列*")
        lines.append("")

        return "\n".join(lines)

    def _extract_base_metadata(self, file_path: Path) -> dict[str, Any]:
        """提取 Excel 文件的基础元信息。

        Args:
            file_path: 文件路径

        Returns:
            dict: 基础元信息字典
        """
        stat = file_path.stat()
        return {
            "file_name": file_path.name,
            "file_size": stat.st_size,
            "created_time": stat.st_ctime,
            "modified_time": stat.st_mtime,
            "file_type": "Excel",
        }

    def _extract_sheet_metadata(self, df: pd.DataFrame, sheet_name: str) -> dict[str, Any]:
        """提取单个 Sheet 的元信息。

        Args:
            df: pandas DataFrame
            sheet_name: Sheet 名称

        Returns:
            dict: Sheet 元信息字典
        """
        column_names = [str(col) if pd.notna(col) else "" for col in df.columns.tolist()]
        column_types = {col: str(dtype) for col, dtype in zip(column_names, df.dtypes)}

        return {
            "name": sheet_name,
            "rows": len(df),
            "columns": len(df.columns),
            "column_names": column_names,
            "column_types": column_types,
        }

    def _generate_summary(
        self, sheet_names: list[str], sheet_metadata: list[dict[str, Any]]
    ) -> str:
        """生成 Excel 文件摘要。

        Args:
            sheet_names: Sheet 名称列表
            sheet_metadata: Sheet 元信息列表

        Returns:
            str: 摘要文本
        """
        if not sheet_names:
            return "空 Excel 文件"

        total_rows = sum(meta.get("rows", 0) for meta in sheet_metadata)
        total_cols = max((meta.get("columns", 0) for meta in sheet_metadata), default=0)

        if len(sheet_names) == 1:
            meta = sheet_metadata[0] if sheet_metadata else {}
            return f"Excel 文件，包含 1 个 Sheet「{sheet_names[0]}」，{meta.get('rows', 0)} 行 × {meta.get('columns', 0)} 列"
        else:
            return f"Excel 文件，包含 {len(sheet_names)} 个 Sheet，共 {total_rows} 行数据，最大 {total_cols} 列"