"""
Flet 主题配置模块

定义颜色、字体、间距等样式配置，并提供主题管理功能。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal

from config import get_config, set_config


class ThemeMode(str, Enum):
    """主题模式"""
    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "system"


# ==================== 颜色方案 ====================

@dataclass(frozen=True)
class ColorScheme:
    """颜色方案"""
    # 主色调
    primary: str
    primary_hover: str
    primary_soft: str
    primary_border: str

    # 背景色
    bg_page: str
    surface: str
    surface_hover: str

    # 边框色
    border: str
    border_focus: str

    # 文本色
    text: str
    text_muted: str
    text_on_primary: str

    # 状态色
    success: str
    success_soft: str
    warning: str
    warning_soft: str
    error: str
    error_soft: str

    # 其他
    tab_close_x: str


# 亮色主题颜色方案
LIGHT_COLOR_SCHEME = ColorScheme(
    # 主色调（蓝色系）
    primary="#2563eb",
    primary_hover="#1d4ed8",
    primary_soft="#e8f3ff",
    primary_border="#bfdbfe",

    # 背景色
    bg_page="#f5f7fa",
    surface="#ffffff",
    surface_hover="#f9fafb",

    # 边框色
    border="#e5e7eb",
    border_focus="#93c5fd",

    # 文本色
    text="#374151",
    text_muted="#6b7280",
    text_on_primary="#ffffff",

    # 状态色
    success="#10b981",
    success_soft="#d1fae5",
    warning="#f59e0b",
    warning_soft="#fef3c7",
    error="#ef4444",
    error_soft="#fee2e2",

    # 其他
    tab_close_x="#64748b",
)

# 暗色主题颜色方案
DARK_COLOR_SCHEME = ColorScheme(
    # 主色调（蓝色系）
    primary="#3b82f6",
    primary_hover="#60a5fa",
    primary_soft="#1e3a5f",
    primary_border="#2563eb",

    # 背景色
    bg_page="#111827",
    surface="#1f2937",
    surface_hover="#374151",

    # 边框色
    border="#374151",
    border_focus="#3b82f6",

    # 文本色
    text="#e5e7eb",
    text_muted="#9ca3af",
    text_on_primary="#ffffff",

    # 状态色
    success="#10b981",
    success_soft="#064e3b",
    warning="#f59e0b",
    warning_soft="#78350f",
    error="#ef4444",
    error_soft="#7f1d1d",

    # 其他
    tab_close_x="#94a3b8",
)


# ==================== 字体配置 ====================

@dataclass(frozen=True)
class FontConfig:
    """字体配置"""
    # 字体族
    family: str
    family_mono: str

    # 字体大小
    size_xs: float  # 12px
    size_sm: float  # 14px
    size_md: float  # 16px
    size_lg: float  # 18px
    size_xl: float  # 20px
    size_2xl: float  # 24px

    # 字体粗细
    weight_light: int  # 300
    weight_normal: int  # 400
    weight_medium: int  # 500
    weight_semibold: int  # 600
    weight_bold: int  # 700


# 默认字体配置
DEFAULT_FONT_CONFIG = FontConfig(
    # 字体族
    family="system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif",
    family_mono="'Consolas', 'Monaco', 'Courier New', monospace",

    # 字体大小
    size_xs=12.0,
    size_sm=14.0,
    size_md=16.0,
    size_lg=18.0,
    size_xl=20.0,
    size_2xl=24.0,

    # 字体粗细
    weight_light=300,
    weight_normal=400,
    weight_medium=500,
    weight_semibold=600,
    weight_bold=700,
)


# ==================== 间距配置 ====================

@dataclass(frozen=True)
class SpacingConfig:
    """间距配置"""
    # 边距（像素）
    xs: float  # 4px
    sm: float  # 8px
    md: float  # 12px
    lg: float  # 16px
    xl: float  # 24px
    xxl: float  # 32px

    # 圆角（像素）
    radius_sm: float  # 4px
    radius_md: float  # 8px
    radius_lg: float  # 12px
    radius_xl: float  # 16px


# 默认间距配置
DEFAULT_SPACING_CONFIG = SpacingConfig(
    # 边距
    xs=4.0,
    sm=8.0,
    md=12.0,
    lg=16.0,
    xl=24.0,
    xxl=32.0,

    # 圆角
    radius_sm=4.0,
    radius_md=8.0,
    radius_lg=12.0,
    radius_xl=16.0,
)


# ==================== 主题管理器 ====================

class ThemeManager:
    """
    主题管理器

    管理当前主题状态，提供主题切换和颜色获取功能。
    使用单例模式确保全局一致性。
    """

    _instance: ThemeManager | None = None

    def __new__(cls) -> ThemeManager:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._current_theme: ThemeMode = ThemeMode.SYSTEM
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._load_theme_preference()

    def _load_theme_preference(self) -> None:
        """从配置文件加载主题偏好"""
        theme_str = get_config("UI_THEME_MODE")
        if theme_str:
            try:
                self._current_theme = ThemeMode(theme_str.lower())
            except ValueError:
                self._current_theme = ThemeMode.SYSTEM
        else:
            self._current_theme = ThemeMode.SYSTEM

    def _save_theme_preference(self) -> None:
        """保存主题偏好到配置文件"""
        set_config("UI_THEME_MODE", self._current_theme.value)

    @property
    def current_theme(self) -> ThemeMode:
        """获取当前主题模式"""
        return self._current_theme

    def set_theme(self, theme: ThemeMode | str) -> None:
        """
        设置主题模式

        Args:
            theme: 主题模式（light/dark/system）
        """
        if isinstance(theme, str):
            theme = ThemeMode(theme.lower())
        self._current_theme = theme
        self._save_theme_preference()

    def toggle_theme(self) -> None:
        """
        切换主题（亮色 <-> 暗色）

        如果当前是系统主题，则切换到亮色主题。
        """
        if self._current_theme == ThemeMode.LIGHT:
            self.set_theme(ThemeMode.DARK)
        else:
            self.set_theme(ThemeMode.LIGHT)

    def get_color_scheme(self, theme: ThemeMode | None = None) -> ColorScheme:
        """
        获取颜色方案

        Args:
            theme: 主题模式，如果为 None 则使用当前主题

        Returns:
            对应主题的颜色方案
        """
        if theme is None:
            theme = self._current_theme

        # 对于系统主题，默认返回亮色方案
        # 实际应用中应该检测系统主题，这里简化处理
        if theme == ThemeMode.DARK:
            return DARK_COLOR_SCHEME
        else:
            return LIGHT_COLOR_SCHEME

    def get_color(self, color_name: str, theme: ThemeMode | None = None) -> str:
        """
        获取指定颜色的值

        Args:
            color_name: 颜色名称（如 "primary", "bg_page"）
            theme: 主题模式，如果为 None 则使用当前主题

        Returns:
            颜色值（十六进制字符串）

        Raises:
            AttributeError: 如果颜色名称不存在
        """
        color_scheme = self.get_color_scheme(theme)
        return getattr(color_scheme, color_name)

    @classmethod
    def get_instance(cls) -> ThemeManager:
        """获取主题管理器实例"""
        return cls()


# ==================== 便捷函数 ====================

def get_theme_manager() -> ThemeManager:
    """获取主题管理器实例"""
    return ThemeManager.get_instance()


def get_color(color_name: str, theme: ThemeMode | None = None) -> str:
    """
    获取指定颜色的值

    Args:
        color_name: 颜色名称
        theme: 主题模式

    Returns:
        颜色值
    """
    return get_theme_manager().get_color(color_name, theme)


def get_current_theme() -> ThemeMode:
    """获取当前主题模式"""
    return get_theme_manager().current_theme


def toggle_theme() -> None:
    """切换主题"""
    get_theme_manager().toggle_theme()


def set_theme(theme: ThemeMode | str) -> None:
    """设置主题"""
    get_theme_manager().set_theme(theme)


# ==================== 导出常量（兼容原有代码） ====================

# 默认导出亮色主题的颜色，便于快速使用
PRIMARY = LIGHT_COLOR_SCHEME.primary
PRIMARY_HOVER = LIGHT_COLOR_SCHEME.primary_hover
PRIMARY_SOFT = LIGHT_COLOR_SCHEME.primary_soft
PRIMARY_BORDER = LIGHT_COLOR_SCHEME.primary_border
BG_PAGE = LIGHT_COLOR_SCHEME.bg_page
SURFACE = LIGHT_COLOR_SCHEME.surface
BORDER = LIGHT_COLOR_SCHEME.border
TEXT = LIGHT_COLOR_SCHEME.text
TEXT_MUTED = LIGHT_COLOR_SCHEME.text_muted
SUCCESS = LIGHT_COLOR_SCHEME.success
WARNING = LIGHT_COLOR_SCHEME.warning
ERROR = LIGHT_COLOR_SCHEME.error
TAB_CLOSE_X = LIGHT_COLOR_SCHEME.tab_close_x