from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from .models import ParseResult


class BaseParser(ABC):
    """文档解析器基类。"""

    SUPPORTED_EXTENSIONS: list[str] = []

    def __init__(self, encoding: str | None = None):
        self.encoding = encoding or "utf-8"

    @property
    def supported_extensions(self) -> list[str]:
        """获取支持的文件扩展名列表（小写，不含点号）。

        Returns:
            list[str]: 支持的扩展名列表
        """
        return [ext.lower().lstrip(".") for ext in self.SUPPORTED_EXTENSIONS]

    @abstractmethod
    def parse(self, file_path: Path) -> ParseResult:
        """解析文件并返回解析结果。

        Args:
            file_path: 要解析的文件路径

        Returns:
            ParseResult: 包含内容、元信息和摘要的解析结果
        """
        pass

    def validate_file(self, file_path: Path) -> str | None:
        """验证文件是否可以解析。

        Args:
            file_path: 文件路径

        Returns:
            str | None: 如果验证失败返回错误信息，否则返回 None
        """
        if not file_path.exists():
            return f"文件不存在: {file_path}"

        if not file_path.is_file():
            return f"路径不是文件: {file_path}"

        extension = file_path.suffix.lower().lstrip(".")
        if extension not in self.supported_extensions:
            return f"不支持的文件类型: {file_path.suffix}"

        return None

    def supports_extension(self, extension: str) -> bool:
        """检查是否支持指定的文件扩展名。

        Args:
            extension: 文件扩展名（包含点号，如 '.txt'）

        Returns:
            bool: 是否支持该扩展名
        """
        return extension.lower() in [ext.lower() for ext in self.SUPPORTED_EXTENSIONS]

    def _detect_encoding(self, file_path: Path) -> str:
        """检测文件编码。

        Args:
            file_path: 文件路径

        Returns:
            str: 检测到的编码名称
        """
        try:
            import chardet

            with open(file_path, "rb") as f:
                raw_data = f.read(10000)
                result = chardet.detect(raw_data)
                return result.get("encoding", "utf-8") or "utf-8"
        except ImportError:
            return "utf-8"

    def _read_file(self, file_path: Path) -> str:
        """读取文件内容，处理编码问题。

        Args:
            file_path: 文件路径

        Returns:
            str: 文件内容

        Raises:
            FileNotFoundError: 文件不存在
            UnicodeDecodeError: 编码错误
        """
        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        try:
            with open(file_path, "r", encoding=self.encoding) as f:
                return f.read()
        except UnicodeDecodeError:
            detected_encoding = self._detect_encoding(file_path)
            with open(file_path, "r", encoding=detected_encoding) as f:
                return f.read()