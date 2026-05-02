---
id: 7
name: 图片匹配测试
description: 当用户需要进行图片匹配时使用。
---

## 使用说明
输入快捷键，执行'./scripts/hotkey.py':
--keys required=True, help='e.g. "ctrl+c" or "alt+tab"'
--delay type=float, default=0.0
--interval type=float, default=0.0

点击逻辑，执行'./scripts/click_bbox.py':
--bbox", required=True, help="xmin,ymin,xmax,ymax"
--delay", type=float, default=0.0
--jitter", type=int, default=0
--clicks", type=int, default=1
--button", default="left"
--interval", type=float, default=0.0

图片模板匹配逻辑，执行'./scripts/template_match_cv2.py':
--target", required=True, help="Template image path"
--source", required=True, help="Source image path"
--threshold", type=float, default=0.8
--method", default="TM_CCOEFF_NORMED"
--color", action="store_true", help="Use color (default grayscale)"

屏幕截屏逻辑，执行'./scripts/capture_screen.py':


## 执行流程
1. 执行快捷键win+d返回桌面。
2. 等待1秒后执行获取当前屏幕图片