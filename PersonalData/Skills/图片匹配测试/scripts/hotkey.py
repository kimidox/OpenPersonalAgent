from __future__ import annotations

import time
from typing import Iterable, TypedDict

import pyautogui


class HotkeyResult(TypedDict):
    keys: list[str]


def press_hotkey(keys: Iterable[str] | str, *, delay: float = 0.0, interval: float = 0.0) -> HotkeyResult:
    """
    使用 pyautogui 执行快捷键。

    - keys: 例如 ["ctrl", "c"] 或 "ctrl+c"
    - delay: 执行前延迟（秒）
    - interval: 按键间隔（秒）
    """
    if isinstance(keys, str):
        parts = [k.strip() for k in keys.replace(" ", "").split("+") if k.strip()]
        keys_list = parts
    else:
        keys_list = [str(k).strip() for k in keys if str(k).strip()]

    if not keys_list:
        raise ValueError("keys is empty")

    if delay and delay > 0:
        time.sleep(delay)

    pyautogui.hotkey(*keys_list, interval=float(interval))
    return {"keys": keys_list}


if __name__ == "__main__":
    import argparse
    import json

    p = argparse.ArgumentParser(description="Press hotkey via pyautogui")
    p.add_argument("--keys", required=True, help='e.g. "ctrl+c" or "alt+tab"')
    p.add_argument("--delay", type=float, default=0.0)
    p.add_argument("--interval", type=float, default=0.0)
    a = p.parse_args()
    print(json.dumps(press_hotkey(a.keys, delay=a.delay, interval=a.interval), ensure_ascii=False))

