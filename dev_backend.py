"""开发模式启动脚本（PyCharm 调试用）。

用途：在 PyCharm 中以此脚本为入口启动后端，断点可正常生效。
- 直接调用 uvicorn.run()，PyCharm debugger 接管主进程
- --dev 跳过 token 校验（前端 vite proxy 无需 token）
- 端口固定 8765（vite.config.ts proxy 已指向此端口）

使用方式：
1. PyCharm 运行配置 → Python → Script path = dev_backend.py
2. 点击 Debug 按钮，断点在 backend_service/ 任意 .py 文件中生效
3. 另开一个终端运行 `cd frontend && npm run dev`
4. 浏览器访问 http://localhost:1420

注意：不要用 `uvicorn backend_service.app:app` CLI 方式启动，
那样 PyCharm debugger 无法附加，断点不生效。
"""
from __future__ import annotations

import uvicorn

from backend_service.app import create_app, parse_args


def main() -> None:
    # --dev 跳过 token 校验；端口固定 8765（与 vite.config.ts proxy 对齐）
    args = parse_args(["--port", "8765", "--host", "127.0.0.1", "--dev"])
    app = create_app(args)
    print("[dev_backend] 启动后端: http://127.0.0.1:8765 (dev 模式，无 token)")
    print("[dev_backend] API 文档: http://127.0.0.1:8765/docs")
    print("[dev_backend] 前端访问: http://localhost:1420 (vite dev server)")
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info",
        reload=False,  # PyCharm 调试时禁用 reload（reload 会 fork 子进程，断点失效）
    )


if __name__ == "__main__":
    main()
