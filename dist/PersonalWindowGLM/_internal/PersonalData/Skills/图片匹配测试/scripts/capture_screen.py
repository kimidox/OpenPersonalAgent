from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TypedDict

import pyautogui


class CaptureScreenResult(TypedDict):
    source_image_path: str


def capture_screen_to_source_images(
    *,
    source_images_dir: str | None = None,
    filename_prefix: str = "source_",
) -> CaptureScreenResult:
    """
    获取当前屏幕截图并保存到 source_images 目录，返回保存路径。
    """
    if source_images_dir is None:
        source_images_dir = str(Path(__file__).resolve().parent.parent / "source_images")
    out_dir = Path(source_images_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    out_path = out_dir / f"{filename_prefix}{ts}.png"

    img = pyautogui.screenshot()
    img.save(out_path)

    return {"source_image_path": str(out_path)}


if __name__ == "__main__":
    import json

    print(json.dumps(capture_screen_to_source_images(), ensure_ascii=False))

