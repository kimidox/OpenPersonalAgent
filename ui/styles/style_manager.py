from __future__ import annotations

import re
from pathlib import Path
from typing import Final


_SECTION_PATTERN: Final = re.compile(r"/\* === section:(\w+) === \*/")


def load_style_sections(css_path: Path) -> dict[str, str]:
    if not css_path.exists():
        return {}
    raw = css_path.read_text(encoding="utf-8")
    parts = _SECTION_PATTERN.split(raw)
    if len(parts) < 2:
        return {}
    out: dict[str, str] = {}
    for i in range(1, len(parts), 2):
        key = parts[i]
        body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        out[key] = body
    return out


class StyleManager:
    _instance: StyleManager | None = None
    _styles: dict[str, str]

    def __new__(cls) -> StyleManager:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._styles = {}
        return cls._instance

    @classmethod
    def load_from_file(cls, css_path: Path) -> None:
        instance = cls()
        instance._styles = load_style_sections(css_path)

    @classmethod
    def get_style(cls, section_name: str) -> str:
        instance = cls()
        return instance._styles.get(section_name, "")

    @classmethod
    def get_all_styles(cls) -> dict[str, str]:
        instance = cls()
        return instance._styles.copy()

    @classmethod
    def has_style(cls, section_name: str) -> bool:
        instance = cls()
        return section_name in instance._styles

    @classmethod
    def section_names(cls) -> list[str]:
        instance = cls()
        return list(instance._styles.keys())
