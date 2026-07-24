"""
Flet UI 入口文件

基于原有 ui/main.py 功能，使用 Flet 框架实现的 UI 入口。
桌面悬浮球以独立 PySide6 进程运行，可在全桌面范围内拖拽。
"""
from __future__ import annotations

import sys
import threading
from multiprocessing import Process, Queue
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
_from_ball_queue: Queue | None = None
_ipc_poll_thread: threading.Thread | None = None
_ipc_stop_event = threading.Event()

# 页面和主窗口引用，供悬浮球 IPC 回调使用
_page: ft.Page | None = None
_main_window: MainWindow | None = None


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


def _cleanup_old_images():
    """后台清理过期的图片文件"""
    try:
        from document_parser.file_storage import cleanup_old_images

        logger = get_logger()
        logger.info("开始执行图片清理任务...")

        result = cleanup_old_images()

        deleted_count = result.get("deleted_count", 0)
        total_size = result.get("total_size", 0)

        if deleted_count > 0:
            # 格式化文件大小（字节 -> MB）
            size_mb = total_size / (1024 * 1024)
            logger.info(
                f"图片清理完成: 删除 {deleted_count} 个文件，"
                f"释放 {size_mb:.2f} MB 空间 ({total_size} 字节)"
            )
        else:
            logger.info("图片清理完成: 无需清理的过期文件")

    except Exception as e:
        logger = get_logger()
        logger.exception(f"图片清理任务异常: {e}")


def _start_floating_ball_process() -> tuple[Process, Queue, Queue]:
    """启动桌面悬浮球子进程"""
    logger = get_logger()

    # 使用 spawn 模式避免在 Windows 上继承不必要的资源
    from multiprocessing import get_context
    import os

    ctx = get_context("spawn")

    to_ball = ctx.Queue()
    from_ball = ctx.Queue()

    # 传递主进程 PID 给子进程
    main_pid = os.getpid()

    # 查找 Flet 原生进程 PID（使用进程树关系，不依赖进程名）
    # Flet 原生进程是 Python 主进程的直接子进程
    flet_pid = None
    try:
        import psutil
        current_process = psutil.Process(main_pid)
        # 获取直接子进程（Flet 原生进程应该是最近启动的子进程）
        children = current_process.children(recursive=False)
        if children:
            # 选择最近启动的子进程作为 Flet 进程
            flet_process = max(children, key=lambda p: p.create_time())
            flet_pid = flet_process.pid
            logger.info(f"找到子进程 PID: {flet_pid}, 进程名: {flet_process.name()}")
    except Exception as e:
        logger.warning(f"查找子进程失败: {e}")

    # 延迟导入，避免主进程导入 PySide6 带来的额外开销
    from ui_flet.floating_ball_process import run_floating_ball_process

    process = ctx.Process(
        target=run_floating_ball_process,
        args=(from_ball, to_ball, main_pid, flet_pid),
        name="FloatingBallProcess",
        daemon=False,
    )
    process.start()
    logger.info(f"桌面悬浮球子进程已启动 (pid={process.pid}, main_pid={main_pid}, flet_pid={flet_pid})")
    return process, to_ball, from_ball


def _stop_floating_ball_process() -> None:
    """通知悬浮球子进程和悬浮聊天窗口子进程退出并等待其结束"""
    global _floating_ball_process, _to_ball_queue

    logger = get_logger()
    logger.info("正在关闭桌面悬浮球子进程...")

    _ipc_stop_event.set()

    # 关闭悬浮球进程
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

    while not _ipc_stop_event.is_set():
        try:
            msg = from_ball.get(timeout=0.2)
        except Exception:
            continue

        msg_type = msg.get("type") if isinstance(msg, dict) else None
        logger.info(f"收到悬浮球消息: {msg_type}")

        if msg_type == MessageType.SHOW_MAIN_WINDOW:
            async def _show_main():
                main_window.show_main_window()
            page.run_task(_show_main)
        elif msg_type == MessageType.TOGGLE_CHAT:
            # 聊天窗口在悬浮球进程内部处理，主进程不需要做什么
            # TOGGLE_CHAT 消息仅用于日志记录
            logger.info("悬浮球切换聊天窗口（在悬浮球进程内部处理）")
        elif msg_type == MessageType.START_RECORDING:
            async def _start_rec():
                main_window.start_recording()
            page.run_task(_start_rec)
        elif msg_type == MessageType.STOP_RECORDING:
            async def _stop_rec():
                main_window.stop_recording()
            page.run_task(_stop_rec)
        elif msg_type == MessageType.QUIT_APPLICATION:
            # 收到退出消息，关闭 Flet 窗口
            logger.info("收到退出消息，关闭主窗口...")
            try:
                # 设置 prevent_close = False 允许关闭
                page.window.prevent_close = False
                page.update()
                # 调用窗口关闭
                page.window.close()
            except Exception as e:
                logger.error(f"关闭窗口失败: {e}")
                # 如果关闭失败，强制退出
                import os
                os._exit(1)
        elif msg_type == MessageType.CHAT_SEND_MESSAGE:
            # 转发聊天消息到主窗口
            content = msg.get("content", "")
            async def _handle_chat_send():
                main_window._on_floating_chat_send(content)
            page.run_task(_handle_chat_send)


def _start_floating_ball_mode() -> None:
    """
    启动悬浮球模式（供主窗口调用）

    当用户在关闭确认对话框中选择"悬浮球模式"时调用。
    如果悬浮球进程尚未启动，则启动它；
    如果已经启动，则确保它可见。
    """
    global _floating_ball_process, _to_ball_queue, _from_ball_queue, _ipc_poll_thread

    logger = get_logger()

    # 如果悬浮球进程已经启动，直接返回
    if _floating_ball_process is not None and _floating_ball_process.is_alive():
        logger.info("悬浮球进程已启动，无需重复启动")
        return

    # 启动悬浮球进程
    logger.info("启动悬浮球模式...")
    try:
        _floating_ball_process, _to_ball_queue, from_ball = _start_floating_ball_process()

        # 保存 from_ball 队列引用
        _from_ball_queue = from_ball

        # 启动 IPC 轮询线程
        # 必须启动，否则悬浮球发出的所有消息都无法被处理
        # 包括：显示主窗口、切换聊天、退出应用等
        if from_ball is not None and _page is not None and _main_window is not None:
            if _ipc_poll_thread is None or not _ipc_poll_thread.is_alive():
                _ipc_stop_event.clear()
                _ipc_poll_thread = threading.Thread(
                    target=_poll_ball_messages,
                    args=(_page, from_ball, _main_window),
                    name="floating-ball-ipc",
                    daemon=True,
                )
                _ipc_poll_thread.start()
                logger.info("IPC 轮询线程已启动")
            else:
                logger.info("IPC 轮询线程已在运行")
        else:
            logger.warning(f"无法启动 IPC 轮询线程: _page={_page is not None}, _main_window={_main_window is not None}")

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
    global _floating_ball_process, _to_ball_queue, _ipc_poll_thread, _page, _main_window

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

    # 保存全局引用，供悬浮球 IPC 回调使用
    _page = page
    _main_window = main_window
    logger.info("已保存 page 和 main_window 全局引用")

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

    # 启动图片清理线程（应用启动时执行一次）
    cleanup_thread = threading.Thread(
        target=_cleanup_old_images,
        name="image-cleanup",
        daemon=True
    )
    cleanup_thread.start()

    logger.info("ui_flet.main: 启动 Flet 应用")

    # 启动 Flet 应用
    ft.run(
        lambda page: main(page, background=background),
        view=ft.AppView.FLET_APP,
    )


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    # 避免 multiprocessing spawn 子进程重新启动 Flet 应用
    if multiprocessing.parent_process() is None:
        run_app()
