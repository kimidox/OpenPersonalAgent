"""
Flet UI 入口文件

基于原有 ui/main.py 功能，使用 Flet 框架实现的 UI 入口。
桌面悬浮球以独立 PySide6 进程运行，可在全桌面范围内拖拽。
"""
from __future__ import annotations

import sys
import threading
from multiprocessing import Process
from pathlib import Path

import flet as ft

# 确保项目根目录在 Python 路径中，支持直接运行 ui_flet/main.py
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from logger import get_logger
from resource_path import paths
from ui_flet.floating_ball_ipc import MessageType
from ui_flet.views.main_window import MainWindow


# 悬浮球进程引用，便于退出时清理
_floating_ball_process: Process | None = None
_to_ball_queue: Queue | None = None
_ipc_poll_thread: threading.Thread | None = None
_ipc_stop_event = threading.Event()


def _preload_asr_check():
    """后台检查 ASR 模型配置并自动加载"""
    try:
        import config
        from recorder import is_online_model_loaded, load_online_model

        logger = get_logger()

        # 检查是否配置了自动加载流式模型
        if getattr(config, 'ASR_REALTIME_AUTO_LOAD', False):
            logger.info("配置了自动加载流式模型，正在加载...")
            if not is_online_model_loaded():
                success = load_online_model()
                if success:
                    logger.info("流式模型自动加载成功")
                else:
                    logger.warning("流式模型自动加载失败")
            else:
                logger.info("流式模型已加载")
        else:
            if not is_online_model_loaded():
                logger.info("流式模型未加载，录音功能需要先在设置中加载模型")
    except Exception as e:
        logger = get_logger()
        logger.exception(f"ASR 模型自动加载检查异常: {e}")


def _preload_tts_check():
    """后台检查 TTS 模型配置并自动加载"""
    try:
        import config
        from tts import is_tts_model_loaded, load_tts_model

        logger = get_logger()

        # 检查是否配置了自动加载
        if getattr(config, 'TTS_AUTO_LOAD', False):
            logger.info("配置了自动加载 TTS 模型，正在加载...")
            if not is_tts_model_loaded():
                # 使用配置的模型类型
                model_type = getattr(config, 'TTS_MODEL_TYPE', 'zh')
                model_path = getattr(config, 'TTS_MODEL_PATH', '')

                if model_path:
                    success = load_tts_model(model_path, auto_download=False)
                else:
                    success = load_tts_model(model_type=model_type, auto_download=True)

                if success:
                    logger.info("TTS 模型自动加载成功")
                else:
                    logger.warning("TTS 模型自动加载失败")
            else:
                logger.info("TTS 模型已加载")
    except Exception as e:
        logger = get_logger()
        logger.exception(f"TTS 模型自动加载检查异常: {e}")


def _start_floating_ball_process() -> tuple[Process, Queue, Queue]:
    """启动桌面悬浮球子进程"""
    logger = get_logger()

    # 使用 spawn 模式避免在 Windows 上继承不必要的资源
    from multiprocessing import get_context
    ctx = get_context("spawn")

    to_ball = ctx.Queue()
    from_ball = ctx.Queue()

    # 延迟导入，避免主进程导入 PySide6 带来的额外开销
    from ui_flet.floating_ball_process import run_floating_ball_process

    process = ctx.Process(
        target=run_floating_ball_process,
        args=(from_ball, to_ball),
        name="FloatingBallProcess",
        daemon=False,
    )
    process.start()
    logger.info(f"桌面悬浮球子进程已启动 (pid={process.pid})")
    return process, to_ball, from_ball


def _stop_floating_ball_process() -> None:
    """通知悬浮球子进程退出并等待其结束"""
    global _floating_ball_process, _to_ball_queue

    logger = get_logger()
    logger.info("正在关闭桌面悬浮球子进程...")

    _ipc_stop_event.set()

    if _to_ball_queue is not None:
        try:
            _to_ball_queue.put({"type": MessageType.EXIT})
        except Exception as e:
            logger.warning(f"通知悬浮球退出失败: {e}")

    if _floating_ball_process is not None and _floating_ball_process.is_alive():
        try:
            _floating_ball_process.join(timeout=3)
            if _floating_ball_process.is_alive():
                logger.warning("悬浮球子进程未在 3 秒内退出，强制终止")
                _floating_ball_process.terminate()
                _floating_ball_process.join(timeout=2)
        except Exception as e:
            logger.warning(f"关闭悬浮球子进程异常: {e}")

    _floating_ball_process = None
    _to_ball_queue = None


def _poll_ball_messages(page: ft.Page, from_ball: Queue, main_window: MainWindow) -> None:
    """在后台线程中轮询悬浮球消息，并调度到 Flet 主线程处理"""
    logger = get_logger()

    def _dispatch(handler):
        try:
            page.run(handler)
        except Exception as e:
            logger.exception(f"调度悬浮球消息到 Flet 主线程失败: {e}")

    while not _ipc_stop_event.is_set():
        try:
            msg = from_ball.get(timeout=0.2)
        except Exception:
            continue

        msg_type = msg.get("type") if isinstance(msg, dict) else None
        logger.info(f"收到悬浮球消息: {msg_type}")

        if msg_type == MessageType.SHOW_MAIN_WINDOW:
            _dispatch(lambda: main_window.show_main_window())
        elif msg_type == MessageType.TOGGLE_CHAT:
            _dispatch(lambda: main_window.toggle_floating_chat())
        elif msg_type == MessageType.START_RECORDING:
            _dispatch(lambda: main_window.start_recording())
        elif msg_type == MessageType.STOP_RECORDING:
            _dispatch(lambda: main_window.stop_recording())
        elif msg_type == MessageType.QUIT_APPLICATION:
            _dispatch(lambda: page.run_task(main_window.quit_application()))


def _start_floating_ball_mode() -> None:
    """
    启动悬浮球模式（供主窗口调用）

    当用户在关闭确认对话框中选择"悬浮球模式"时调用。
    如果悬浮球进程尚未启动，则启动它；
    如果已经启动，则确保它可见。
    """
    global _floating_ball_process, _to_ball_queue

    logger = get_logger()

    # 如果悬浮球进程已经启动，直接返回
    if _floating_ball_process is not None and _floating_ball_process.is_alive():
        logger.info("悬浮球进程已启动，无需重复启动")
        return

    # 启动悬浮球进程
    logger.info("启动悬浮球模式...")
    try:
        _floating_ball_process, _to_ball_queue, from_ball = _start_floating_ball_process()

        # 注意：在悬浮球模式下，不启动 IPC 轮询线程
        # 因为主窗口已经隐藏，不需要处理来自悬浮球的消息
        # 悬浮球进程会独立运行，用户可以通过点击悬浮球来显示主窗口

        logger.info("悬浮球模式启动成功")
    except Exception as e:
        logger.exception(f"启动悬浮球模式失败: {e}")


def main(page: ft.Page, background: bool = False) -> None:
    """
    Flet 应用主入口

    Args:
        page: Flet Page 对象
        background: 是否后台模式启动（True 时最小化窗口）
    """
    global _floating_ball_process, _to_ball_queue, _ipc_poll_thread

    logger = get_logger()

    # 记录窗口初始状态
    logger.info(f"窗口初始状态 - visible: {page.window.visible}, "
                f"width: {page.window.width}, height: {page.window.height}, "
                f"left: {page.window.left}, top: {page.window.top}")

    # 先隐藏窗口，避免显示默认标题
    logger.info("设置窗口可见性: False（初始化隐藏）")
    page.window.visible = False
    logger.info(f"窗口可见性已设置: {page.window.visible}")

    # 设置页面标题（必须先设置）
    page.title = "PersonalWindowGLM"
    logger.info(f"设置页面标题: {page.title}")

    # 加载应用图标
    icon_path = paths.get_bundled_resource("application.ico")
    if icon_path.exists():
        # Flet 使用 window.icon 设置窗口图标
        page.window.icon = str(icon_path)
        logger.info(f"已加载应用图标: {icon_path}")

    logger.info("ui_flet.main: 创建主窗口")

    # 创建主窗口
    main_window = MainWindow(page)

    logger.info(f"主窗口创建完成，page.controls 数量: {len(page.controls)}")

    # 页面构建完成后，延迟注册 FilePicker
    input_area = main_window.get_input_area()
    if input_area:
        async def _attach_file_picker():
            """延迟注册 FilePicker"""
            input_area.attach_to_page()
            logger.info("FilePicker 已注册")

        page.run_task(_attach_file_picker)

    # 不在启动时自动启动悬浮球子进程，改为用户选择"悬浮球模式"时启动
    # 如果 background=True（后台模式），则启动悬浮球
    if background:
        logger.info("ui_flet.main: 后台模式，启动悬浮球子进程")
        try:
            _floating_ball_process, _to_ball_queue, from_ball = _start_floating_ball_process()

            # 启动 IPC 轮询线程
            if from_ball is not None:
                _ipc_stop_event.clear()
                _ipc_poll_thread = threading.Thread(
                    target=_poll_ball_messages,
                    args=(page, from_ball, main_window),
                    name="floating-ball-ipc",
                    daemon=True,
                )
                _ipc_poll_thread.start()
        except Exception as e:
            logger.exception(f"后台模式启动悬浮球子进程失败: {e}")
            _floating_ball_process = None
            _to_ball_queue = None

    # 窗口关闭时清理悬浮球进程（包装原有的窗口事件处理器）
    original_on_event = page.window.on_event

    def _on_window_event(e) -> None:
        """包装原窗口事件处理器，在确认关闭时清理子进程"""
        event_type = e.type if hasattr(e, 'type') else None
        if event_type == ft.WindowEventType.CLOSE:
            if not page.window.prevent_close:
                # prevent_close 为 False 表示正在执行真实关闭，清理子进程
                logger.info("主窗口关闭，开始清理悬浮球子进程")
                _stop_floating_ball_process()
                return
        if original_on_event is not None:
            original_on_event(e)

    page.window.on_event = _on_window_event

    # 后台模式处理
    logger.info(f"ui_flet.main: background = {background}")
    if background:
        logger.info("ui_flet.main: 后台模式，最小化窗口")
        logger.info(f"窗口状态（最小化前） - visible: {page.window.visible}, "
                    f"minimized: {page.window.minimized}")
        page.window.minimized = True
        logger.info(f"窗口已最小化 - minimized: {page.window.minimized}, "
                    f"visible: {page.window.visible}")
    else:
        # 非后台模式：显示主窗口
        logger.info("ui_flet.main: 非后台模式，准备显示主窗口")
        # 记录窗口位置验证完成后的状态
        logger.info(f"窗口状态（显示前） - visible: {page.window.visible}, "
                    f"width: {page.window.width}, height: {page.window.height}, "
                    f"left: {page.window.left}, top: {page.window.top}")
        logger.info("设置窗口可见性: True（准备显示）")
        page.window.visible = True
        logger.info(f"窗口可见性已设置: {page.window.visible}")

    # 记录最终状态
    logger.info(f"最终窗口状态 - visible: {page.window.visible}, "
                f"minimized: {page.window.minimized}, "
                f"width: {page.window.width}, height: {page.window.height}, "
                f"left: {page.window.left}, top: {page.window.top}")
    logger.info(f"最终 page.controls 数量: {len(page.controls)}, overlay 数量: {len(page.overlay)}")

    # 调用 page.update() 更新窗口状态
    logger.info("调用 page.update() 更新窗口状态")
    page.update()
    logger.info("page.update() 已完成")


def run_app(background: bool = False) -> None:
    """
    启动 Flet 应用

    Args:
        background: 是否后台模式启动
    """
    logger = get_logger()

    # 启动 ASR 预加载线程
    preload_thread = threading.Thread(
        target=_preload_asr_check,
        name="asr-preload",
        daemon=True
    )
    preload_thread.start()

    # 启动 TTS 预加载线程
    tts_preload_thread = threading.Thread(
        target=_preload_tts_check,
        name="tts-preload",
        daemon=True
    )
    tts_preload_thread.start()

    logger.info("ui_flet.main: 启动 Flet 应用")

    # 启动 Flet 应用
    ft.run(
        lambda page: main(page, background=background)
    )


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    # 避免 multiprocessing spawn 子进程重新启动 Flet 应用
    if multiprocessing.parent_process() is None:
        run_app()
