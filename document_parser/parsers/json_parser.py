from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from ..base_parser import BaseParser
from ..models import ParseResult


class JSONParser(BaseParser):
    """JSON 文件解析器，支持格式化输出。"""

    SUPPORTED_EXTENSIONS = [".json"]

    def __init__(
        self,
        encoding: str | None = None,
        output_format: Literal["text", "markdown"] = "text",
        indent: int = 2,
    ):
        """初始化 JSON 解析器。

        Args:
            encoding: 文件编码，默认 UTF-8
            output_format: 输出格式，支持 'text' 或 'markdown'
            indent: JSON 格式化缩进空格数
        """
        super().__init__(encoding)
        self.output_format = output_format
        self.indent = indent

    def parse(self, file_path: Path) -> ParseResult:
        """解析 JSON 文件。

        Args:
            file_path: 要解析的文件路径

        Returns:
            ParseResult: 包含格式化内容、元信息和摘要的解析结果
        """
        raw_content = self._read_file(file_path)

        try:
            json_data = json.loads(raw_content)
        except json.JSONDecodeError as e:
            raise ValueError(f"无效的 JSON 格式: {e}") from e

        metadata = self._extract_metadata(file_path, json_data, raw_content)
        content = self._format_content(json_data)
        summary = self._generate_summary(json_data)

        return ParseResult(
            content=content,
            metadata=metadata,
            summary=summary,
        )

    def _extract_metadata(
        self, file_path: Path, json_data: Any, raw_content: str
    ) -> dict:
        """提取 JSON 文件的元信息。

        Args:
            file_path: 文件路径
            json_data: 解析后的 JSON 数据
            raw_content: 原始文件内容

        Returns:
            dict: 元信息字典
        """
        stat = file_path.stat()

        data_type = type(json_data).__name__
        key_count = 0
        depth = 0

        if isinstance(json_data, dict):
            key_count = len(json_data)
            depth = self._calculate_depth(json_data)
        elif isinstance(json_data, list):
            key_count = len(json_data)
            depth = self._calculate_list_depth(json_data)

        return {
            "file_name": file_path.name,
            "file_size": stat.st_size,
            "created_time": stat.st_ctime,
            "modified_time": stat.st_mtime,
            "data_type": data_type,
            "key_count": key_count,
            "depth": depth,
            "encoding": self.encoding,
        }

    def _calculate_depth(self, data: dict, current_depth: int = 1) -> int:
        """计算字典的嵌套深度。

        Args:
            data: 字典数据
            current_depth: 当前深度

        Returns:
            int: 最大深度
        """
        max_depth = current_depth
        for value in data.values():
            if isinstance(value, dict):
                depth = self._calculate_depth(value, current_depth + 1)
                max_depth = max(max_depth, depth)
        return max_depth

    def _calculate_list_depth(self, data: list, current_depth: int = 1) -> int:
        """计算列表的嵌套深度。

        Args:
            data: 列表数据
            current_depth: 当前深度

        Returns:
            int: 最大深度
        """
        max_depth = current_depth
        for item in data:
            if isinstance(item, dict):
                depth = self._calculate_depth(item, current_depth + 1)
                max_depth = max(max_depth, depth)
            elif isinstance(item, list):
                depth = self._calculate_list_depth(item, current_depth + 1)
                max_depth = max(max_depth, depth)
        return max_depth

    def _format_content(self, json_data: Any) -> str:
        """根据输出格式格式化 JSON 内容。

        Args:
            json_data: 解析后的 JSON 数据

        Returns:
            str: 格式化后的内容
        """
        if self.output_format == "markdown":
            return self._format_as_markdown(json_data)
        else:
            return self._format_as_text(json_data)

    def _format_as_text(self, json_data: Any) -> str:
        """将 JSON 格式化为易读的文本格式。

        Args:
            json_data: 解析后的 JSON 数据

        Returns:
            str: 格式化后的文本
        """
        return json.dumps(json_data, indent=self.indent, ensure_ascii=False)

    def _format_as_markdown(self, json_data: Any) -> str:
        """将 JSON 格式化为 Markdown 格式。

        Args:
            json_data: 解析后的 JSON 数据

        Returns:
            str: 格式化后的 Markdown 文本
        """
        if isinstance(json_data, dict):
            return self._dict_to_markdown(json_data)
        elif isinstance(json_data, list):
            return self._list_to_markdown(json_data)
        else:
            return f"```json\n{json.dumps(json_data, ensure_ascii=False)}\n```"

    def _dict_to_markdown(
        self, data: dict, level: int = 1, prefix: str = ""
    ) -> str:
        """将字典转换为 Markdown 格式。

        Args:
            data: 字典数据
            level: 标题级别
            prefix: 键名前缀

        Returns:
            str: Markdown 格式文本
        """
        lines = []

        for key, value in data.items():
            full_key = f"{prefix}.{key}" if prefix else key

            if isinstance(value, dict):
                lines.append(f"{'#' * level} {key}")
                lines.append("")
                lines.append(self._dict_to_markdown(value, level + 1, full_key))
                lines.append("")
            elif isinstance(value, list):
                lines.append(f"**{key}:**")
                lines.append("")
                lines.append(self._list_to_markdown(value, level + 1))
                lines.append("")
            else:
                lines.append(f"- **{key}:** {self._format_value(value)}")

        return "\n".join(lines)

    def _list_to_markdown(self, data: list, level: int = 1) -> str:
        """将列表转换为 Markdown 格式。

        Args:
            data: 列表数据
            level: 标题级别

        Returns:
            str: Markdown 格式文本
        """
        lines = []

        for i, item in enumerate(data):
            if isinstance(item, dict):
                lines.append(f"{i + 1}. **项目 {i + 1}**")
                lines.append("")
                for key, value in item.items():
                    if isinstance(value, (dict, list)):
                        lines.append(f"   - **{key}:**")
                        lines.append(
                            f"   ```json\n   {json.dumps(value, ensure_ascii=False, indent=2)}\n   ```"
                        )
                    else:
                        lines.append(f"   - **{key}:** {self._format_value(value)}")
                lines.append("")
            elif isinstance(item, list):
                lines.append(f"{i + 1}. {json.dumps(item, ensure_ascii=False)}")
            else:
                lines.append(f"{i + 1}. {self._format_value(item)}")

        return "\n".join(lines)

    def _format_value(self, value: Any) -> str:
        """格式化单个值。

        Args:
            value: 要格式化的值

        Returns:
            str: 格式化后的字符串
        """
        if value is None:
            return "`null`"
        elif isinstance(value, bool):
            return f"`{str(value).lower()}`"
        elif isinstance(value, str):
            if len(value) > 100:
                return f'`"{value[:100]}..."`'
            return f'`"{value}"`'
        elif isinstance(value, (int, float)):
            return f"`{value}`"
        else:
            return f"`{json.dumps(value, ensure_ascii=False)}`"

    def _generate_summary(self, json_data: Any) -> str:
        """生成 JSON 文件摘要。

        Args:
            json_data: 解析后的 JSON 数据

        Returns:
            str: 摘要文本
        """
        data_type = type(json_data).__name__

        if isinstance(json_data, dict):
            keys = list(json_data.keys())[:5]
            keys_str = ", ".join(keys)
            if len(json_data) > 5:
                keys_str += f", ... (共 {len(json_data)} 个键)"
            return f"JSON 对象，包含 {len(json_data)} 个键: {keys_str}"
        elif isinstance(json_data, list):
            return f"JSON 数组，包含 {len(json_data)} 个元素"
        else:
            return f"JSON {data_type}: {json.dumps(json_data, ensure_ascii=False)[:100]}"