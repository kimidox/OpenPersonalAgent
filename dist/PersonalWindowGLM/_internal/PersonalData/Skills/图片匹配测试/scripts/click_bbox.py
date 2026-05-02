from __future__ import annotations

import random
import time
from typing import Literal, TypedDict

import pyautogui


class ClickBboxResult(TypedDict):
    clicked_at: tuple[int, int]


def click_bbox_center(
    bbox: tuple[int, int, int, int],
    *,
    delay: float = 0.0,
    jitter: int = 0,
    clicks: int = 1,
    button: Literal["left", "middle", "right"] = "left",
    interval: float = 0.0,
) -> ClickBboxResult:
    """
    根据 bbox (xmin, ymin, xmax, ymax) 点击其中心点。

    - delay: 点击前延迟（秒）
    - jitter: 抖动范围（像素），实际点击点会在中心点基础上随机偏移 [-jitter, +jitter]
    """
    xmin, ymin, xmax, ymax = bbox
    cx = int(round((xmin + xmax) / 2.0))
    cy = int(round((ymin + ymax) / 2.0))

    if jitter and jitter > 0:
        cx += random.randint(-jitter, jitter)
        cy += random.randint(-jitter, jitter)

    if delay and delay > 0:
        time.sleep(delay)

    pyautogui.click(x=cx, y=cy, clicks=int(clicks), interval=float(interval), button=button)
    return {"clicked_at": (cx, cy)}


if __name__ == "__main__":
    import argparse
    import json

    p = argparse.ArgumentParser(description="Click bbox center via pyautogui")
    p.add_argument("--bbox", required=True, help="xmin,ymin,xmax,ymax")
    p.add_argument("--delay", type=float, default=0.0)
    p.add_argument("--jitter", type=int, default=0)
    p.add_argument("--clicks", type=int, default=1)
    p.add_argument("--button", default="left")
    p.add_argument("--interval", type=float, default=0.0)
    a = p.parse_args()

    parts = [int(x.strip()) for x in a.bbox.split(",")]
    if len(parts) != 4:
        raise SystemExit("bbox must be xmin,ymin,xmax,ymax")
    print(
        json.dumps(
            click_bbox_center(
                (parts[0], parts[1], parts[2], parts[3]),
                delay=a.delay,
                jitter=a.jitter,
                clicks=a.clicks,
                button=a.button,
                interval=a.interval,
            ),
            ensure_ascii=False,
        )
    )

