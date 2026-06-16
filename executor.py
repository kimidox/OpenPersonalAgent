import ctypes
import os
import sys
import time
from ctypes import wintypes

import pyautogui
import subprocess
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
import base64

import config
from logger import get_module_logger

logger = get_module_logger("Executor")


pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.5


def get_primary_monitor_info() -> dict:
    """
    兼容所有Windows版本的显示器信息获取（替换GetDpiForMonitor）
    返回：{"width": 物理宽度, "height": 物理高度, "scale_x": X轴缩放, "scale_y": Y轴缩放}
    """
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    # 方案1：让进程感知DPI（基础兼容）
    try:
        # Windows 10/11 高DPI感知
        user32.SetProcessDpiAwarenessContext(2)  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
    except:
        # 兼容旧系统
        user32.SetProcessDPIAware()

    # 获取主显示器物理分辨率
    screen_width = user32.GetSystemMetrics(0)  # SM_CXSCREEN
    screen_height = user32.GetSystemMetrics(1)  # SM_CYSCREEN

    # 方案2：通过GetDeviceCaps获取DPI（替代GetDpiForMonitor）
    hdc = user32.GetDC(None)  # 获取屏幕DC
    dpi_x = gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX = 88
    dpi_y = gdi32.GetDeviceCaps(hdc, 90)  # LOGPIXELSY = 90
    user32.ReleaseDC(None, hdc)  # 释放DC

    # 计算DPI缩放因子（96是Windows默认DPI）
    scale_x = dpi_x / 96.0
    scale_y = dpi_y / 96.0

    return {
        "width": screen_width,
        "height": screen_height,
        "scale_x": scale_x,
        "scale_y": scale_y
    }


def draw_screenshot_grid(img: Image.Image, step: int) -> Image.Image:
    """
    在截屏上绘制与屏幕像素对齐的网格：原点在左上角，每格 step×step 像素。
    gx 标在每列可见区域水平居中、靠首行上方；gy 标在每行可见区域垂直居中、靠左侧（逐格标注）。
    """
    step = max(8, int(step))
    base = img.convert("RGBA")
    w, h = base.size
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    line_rgba = (255, 64, 64, 72)
    for x in range(0, w, step):
        d.line([(x, 0), (x, h)], fill=line_rgba, width=1)
    for y in range(0, h, step):
        d.line([(0, y), (w, y)], fill=line_rgba, width=1)
    out = Image.alpha_composite(base, overlay)
    draw = ImageDraw.Draw(out)
    font_size = max(7, min(11, step // 3))
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except OSError:
        try:
            font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", font_size)
        except OSError:
            font = ImageFont.load_default()
    fill = (255, 255, 255, 240)
    stroke = (0, 0, 0, 255)
    num_gx = (w + step - 1) // step
    num_gy = (h + step - 1) // step
    row0_y1 = min(step, h)
    gx_label_y = max(font_size // 2 + 1, min(row0_y1 // 2, row0_y1 - 2))
    for gx in range(num_gx):
        x0 = gx * step
        x1 = min((gx + 1) * step, w)
        cx = (x0 + x1) // 2
        draw.text((cx, gx_label_y), str(gx), font=font, fill=fill, stroke_width=1, stroke_fill=stroke, anchor="mm")
    gy_label_x = max(3, min(step // 5, 14))
    for gy in range(num_gy):
        y0 = gy * step
        y1 = min((gy + 1) * step, h)
        cy = (y0 + y1) // 2
        draw.text((gy_label_x, cy), str(gy), font=font, fill=fill, stroke_width=1, stroke_fill=stroke, anchor="lm")
    return out.convert("RGB")


def translate_grid_xy_to_screen_coord(
    grid_x: float | int,
    grid_y: float | int,
    *,
    step: int,
    screen_width: int,
    screen_height: int,
) -> tuple[int, int]:
    """
    将截图上的网格单元索引 (gx, gy) 转为屏幕像素坐标（取该格中心点，与 pyautogui 一致）。
    """
    if not isinstance(grid_x, (int, float)) or not isinstance(grid_y, (int, float)):
        raise TypeError("网格坐标 x、y 必须为数字")
    step = max(1, int(step))
    gx = int(round(float(grid_x)))
    gy = int(round(float(grid_y)))
    gx = max(0, gx)
    gy = max(0, gy)
    max_gx = max(0, (screen_width - 1 - step // 2) // step)
    max_gy = max(0, (screen_height - 1 - step // 2) // step)
    gx = min(gx, max_gx)
    gy = min(gy, max_gy)
    screen_x = gx * step + step // 2
    screen_y = gy * step + step // 2
    screen_x = max(0, min(screen_x, screen_width - 1))
    screen_y = max(0, min(screen_y, screen_height - 1))
    logger.debug(f"网格 ({grid_x}, {grid_y}) -> 屏幕像素 ({screen_x}, {screen_y}), step={step}")
    return (screen_x, screen_y)

class Executor:
    def __init__(self, work_dir: str):
        self.work_dir = work_dir
        self.screenshot_dir = os.path.join(work_dir, "screenshots")
        os.makedirs(self.screenshot_dir, exist_ok=True)
        self.screenshot_count = 0
        self.grid_step = getattr(config, "SCREENSHOT_GRID_STEP_PX", 32)
        self._last_screenshot_size: tuple[int, int] | None = None

    def screenshot(self) -> str:
        self.screenshot_count += 1
        filename = f"screenshot_{self.screenshot_count}.png"
        filepath = os.path.join(self.screenshot_dir, filename)

        img = pyautogui.screenshot()
        self._last_screenshot_size = img.size
        gridded = draw_screenshot_grid(img, self.grid_step)
        gridded.save(filepath)
        return filepath

    def _grid_to_screen(self, grid_x, grid_y) -> tuple[int, int]:
        w, h = self._last_screenshot_size or pyautogui.size()
        pw, ph = pyautogui.size()
        if self._last_screenshot_size and (w, h) != (pw, ph):
            logger.debug(
                f"警告: 截图像素 {w}x{h} 与 pyautogui.size() {pw}x{ph} 不一致，"
                f"点击坐标按截图像素换算；若点击偏移请检查多显示器/DPI。"
            )
        return translate_grid_xy_to_screen_coord(
            grid_x, grid_y, step=self.grid_step, screen_width=w, screen_height=h
        )

    def click(self, x: int, y: int, button: str = "left") -> str:
        pyautogui.click(x, y, button=button)
        return f"Clicked at ({x}, {y}) with {button} button"

    def double_click(self, x: int, y: int, button: str = "left") -> str:
        pyautogui.doubleClick(x, y, button=button)
        return f"Double-clicked at ({x}, {y}) with {button} button"

    def right_click(self, x: int, y: int) -> str:
        return self.click(x, y, button="right")

    def move_to(self, x: int, y: int) -> str:
        pyautogui.moveTo(x, y)
        return f"Moved to ({x}, {y})"

    def type_text(self, text: str) -> str:
        pyautogui.write(text, interval=0.05)
        return f"Typed text: {text}"

    def press_key(self, key: str) -> str:
        pyautogui.press(key)
        return f"Pressed key: {key}"

    def hotkey(self, *keys) -> str:
        pyautogui.hotkey(*keys)
        return f"Pressed hotkey: {'+'.join(keys)}"

    def scroll(self, clicks: int, x: int = None, y: int = None) -> str:
        if x is not None and y is not None:
            pyautogui.scroll(clicks, x, y)
        else:
            pyautogui.scroll(clicks)
        return f"Scrolled {clicks} clicks"

    def get_screen_size(self) -> tuple:
        return pyautogui.size()

    def return_to_desktop(self) -> str:
        pyautogui.hotkey("win", "d")
        return "Returned to desktop"

    def execute_action(self, action: dict) -> str:
        action_type = action.get("action", "").lower()

        if action_type == "click":
            x = action.get("x")
            y = action.get("y")
            if x is not None and y is not None:
                real_x, real_y = self._grid_to_screen(x, y)
                return self.click(real_x, real_y)

        elif action_type == "double_click" or action_type == "双击":
            x = action.get("x")
            y = action.get("y")
            if x is not None and y is not None:
                real_x, real_y = self._grid_to_screen(x, y)
                return self.double_click(real_x, real_y)

        elif action_type == "right_click" or action_type == "右键点击":
            x = action.get("x")
            y = action.get("y")
            if x is not None and y is not None:
                real_x, real_y = self._grid_to_screen(x, y)
                return self.right_click(real_x, real_y)

        elif action_type == "move_to":
            x = action.get("x")
            y = action.get("y")
            if x is not None and y is not None:
                real_x, real_y = self._grid_to_screen(x, y)
                return self.move_to(real_x, real_y)

        elif action_type == "type" or action_type == "输入":
            text = action.get("text", "")
            return self.type_text(text)

        elif action_type == "press" or action_type == "按键":
            key = action.get("key", "")
            return self.press_key(key)

        elif action_type == "hotkey" or action_type == "快捷键":
            keys = action.get("key").split("+")
            if keys:
                return self.hotkey(*keys)

        elif action_type == "scroll" or action_type == "滚动":
            clicks = action.get("clicks", 0)
            x = action.get("x")
            y = action.get("y")
            if x is not None and y is not None:
                real_x, real_y = self._grid_to_screen(x, y)
                return self.scroll(clicks, real_x, real_y)
            return self.scroll(clicks)

        elif action_type == "screenshot" or action_type == "截屏":
            filepath = self.screenshot()
            return f"Screenshot saved: {filepath}"

        elif action_type == "wait" or action_type == "等待":
            seconds = action.get("seconds", 1)
            time.sleep(seconds)
            return f"Waited {seconds} seconds"

        elif action_type == "open_app" or action_type == "打开应用":
            app_path = action.get("path", "")
            if app_path:
                try:
                    subprocess.Popen(app_path)
                    return f"Opened application: {app_path}"
                except Exception as e:
                    return f"Failed to open application: {e}"

        elif action_type == "return_to_desktop" or action_type == "返回桌面":
            return self.return_to_desktop()
        elif action_type == "over" or action_type == "完成":
            return "任务完成"

        return f"Unknown action: {action}"
