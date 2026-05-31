from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from .base_parser import BaseParser, ParseResult


class ParserFactory:
    """
    解析器工厂类。

    根据文件扩展名返回对应的解析器实例。
    使用注册机制，支持动态注册新的解析器。
    """

    _parsers: dict[str, type[BaseParser]] = {}
    _instances: dict[str, BaseParser] = {}

    @classmethod
    def register(cls, parser_class: type[BaseParser]) -> None:
        """
        注册解析器类。

        参数：
            parser_class: 要注册的解析器类
        """
        instance = parser_class()
        supported_exts = getattr(parser_class, 'SUPPORTED_EXTENSIONS', [])
        for ext in supported_exts:
            ext_lower = ext.lower().lstrip(".")
            cls._parsers[ext_lower] = parser_class
            cls._instances[ext_lower] = instance

    @classmethod
    def register_with_config(cls, parser_class: type[BaseParser], config: dict[str, Any]) -> None:
        """
        注册解析器类并使用指定配置。

        参数：
            parser_class: 要注册的解析器类
            config: 解析器配置
        """
        instance = parser_class(config=config)
        for ext in parser_class.supported_extensions:
            ext_lower = ext.lower()
            cls._parsers[ext_lower] = parser_class
            cls._instances[ext_lower] = instance

    @classmethod
    def get_parser(cls, file_path: Path | str) -> Optional[BaseParser]:
        """
        根据文件扩展名获取对应的解析器实例。

        参数：
            file_path: 文件路径或文件扩展名

        返回：
            对应的解析器实例，如果没有找到则返回 None
        """
        path = Path(file_path) if isinstance(file_path, str) else file_path
        extension = path.suffix.lower().lstrip(".")

        return cls._instances.get(extension)

    @classmethod
    def get_parser_by_extension(cls, extension: str) -> Optional[BaseParser]:
        """
        根据文件扩展名获取对应的解析器实例。

        参数：
            extension: 文件扩展名（可含或不含点号）

        返回：
            对应的解析器实例，如果没有找到则返回 None
        """
        ext = extension.lower().lstrip(".")
        return cls._instances.get(ext)

    @classmethod
    def parse(cls, file_path: Path | str) -> ParseResult:
        """
        解析指定文件。

        自动根据文件扩展名选择合适的解析器进行解析。

        参数：
            file_path: 要解析的文件路径

        返回：
            ParseResult 对象
        """
        path = Path(file_path) if isinstance(file_path, str) else file_path

        parser = cls.get_parser(path)
        if parser is None:
            extension = path.suffix.lower().lstrip(".")
            return ParseResult.from_error(
                f"不支持的文件类型: {extension}",
                file_path=path,
            )

        validation_error = parser.validate_file(path)
        if validation_error:
            return ParseResult.from_error(validation_error, file_path=path)

        return parser.parse(path)

    @classmethod
    def get_supported_extensions(cls) -> list[str]:
        """获取所有已注册支持的文件扩展名列表。"""
        return list(cls._parsers.keys())

    @classmethod
    def is_supported(cls, file_path: Path | str) -> bool:
        """
        检查文件是否支持解析。

        参数：
            file_path: 文件路径

        返回：
            是否支持解析
        """
        path = Path(file_path) if isinstance(file_path, str) else file_path
        extension = path.suffix.lower().lstrip(".")
        return extension in cls._parsers

    @classmethod
    def clear(cls) -> None:
        """清除所有已注册的解析器（主要用于测试）。"""
        cls._parsers.clear()
        cls._instances.clear()


def get_parser(file_path: Path | str) -> Optional[BaseParser]:
    """
    便捷函数：获取文件对应的解析器。

    参数：
        file_path: 文件路径

    返回：
        对应的解析器实例，如果没有找到则返回 None
    """
    return ParserFactory.get_parser(file_path)


def parse_file(file_path: Path | str) -> ParseResult:
    """
    便捷函数：解析文件。

    参数：
        file_path: 文件路径

    返回：
        ParseResult 对象
    """
    return ParserFactory.parse(file_path)