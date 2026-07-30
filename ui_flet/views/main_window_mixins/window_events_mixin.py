"""
窗口事件处理 Mixin

负责窗口事件（关闭、最小化）、全局快捷键、主题应用等。
"""
from __future__ import annotations

import flet as ft

from config import get_config
from logger import get_logger
from ui_flet.theme import ThemeManager, DEFAULT_FONT_CONFIG


class WindowEventsMixin:
    """
    窗口事件处理 Mixin

    包含窗口事件处理、快捷键、主题等与窗口本身相关的方法。
    通过 self 访问 MainWindow 的属性（如 self._page, self._logger 等）。
    """

    # ==================================================================
    # 窗口事件处理
    # ==================================================================

    def _on_window_event(self, e) -> None:
        """
        窗口事件处理器

        Args:
            e: 窗口事件对象
        """
        event_type = e.type if hasattr(e, 'type') else None
        if event_type == ft.WindowEventType.CLOSE:
            self._handle_close_request()
        elif event_type == ft.WindowEventType.MINIMIZE:
            self._handle_minimize()

    # ==================== 快捷键处理 ====================

    @staticmethod
    def _build_hotkey_str(e) -> str:
        """从键盘事件构建快捷键字符串（如 'ctrl+enter'）"""
        # 忽略单独的修饰键
        key = e.key.lower()
        if key in ("ctrl", "shift", "alt", "meta", "control"):
            return ""

        modifiers = []
        if e.ctrl:
            modifiers.append("ctrl")
        if e.shift:
            modifiers.append("shift")
        if e.alt:
            modifiers.append("alt")
        if e.meta:
            modifiers.append("meta")

        # 特殊键映射
        key_map = {
            "enter": "enter",
            "escape": "esc",
            "arrowup": "up",
            "arrowdown": "down",
            "arrowleft": "left",
            "arrowright": "right",
            "space": "space",
            "minus": "-",
            "equal": "=",
            "bracketleft": "[",
            "bracketright": "]",
            "semicolon": ";",
            "quote": "'",
            "comma": ",",
            "period": ".",
            "slash": "/",
            "backspace": "backspace",
            "tab": "tab",
        }
        if key in key_map:
            key = key_map[key]

        return "+".join(modifiers + [key])

    def _get_hotkey_value(self, hotkey_id: str) -> str:
        """从配置读取快捷键值，不存在则返回默认值"""
        from ui_flet.settings.hotkey_settings_page import DEFAULT_HOTKEYS
        config = DEFAULT_HOTKEYS.get(hotkey_id)
        if not config:
            return ""
        val = get_config(config["config_key"])
        return (val or config["default"]).lower()

    def _is_modal_open(self) -> bool:
        """检查是否有模态对话框打开（设置页 / 关闭确认框）"""
        if self._settings_dialog and self._settings_dialog.is_open():
            return True
        if hasattr(self, '_close_confirmation_dialog') and self._close_confirmation_dialog:
            if getattr(self._close_confirmation_dialog, 'open', False):
                return True
        return False

    def _on_keyboard_event(self, e) -> None:
        """全局键盘事件处理：根据配置的快捷键执行对应操作"""
        # 如果有模态对话框打开，不处理全局快捷键（避免干扰设置页面等）
        if self._is_modal_open():
            return

        hotkey_str = self._build_hotkey_str(e)
        if not hotkey_str:
            return

        # 读取各快捷键配置
        send_key = self._get_hotkey_value("send_message")
        newline_key = self._get_hotkey_value("newline")
        record_key = self._get_hotkey_value("record")
        new_conv_key = self._get_hotkey_value("new_conversation")
        settings_key = self._get_hotkey_value("settings")

        # 发送消息快捷键
        if hotkey_str == send_key:
            if self._input_area:
                self._input_area.send_message()
            return

        # 换行快捷键：仅对非原生 Enter/Shift+Enter 手动插入换行
        # （原生 Enter/Shift+Enter 由 multiline TextField 自动处理）
        if hotkey_str == newline_key and newline_key not in ("enter", "shift+enter"):
            if self._input_area:
                self._input_area.insert_newline()
            return

        # 录音快捷键
        if hotkey_str == record_key:
            self._toggle_recording()
            return

        # 新建会话快捷键
        if hotkey_str == new_conv_key:
            self._handle_new_conversation()
            return

        # 打开设置快捷键
        if hotkey_str == settings_key:
            self._on_settings_click()
            return

    def _toggle_recording(self) -> None:
        """切换录音状态"""
        try:
            from recorder import get_recorder, is_online_model_loaded

            if not is_online_model_loaded():
                self._logger.warning("流式 ASR 模型未加载，无法录音")
                return

            recorder = get_recorder()
            if recorder.is_recording():
                self.stop_recording()
            else:
                self.start_recording()
        except Exception as e:
            self._logger.exception(f"切换录音失败: {e}")

    def _handle_close_request(self) -> None:
        """处理关闭请求"""
        # 显示确认对话框
        self._show_close_confirmation()

    def _handle_minimize(self) -> None:
        """处理最小化"""
        self._logger.info("窗口最小化")

    def _show_close_confirmation(self) -> None:
        """显示关闭确认对话框"""
        def on_minimize(e):
            """最小化到任务栏"""
            self._page.window.minimized = True
            self._dismiss_close_dialog()
            self._page.update()

        async def on_floating_ball(e):
            """进入悬浮球模式"""
            self._dismiss_close_dialog()
            # 隐藏主窗口
            self._page.window.minimized = True
            self._page.window.visible = False
            self._page.update()
            self._logger.info("进入悬浮球模式")
            # 启动悬浮球（通过调用 main 模块的函数）
            from ui_flet import main as main_module
            if hasattr(main_module, '_start_floating_ball_mode'):
                main_module._start_floating_ball_mode()

        async def on_close(e):
            """直接关闭"""
            self._dismiss_close_dialog()
            self._stop_scheduler()
            self._page.window.prevent_close = False
            # 必须先 update 同步 prevent_close=False 到客户端，
            # 否则 window.close() 触发的关闭会被客户端的旧值(True)阻止
            self._page.update()
            await self._page.window.close()

        # 创建对话框
        self._close_confirmation_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("关闭确认"),
            content=ft.Text("请选择关闭方式："),
            actions=[
                ft.TextButton("最小化到任务栏", on_click=on_minimize),
                ft.TextButton("悬浮球模式", on_click=on_floating_ball),
                ft.TextButton("直接关闭", on_click=on_close),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        self._page.overlay.append(self._close_confirmation_dialog)
        self._close_confirmation_dialog.open = True
        self._page.update()

    def _dismiss_close_dialog(self) -> None:
        """关闭对话框"""
        if hasattr(self, '_close_confirmation_dialog') and self._close_confirmation_dialog:
            self._close_confirmation_dialog.open = False
            self._page.update()

    def _center_window(self) -> None:
        """将窗口居中显示在主显示器上"""
        self._page.window.center()
        # try:
        #     window_width = int(self._page.window.width)
        #     window_height = int(self._page.window.height)
        #     import ctypes
        #     # 获取屏幕工作区（排除任务栏）
        #     user32 = ctypes.windll.user32
        #     work_area = ctypes.wintypes.RECT()
        #     user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(work_area), 0)  # SPI_GETWORKAREA
        #
        #     work_left = work_area.left
        #     work_top = work_area.top
        #     work_right = work_area.right
        #     work_bottom = work_area.bottom
        #
        #     work_width = work_right - work_left
        #     work_height = work_bottom - work_top
        #
        #     x = work_left + (work_width - window_width) // 2
        #     y = work_top + (work_height - window_height) // 2
        #
        #     self._logger.info(
        #         f"窗口已居中: ({x}, {y}), 屏幕: {work_width}x{work_height}"
        #     )
        #
        # except Exception as e:
        #     self._logger.warning(f"居中窗口失败: {e}")
        #     # 使用默认位置（Flet 会自动处理）
        #     pass

    def _apply_theme(self) -> None:
        """应用主题样式"""
        colors = self._theme_manager.get_color_scheme()

        # 设置页面背景色
        self._page.bgcolor = colors.bg_page
        self._logger.info(f"设置页面背景色: {colors.bg_page}")

        # 设置全局主题字体，并统一按钮文字字重为 W_500
        self._page.theme = ft.Theme(
            font_family=DEFAULT_FONT_CONFIG.family,
            text_theme=ft.TextTheme(
                label_large=ft.TextStyle(
                    font_family=DEFAULT_FONT_CONFIG.family,
                    weight=ft.FontWeight.W_500,
                ),
            ),
        )
        self._logger.info(f"设置全局字体: {DEFAULT_FONT_CONFIG.family}")

        # 根据主题设置 Flet 主题
        if self._theme_manager.current_theme.value == "dark":
            self._page.theme_mode = ft.ThemeMode.DARK
        else:
            self._page.theme_mode = ft.ThemeMode.LIGHT
        self._logger.info(f"设置主题模式: {self._page.theme_mode}")
