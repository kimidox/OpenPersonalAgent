from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypedDict

import cv2
import numpy as np


class TemplateMatchResult(TypedDict):
    target_image_path: str
    source_image_path: str
    is_found: bool
    bbox: tuple[int, int, int, int] | None


_MethodName = Literal[
    "TM_CCOEFF_NORMED",
    "TM_CCORR_NORMED",
    "TM_SQDIFF_NORMED",
    "TM_CCOEFF",
    "TM_CCORR",
    "TM_SQDIFF",
]


_METHOD_MAP: dict[_MethodName, int] = {
    "TM_CCOEFF_NORMED": cv2.TM_CCOEFF_NORMED,
    "TM_CCORR_NORMED": cv2.TM_CCORR_NORMED,
    "TM_SQDIFF_NORMED": cv2.TM_SQDIFF_NORMED,
    "TM_CCOEFF": cv2.TM_CCOEFF,
    "TM_CCORR": cv2.TM_CCORR,
    "TM_SQDIFF": cv2.TM_SQDIFF,
}


def template_match_cv2(
    target_image_path: str,
    source_image_path: str,
    *,
    threshold: float = 0.8,
    method: _MethodName = "TM_CCOEFF_NORMED",
    use_grayscale: bool = True,
) -> TemplateMatchResult:
    """
    使用 OpenCV 模板匹配，在 source_image 中寻找 taget_image（模板）的位置。

    返回 bbox 坐标为 (xmin, ymin, xmax, ymax)，均为像素整型；未找到则 bbox 为 None。
    """
    t_path = Path(target_image_path)
    s_path = Path(source_image_path)
    if not t_path.is_file():
        raise FileNotFoundError(f"taget_image_path not found: {t_path}")
    if not s_path.is_file():
        raise FileNotFoundError(f"source_image_path not found: {s_path}")

    if use_grayscale:
        tmpl = cv2.imread(str(t_path), cv2.IMREAD_GRAYSCALE)
        src = cv2.imread(str(s_path), cv2.IMREAD_GRAYSCALE)
    else:
        tmpl = cv2.imread(str(t_path), cv2.IMREAD_COLOR)
        src = cv2.imread(str(s_path), cv2.IMREAD_COLOR)

    if tmpl is None:
        raise ValueError(f"Failed to read target_image_path: {t_path}")
    if src is None:
        raise ValueError(f"Failed to read source_image_path: {s_path}")

    th, tw = tmpl.shape[:2]
    sh, sw = src.shape[:2]
    if th <= 0 or tw <= 0:
        raise ValueError("Template image is empty.")
    if th > sh or tw > sw:
        return {
            "target_image_path": str(t_path),
            "source_image_path": str(s_path),
            "is_found": False,
            "bbox": None,
        }

    m = _METHOD_MAP[method]
    res = cv2.matchTemplate(src, tmpl, m)

    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)

    if method in ("TM_SQDIFF", "TM_SQDIFF_NORMED"):
        score = float(1.0 - min_val)
        top_left = min_loc
    else:
        score = float(max_val)
        top_left = max_loc

    if score < float(threshold):
        return {
            "target_image_path": str(t_path),
            "source_image_path": str(s_path),
            "is_found": False,
            "bbox": None,
        }

    x, y = int(top_left[0]), int(top_left[1])
    bbox = (x, y, x + int(tw), y + int(th))
    return {
        "target_image_path": str(t_path),
        "source_image_path": str(s_path),
        "is_found": True,
        "bbox": bbox,
    }


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="OpenCV template matching helper")
    parser.add_argument("--target", required=True, help="Template image path")
    parser.add_argument("--source", required=True, help="Source image path")
    parser.add_argument("--threshold", type=float, default=0.8)
    parser.add_argument("--method", default="TM_CCOEFF_NORMED")
    parser.add_argument("--color", action="store_true", help="Use color (default grayscale)")
    args = parser.parse_args()

    out = template_match_cv2(
        args.taget,
        args.source,
        threshold=args.threshold,
        method=args.method,
        use_grayscale=not args.color,
    )
    print(json.dumps(out, ensure_ascii=False))

