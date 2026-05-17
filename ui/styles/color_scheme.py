from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ColorScheme:
    primary: str
    primary_hover: str
    primary_soft: str
    primary_border: str
    bg_page: str
    surface: str
    border: str
    text: str
    text_muted: str
    danger: str
    tab_close_x: str


DEFAULT_COLOR_SCHEME = ColorScheme(
    primary="#2563eb",
    primary_hover="#1d4ed8",
    primary_soft="#e8f3ff",
    primary_border="#bfdbfe",
    bg_page="#f5f7fa",
    surface="#ffffff",
    border="#e5e7eb",
    text="#374151",
    text_muted="#6b7280",
    danger="#ef4444",
    tab_close_x="#64748b",
)


PRIMARY = DEFAULT_COLOR_SCHEME.primary
PRIMARY_HOVER = DEFAULT_COLOR_SCHEME.primary_hover
PRIMARY_SOFT = DEFAULT_COLOR_SCHEME.primary_soft
PRIMARY_BORDER = DEFAULT_COLOR_SCHEME.primary_border
BG_PAGE = DEFAULT_COLOR_SCHEME.bg_page
SURFACE = DEFAULT_COLOR_SCHEME.surface
BORDER = DEFAULT_COLOR_SCHEME.border
TEXT = DEFAULT_COLOR_SCHEME.text
TEXT_MUTED = DEFAULT_COLOR_SCHEME.text_muted
DANGER = DEFAULT_COLOR_SCHEME.danger
TAB_CLOSE_X = DEFAULT_COLOR_SCHEME.tab_close_x
