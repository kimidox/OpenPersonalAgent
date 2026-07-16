from __future__ import annotations

from pathlib import Path

from .color_scheme import (
    BG_PAGE,
    BORDER,
    ColorScheme,
    DANGER,
    DEFAULT_COLOR_SCHEME,
    PRIMARY,
    PRIMARY_BORDER,
    PRIMARY_HOVER,
    PRIMARY_SOFT,
    SURFACE,
    TAB_CLOSE_X,
    TEXT,
    TEXT_MUTED,
)
from .style_manager import StyleManager, load_style_sections

_STYLES_DIR = Path(__file__).parent
CSS_FILE_NAME = "ui_skill_agent_styles.css"


def get_styles_css_path() -> Path:
    return _STYLES_DIR / CSS_FILE_NAME


def initialize_styles() -> None:
    css_path = get_styles_css_path()
    StyleManager.load_from_file(css_path)


__all__ = [
    "ColorScheme",
    "DEFAULT_COLOR_SCHEME",
    "PRIMARY",
    "PRIMARY_HOVER",
    "PRIMARY_SOFT",
    "PRIMARY_BORDER",
    "BG_PAGE",
    "SURFACE",
    "BORDER",
    "TEXT",
    "TEXT_MUTED",
    "DANGER",
    "TAB_CLOSE_X",
    "StyleManager",
    "load_style_sections",
    "get_styles_css_path",
    "initialize_styles",
]
