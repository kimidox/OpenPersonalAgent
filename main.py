"""PersonalWindowGLM 主入口（阶段 6 重构后）。

重构后入口切换为后端服务启动器（见 frontend-tauri-refactor.md 3.7 节）：
- Tauri 外壳启动后由 Rust 侧拉起 Python sidecar（本模块）
- 本模块直接调 `backend_service.app:main()` 跑 uvicorn

开发模式可独立运行：
    python main.py --port 8765 --dev
打包模式由 Tauri sidecar 调起：
    backend_service.exe --port {动态端口} --token {随机token}

注意：
- 启动前的初始化（init_db / 模型目录迁移 / 性能监控）保留在 backend_service.lifecycle 内统一执行
- 性能监控与日志在 backend_service.app.lifespan 内启动
"""
from __future__ import annotations

import multiprocessing
import sys


def main() -> None:
    # 延迟导入：允许 `python -c "import main"` 不触发后端启动
    from backend_service.app import main as backend_main

    backend_main()


if __name__ == "__main__":
    # Windows 打包模式必须最先调用：multiprocessing spawn 的子进程（悬浮球）以
    # `backend_service.exe --multiprocessing-fork ...` 重新拉起本 exe，
    # freeze_support 会把控制权交给子进程入口；漏掉则子进程把该参数当普通
    # CLI 参数再跑一遍后端 → argparse 报错退出（黑框一闪 + 悬浮球不出现）。
    # dev 模式下是 no-op。
    multiprocessing.freeze_support()
    main()
