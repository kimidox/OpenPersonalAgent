"""hotkey 工具处理器

包含1个Handler类:
- SendHotkeyHandler
"""
from __future__ import annotations

from .base import ToolHandler
from ..context import ToolContext
from . import register_handler


class SendHotkeyHandler(ToolHandler):
    """发送热键工具处理器"""

    @property
    def name(self) -> str:
        """返回工具名称"""
        return "send_hotkey"

    def execute(self, args: dict, ctx: ToolContext, registry) -> str:
        """发送热键组合到系统，支持指定目标窗口

        Args:
            args: 工具参数字典，支持 keys、target_window
            ctx: ToolContext 执行上下文
            registry: 工具注册表

        Returns:
            工具执行结果的字符串
        """
        keys = args.get("keys", "")
        target_window = args.get("target_window", None)

        if not keys:
            return "错误: 缺少 keys 参数"

        try:
            import time

            # 键名映射表（将用户输入的键名转换为pyautogui/pydirectinput支持的键名）
            key_mapping = {
                "ctrl": "ctrl",
                "alt": "alt",
                "shift": "shift",
                "win": "win",
                "enter": "enter",
                "esc": "esc",
                "escape": "esc",
                "tab": "tab",
                "backspace": "backspace",
                "delete": "delete",
                "del": "delete",
                "insert": "insert",
                "home": "home",
                "end": "end",
                "pageup": "pageup",
                "pagedown": "pagedown",
                "pgup": "pageup",
                "pgdn": "pagedown",
                "f1": "f1",
                "f2": "f2",
                "f3": "f3",
                "f4": "f4",
                "f5": "f5",
                "f6": "f6",
                "f7": "f7",
                "f8": "f8",
                "f9": "f9",
                "f10": "f10",
                "f11": "f11",
                "f12": "f12",
                "up": "up",
                "down": "down",
                "left": "left",
                "right": "right",
                "space": "space",
                "printscreen": "printscreen",
                "prtsc": "printscreen",
                "pause": "pause",
                "capslock": "capslock",
                "numlock": "numlock",
                "scrolllock": "scrolllock",
            }

            # 解析热键组合
            key_parts = keys.lower().split("+")
            mapped_keys = []
            for part in key_parts:
                part = part.strip()
                mapped_key = key_mapping.get(part, part)
                mapped_keys.append(mapped_key)

            # 如果指定了目标窗口，先激活该窗口
            if target_window:
                try:
                    import ctypes
                    user32 = ctypes.windll.user32

                    # 查找窗口
                    hwnd = user32.FindWindowW(None, target_window)
                    if hwnd:
                        # 激活窗口
                        user32.SetForegroundWindow(hwnd)
                        time.sleep(0.3)  # 等待窗口激活
                    else:
                        return f"警告: 未找到窗口 '{target_window}'，热键将发送到当前焦点窗口"
                except Exception as e:
                    return f"警告: 激活窗口失败: {e}，热键将发送到当前焦点窗口"

            # 发送热键
            # 尝试使用 pyautogui（如果已安装）
            try:
                import pyautogui

                # pyautogui 的 hotkey 函数可以直接接收多个键名
                if len(mapped_keys) == 1:
                    pyautogui.press(mapped_keys[0])
                else:
                    pyautogui.hotkey(*mapped_keys)

                time.sleep(0.1)  # 等待热键生效
                return f"已发送热键: {keys}\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"

            except ImportError:
                # 如果 pyautogui 未安装，使用 ctypes 直接调用 Win32 API
                try:
                    import ctypes
                    from ctypes import wintypes

                    user32 = ctypes.windll.user32

                    # 虚拟键码映射
                    vk_codes = {
                        "ctrl": 0x11,  # VK_CONTROL
                        "alt": 0x12,   # VK_MENU
                        "shift": 0x10, # VK_SHIFT
                        "win": 0x5B,   # VK_LWIN
                        "enter": 0x0D, # VK_RETURN
                        "esc": 0x1B,   # VK_ESCAPE
                        "tab": 0x09,   # VK_TAB
                        "backspace": 0x08, # VK_BACK
                        "delete": 0x2E,    # VK_DELETE
                        "insert": 0x2D,    # VK_INSERT
                        "home": 0x24,      # VK_HOME
                        "end": 0x23,       # VK_END
                        "pageup": 0x21,    # VK_PRIOR
                        "pagedown": 0x22,  # VK_NEXT
                        "f1": 0x70,
                        "f2": 0x71,
                        "f3": 0x72,
                        "f4": 0x73,
                        "f5": 0x74,
                        "f6": 0x75,
                        "f7": 0x76,
                        "f8": 0x77,
                        "f9": 0x78,
                        "f10": 0x79,
                        "f11": 0x7A,
                        "f12": 0x7B,
                        "up": 0x26,    # VK_UP
                        "down": 0x28,  # VK_DOWN
                        "left": 0x25,  # VK_LEFT
                        "right": 0x27, # VK_RIGHT
                        "space": 0x20, # VK_SPACE
                        "printscreen": 0x2A, # VK_SNAPSHOT
                        "pause": 0x13,       # VK_PAUSE
                        "capslock": 0x14,    # VK_CAPITAL
                        "numlock": 0x90,     # VK_NUMLOCK
                    }

                    # 获取虚拟键码
                    vk_list = []
                    for key in mapped_keys:
                        vk = vk_codes.get(key)
                        if vk:
                            vk_list.append(vk)
                        else:
                            # 对于普通字符键，使用 VkKeyScan
                            vk = user32.VkKeyScanW(ord(key.upper())) & 0xFF
                            vk_list.append(vk)

                    # 按下所有键
                    for vk in vk_list:
                        user32.keybd_event(vk, 0, 0, 0)  # KEYDOWN
                        time.sleep(0.05)

                    # 释放所有键（反向顺序）
                    for vk in reversed(vk_list):
                        user32.keybd_event(vk, 0, 2, 0)  # KEYUP
                        time.sleep(0.05)

                    return f"已发送热键: {keys}\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"

                except Exception as e:
                    return f"错误: 发送热键失败: {e}"

        except Exception as e:
            return f"错误: 发送热键失败: {e}"


# 注册 Handler
register_handler(SendHotkeyHandler())
