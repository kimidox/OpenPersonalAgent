"""
桌面悬浮球子进程

在独立进程中运行一个 PySide6 无边框置顶窗口，可在全桌面范围内拖拽。
通过 multiprocessing.Queue 与后端主进程通信。
聊天窗口与悬浮球共享同一进程，点击悬浮球立即显示聊天窗口。

优化：
1. PySide6 相关导入和类定义全部延迟到 run_floating_ball_process() 内部
2. 模块级导入最小化，仅保留路径设置和 IPC 协议
3. 性能监控：记录启动各阶段耗时
"""
from __future__ import annotations

import sys
import threading
import time
import traceback
from multiprocessing import Queue
from pathlib import Path
from typing import Optional

# 兼容开发环境和 PyInstaller 打包环境
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# 最小化模块级导入 - 仅导入必要的类型定义
# 延迟导入 logger, paths 等模块到函数内部


# 尺寸和颜色常量已迁移至 floating_ball/floating_ball_widgets/_constants.py



def _set_dpi_awareness() -> None:
    """Windows 高 DPI 感知"""
    try:
        from ctypes import windll

        windll.user32.SetProcessDpiAwarenessContext(2)
    except Exception:
        try:
            from ctypes import windll

            windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def run_floating_ball_process(
    to_main_queue: Queue,
    from_main_queue: Queue,
    main_pid: int,
    live2d_enabled: bool = False,
    live2d_model_path: str | None = None,
    live2d_width: int = 200,
    live2d_height: int = 200,
    show_immediately: bool = True,
) -> None:
    """
    悬浮球子进程入口

    Args:
        to_main_queue: 发送到主进程的队列
        from_main_queue: 从主进程接收消息的队列
        main_pid: 主进程 PID
        live2d_enabled: 是否启用 Live2D
        live2d_model_path: Live2D 模型路径
        live2d_width: Live2D 窗口宽度
        live2d_height: Live2D 窗口高度
        show_immediately: 是否立即显示窗口（预启动模式下为 False）

    Business purpose:
        悬浮球子进程的入口函数，编排 QApplication 创建、组件加载和应用运行。

    Modification notes:
        2026-07-29: 内部类提取至 floating_ball_widgets 包，函数瘦身至编排逻辑

    Related tests:
        tests/test_floating_ball_widgets.py (待补充)
    """
    # =====================================================================
    # 性能监控：启动时间测量
    # =====================================================================
    start_time = time.time()
    perf_log = []  # 性能日志缓存

    def log_perf(stage: str):
        """记录性能日志"""
        elapsed = time.time() - start_time
        perf_log.append(f"[{elapsed:.3f}s] {stage}")

    log_perf("进程入口开始执行")

    # =====================================================================
    # 延迟导入基础模块
    # =====================================================================
    from logger import get_logger
    from resource_path import paths
    from floating_ball.floating_ball_ipc import MessageType, make_message

    logger = get_logger()
    log_perf("基础模块导入完成")

    # =====================================================================
    # 延迟导入 PySide6 + 初始化组件包
    # =====================================================================
    from PySide6.QtCore import Qt
    from PySide6.QtGui import (
        QPainter,
        QColor,
        QBrush,
        QIcon,
        QAction,
        QSurfaceFormat,
    )
    from PySide6.QtWidgets import (
        QApplication,
        QWidget,
        QMenu,
        QStyleFactory,
        QVBoxLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QPushButton,
        QScrollArea,
        QFrame,
    )
    from PySide6.QtOpenGLWidgets import QOpenGLWidget

    log_perf("PySide6 导入完成")

    # 导入悬浮球组件包（内部类已提取至独立模块）
    from floating_ball.floating_ball_widgets import (
        init_qcolor_constants,
        FloatingBallWindow,
    )
    init_qcolor_constants()

    log_perf("悬浮球组件包加载完成")

    # =====================================================================
    # 主逻辑：创建 QApplication 和悬浮球窗口
    # =====================================================================
    import os
    os.environ["QSG_RHI_BACKEND"] = "opengl"

    # 设置 OpenGL 格式（必须在 QApplication 创建之前）
    fmt = QSurfaceFormat()
    fmt.setAlphaBufferSize(8)
    fmt.setDepthBufferSize(24)
    fmt.setStencilBufferSize(8)
    QSurfaceFormat.setDefaultFormat(fmt)

    logger.info("OpenGL 上下文共享属性已设置")
    _set_dpi_awareness()
    log_perf("DPI 感知设置完成")

    # 初始化 Live2D Cubism 框架（创建模型前必须调用）
    live2d_module = None
    if live2d_enabled and live2d_model_path:
        try:
            import live2d.v3 as live2d_module
            live2d_module.init()
            logger.info("Live2D Cubism 框架初始化完成（live2d.init()）")
        except Exception as e:
            logger.error(f"Live2D Cubism 框架初始化失败: {e}", exc_info=True)
            live2d_enabled = False
            live2d_module = None

    app = QApplication(sys.argv)
    app.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    fusion = QStyleFactory.create("Fusion")
    if fusion is not None:
        app.setStyle(fusion)

    icon_path = paths.get_bundled_resource("application.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    log_perf("QApplication 初始化完成")

    # 始终先创建并显示默认悬浮球（快速可见，无需等待 Live2D）
    ball = FloatingBallWindow(
        to_main_queue,
        from_main_queue,
        main_pid,
        live2d_enabled,
        live2d_model_path,
        live2d_width,
        live2d_height,
    )
    log_perf("默认悬浮球创建完成")

    if show_immediately:
        ball.show()
        ball.raise_()
        ball.activateWindow()
        log_perf("默认悬浮球窗口显示完成")
        logger.info(
            f"悬浮球窗口显示信息: "
            f"visible={ball.isVisible()}, "
            f"geometry={ball.geometry()}, "
            f"pos={ball.pos()}, "
            f"size={ball.size()}"
        )
    else:
        # 预启动模式：窗口初始隐藏，等待主进程的 SHOW_WINDOW 消息
        logger.info("预启动模式：悬浮球窗口已创建，初始隐藏")

    # 输出启动性能日志
    total_time = time.time() - start_time
    logger.info("=" * 60)
    logger.info("悬浮球进程启动性能报告:")
    for log_entry in perf_log:
        logger.info(f"  {log_entry}")
    logger.info(f"  [{total_time:.3f}s] 总启动时间")
    logger.info("=" * 60)

    # 判断是否达标
    if total_time < 2.0:
        logger.info(f"✓ 启动性能达标（{total_time:.3f}s < 2s）")
    else:
        logger.warning(f"✗ 启动性能未达标（{total_time:.3f}s >= 2s）")

    # 检查 Live2D 状态并记录日志
    if live2d_enabled and live2d_model_path:
        if ball._live2d_widget is not None:
            logger.info("Live2D 悬浮球已启用并成功初始化")
        else:
            logger.warning("Live2D 启用但初始化失败，回退到默认悬浮球窗口")
    else:
        logger.info("使用默认悬浮球窗口")

    # 确保 Live2D 组件在最上层（如果存在）
    if ball._live2d_widget is not None:
        ball._live2d_widget.raise_()
        ball._live2d_widget.update()
        logger.info("Live2D 组件已提升到最上层并触发更新")

    # 运行应用
    try:
        sys.exit(app.exec())
    except KeyboardInterrupt:
        logger.info("应用被用户中断")
    except Exception as e:
        logger.error(f"应用运行异常: {e}")


def main() -> None:
    """命令行独立调试用入口"""
    import os

    # 创建一对本地队列即可独立运行，事件会打印到日志
    q1: Queue = Queue()
    q2: Queue = Queue()

    def ipc_printer():
        while True:
            try:
                msg = q1.get(timeout=0.5)
                logger.info("IPC: %s", msg)
            except Exception:
                continue

    t = threading.Thread(target=ipc_printer, daemon=True)
    t.start()

    # 独立运行时，main_pid 为当前进程 PID
    run_floating_ball_process(q1, q2, os.getpid())


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    main()
