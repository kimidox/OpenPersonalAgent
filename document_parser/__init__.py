from __future__ import annotations

from .base_parser import BaseParser
from .file_storage import FileInfo, FileStorage
from .models import ParseResult
from .parser_factory import ParserFactory, get_parser, parse_file
from .parsers import AudioParser, ExcelParser, ImageParser, JSONParser, MarkdownParser, PDFParser, TextParser, WordParser

ParserFactory.register(TextParser)
ParserFactory.register(JSONParser)
ParserFactory.register(MarkdownParser)
ParserFactory.register(WordParser)
ParserFactory.register(PDFParser)
ParserFactory.register(ExcelParser)
ParserFactory.register(AudioParser)
ParserFactory.register(ImageParser)

__all__ = [
    "BaseParser",
    "ParseResult",
    "ParserFactory",
    "FileStorage",
    "FileInfo",
    "get_parser",
    "parse_file",
    "TextParser",
    "JSONParser",
    "MarkdownParser",
    "WordParser",
    "PDFParser",
    "ExcelParser",
    "AudioParser",
    "ImageParser",
]