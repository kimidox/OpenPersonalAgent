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

# 确保项目根目录在 Python 路径中，支持直接运行 ui_flet/main.py
# 必须在导入项目模块之前设置
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import config
import flet as ft

from logger import get_logger
from resource_path import paths
from ui_flet.floating_ball_ipc import MessageType
from ui_flet.floating_ball_process import run_floating_ball_process
from ui_flet.views.main_window import MainWindow
from ui_flet.ipc_optimizer import BatchMessageSender, IPCPerformanceMonitor


# 悬浮球进程引用，便于退出时清理
_floating_ball_process: Process | None = None
_to_ball_queue: Queue | None = None
_from_ball_queue: Queue | None = None
_ipc_poll_thread: threading.Thread | None = None
_ipc_stop_event = threading.Event()

# IPC 优化相关
_ipc_sender: BatchMessageSender | None = None
_ipc_monitor: IPCPerformanceMonitor | None = None

# 缓存 Flet 原生进程 PID，避免每次启动悬浮球时重复枚举进程
_cached_flet_pid: int | None = None

# 页面和主窗口引用，供悬浮球 IPC 回调使用
_page: ft.Page | None = None
_main_window: MainWindow | None = None


def send_ipc_message(message: dict) -> None:
    """
    发送 IPC 消息到悬浮球进程（优化的批量发送）

    此函数供其他模块调用，自动使用批量发送机制。

    Args:
        message: 要发送的消息字典
    """
    global _ipc_sender, _to_ball_queue

    if _ipc_sender is not None:
        # 使用优化的批量发送器
        _ipc_sender.send(message)
    elif _to_ball_queue is not None:
        # 回退到原始方式
        try:
            _to_ball_queue.put(message)
        except Exception as e:
            get_logger().error(f"IPC 发送失败: {e}")
    else:
        get_logger().warning("IPC 发送失败: 悬浮球进程未启动")


def get_ipc_stats():
    """获取 IPC 性能统计"""
    global _ipc_monitor
    if _ipc_monitor is not None:
        return _ipc_monitor.get_stats()
    return None


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


def _start_floating_ball_process(prestart: bool = False) -> tuple[Process, Queue, Queue]:
    """
    启动桌面悬浮球子进程

    Args:
        prestart: 是否预启动模式（应用启动时预先启动，窗口初始隐藏）
    """
    global _ipc_sender, _ipc_monitor

    logger = get_logger()

    # 使用 spawn 模式避免在 Windows 上继承不必要的资源
    from multiprocessing import get_context
    import os

    ctx = get_context("spawn")

    to_ball = ctx.Queue()
    from_ball = ctx.Queue()

    # 初始化 IPC 优化组件
    # 批量发送参数：batch_size=20, time_window=50ms
    # 这样可以在 50ms 内累积最多 20 条消息一起发送
    if _ipc_monitor is None:
        _ipc_monitor = IPCPerformanceMonitor(latency_threshold_ms=100.0)

    if _ipc_sender is None:
        _ipc_sender = BatchMessageSender(
            queue=to_ball,
            batch_size=20,
            time_window_ms=50.0,
            use_msgpack=True,
            monitor=_ipc_monitor,
        )
        logger.info("IPC 批量消息发送器已初始化")

    # 传递主进程 PID 给子进程
    main_pid = os.getpid()

    # 查找 Flet 原生进程 PID（使用进程树关系，不依赖进程名）
    # Flet 原生进程是 Python 主进程的直接子进程
    global _cached_flet_pid
    flet_pid = None
    if _cached_flet_pid is not None:
        # 验证缓存的 PID 是否仍然有效
        try:
            import psutil
            if psutil.pid_exists(_cached_flet_pid) and psutil.Process(_cached_flet_pid).is_running():
                flet_pid = _cached_flet_pid
                logger.info(f"使用缓存的 Flet 子进程 PID: {flet_pid}")
            else:
                _cached_flet_pid = None  # 缓存失效
        except Exception:
            _cached_flet_pid = None
    if flet_pid is None:
        try:
            import psutil
            current_process = psutil.Process(main_pid)
            # 获取直接子进程（Flet 原生进程应该是最近启动的子进程）
            children = current_process.children(recursive=False)
            if children:
                # 按 cmdline 含 'flet' 特征过滤
                flet_candidates = []
                for child in children:
                    try:
                        cmdline = ' '.join(child.cmdline())
                        if 'flet' in cmdline.lower():
                            flet_candidates.append(child)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue

                if flet_candidates:
                    # 选择最近启动的 Flet 进程
                    flet_process = max(flet_candidates, key=lambda p: p.create_time())
                    flet_pid = flet_process.pid
                    _cached_flet_pid = flet_pid  # 缓存查找结果
                    logger.info(f"找到 Flet 子进程 PID: {flet_pid}, 进程名: {flet_process.name()}")
                else:
                    # 无匹配时回退原逻辑并记录 warning
                    flet_process = max(children, key=lambda p: p.create_time())
                    flet_pid = flet_process.pid
                    _cached_flet_pid = flet_pid
                    logger.warning(f"未找到包含 'flet' 特征的子进程，回退到最新子进程: PID {flet_pid}")
        except Exception as e:
            logger.warning(f"查找子进程失败: {e}")

    # 读取 Live2D 配置
    live2d_enabled = getattr(config, 'LIVE2D_ENABLED', False)
    live2d_model_name = getattr(config, 'LIVE2D_MODEL_NAME', '')
    live2d_width = getattr(config, 'LIVE2D_BALL_WIDTH', 200)
    live2d_height = getattr(config, 'LIVE2D_BALL_HEIGHT', 200)

    # 计算模型路径（查找 .model3.json 文件）
    live2d_model_path = None
    if live2d_enabled and live2d_model_name:
        from ui_flet.live2d_model_manager import _find_model3_json

        logger.info(f"准备查找 Live2D 模型，模型名称: {live2d_model_name}")
        model_dir = paths.personal_data_dir / "2DLiveFiles" / live2d_model_name
        logger.info(f"模型目录路径: {model_dir}")
        logger.info(f"模型目录是否存在: {model_dir.exists()}")
        logger.info(f"模型目录是否是目录: {model_dir.is_dir() if model_dir.exists() else 'N/A'}")
        
        model_json_path = _find_model3_json(model_dir)
        if model_json_path:
            live2d_model_path = str(model_json_path)
            logger.info(f"✓ 找到 Live2D 模型文件: {live2d_model_path}")
            logger.info(f"模型文件绝对路径: {model_json_path.absolute()}")
        else:
            logger.warning(f"✗ 未找到 Live2D 模型文件，模型目录: {model_dir}")
            logger.warning(f"禁用 Live2D，回退到默认悬浮球")
            live2d_enabled = False  # 禁用 Live2D，fallback 到默认悬浮球

    # 记录配置读取结果
    logger.info(f"Live2D 配置读取结果:")
    logger.info(f"  - LIVE2D_ENABLED: {live2d_enabled}")
    logger.info(f"  - LIVE2D_MODEL_NAME: {live2d_model_name}")
    logger.info(f"  - LIVE2D_BALL_WIDTH: {live2d_width}")
    logger.info(f"  - LIVE2D_BALL_HEIGHT: {live2d_height}")
    logger.info(f"  - 模型路径: {live2d_model_path}")

    # 延迟导入，避免主进程导入 PySide6 带来的额外开销
    # 注意：run_floating_ball_process 已移至模块级别导入（Task 1 后模块轻量化）

    # 预启动模式下，窗口初始隐藏
    show_immediately = not prestart

    process = ctx.Process(
        target=run_floating_ball_process,
        args=(from_ball, to_ball, main_pid, flet_pid, live2d_enabled, live2d_model_path, live2d_width, live2d_height, show_immediately),
        name="FloatingBallProcess",
        daemon=False,
    )
    process.start()

    if prestart:
        logger.info(f"桌面悬浮球子进程已预启动 (pid={process.pid}, main_pid={main_pid}, flet_pid={flet_pid})")
    else:
        logger.info(f"桌面悬浮球子进程已启动 (pid={process.pid}, main_pid={main_pid}, flet_pid={flet_pid})")

    logger.info(f"传递给子进程的 Live2D 参数: enabled={live2d_enabled}, model_path={live2d_model_path}, width={live2d_width}, height={live2d_height}")
    return process, to_ball, from_ball


def _stop_floating_ball_process() -> None:
    """通知悬浮球子进程和悬浮聊天窗口子进程退出并等待其结束"""
    global _floating_ball_process, _to_ball_queue, _from_ball_queue, _ipc_poll_thread, _ipc_sender

    logger = get_logger()
    logger.info("正在关闭桌面悬浮球子进程...")

    _ipc_stop_event.set()

    # 关闭 IPC 批量发送器
    if _ipc_sender is not None:
        try:
            _ipc_sender.close()
            logger.info("IPC 批量消息发送器已关闭")
        except Exception as e:
            logger.warning(f"关闭 IPC 发送器失败: {e}")
        _ipc_sender = None

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
    _from_ball_queue = None
    _ipc_poll_thread = None


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
    如果悬浮球进程已经预启动，则只需显示窗口；
    如果没有预启动，则启动新进程。
    """
    global _floating_ball_process, _to_ball_queue, _from_ball_queue, _ipc_poll_thread, _ipc_sender

    logger = get_logger()

    # 如果悬浮球进程已经启动，发送显示窗口消息
    if _floating_ball_process is not None and _floating_ball_process.is_alive():
        logger.info("悬浮球进程已预启动，发送显示窗口消息")
        # 使用优化的批量发送器发送消息
        send_ipc_message({"type": MessageType.SHOW_WINDOW})
        logger.info("已发送 SHOW_WINDOW 消息")
        return

    # 如果没有预启动，则启动悬浮球进程
    logger.info("启动悬浮球模式...")
    try:
        _floating_ball_process, _to_ball_queue, from_ball = _start_floating_ball_process(prestart=False)

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

    # 启动图片清理任务（异步执行，避免与 ft.run 初始化竞争 I/O）
    async def _cleanup_images_async():
        """异步执行图片清理"""
        _cleanup_old_images()

    page.run_task(_cleanup_images_async)

    # 不在启动时自动启动悬浮球子进程，改为用户选择"悬浮球模式"时启动
    # 如果 background=True（后台模式），则预启动悬浮球进程（隐藏状态）
    if background:
        logger.info("ui_flet.main: 后台模式，预启动悬浮球子进程")
        try:
            # 预启动悬浮球进程（窗口初始隐藏）
            _floating_ball_process, _to_ball_queue, from_ball = _start_floating_ball_process(prestart=True)

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
                logger.info("预启动模式：IPC 轮询线程已启动")
        except Exception as e:
            logger.exception(f"预启动悬浮球子进程失败: {e}")
            _floating_ball_process = None
            _to_ball_queue = None

    # 窗口关闭时清理悬浮球进程（包装原有的窗口事件处理器）
    original_on_event = page.window.on_event

    def _on_window_event(e) -> None:
        """包装原窗口事件处理器，在确认关闭时清理子进程"""
        event_type = e.type if hasattr(e, 'type') else None
        if event_type == ft.WindowEventType.CLOSE:
            logger.info("主窗口关闭事件触发，开始清理悬浮球子进程")
            _stop_floating_ball_process()
            # 调用原事件处理器后继续关闭流程
            if original_on_event is not None:
                original_on_event(e)
            return
        if original_on_event is not None:
            original_on_event(e)

    page.window.on_event = _on_window_event

    # 注册 atexit 钩子，确保程序异常退出或正常退出时都能清理悬浮球进程
    import atexit
    def _cleanup_on_exit():
        logger.info("程序退出 atexit 钩子触发，清理悬浮球子进程")
        _stop_floating_ball_process()
    atexit.register(_cleanup_on_exit)

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

    # 图片清理任务已移至 main() 函数中通过 page.run_task 异步执行
    # 避免与 ft.run 初始化竞争 I/O

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
