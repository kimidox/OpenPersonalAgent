"""悬浮球子进程托管（阶段 5）。

由 backend_service（uvicorn）作为父进程托管悬浮球子进程
（PySide6，代码位于 floating_ball/ 包）。

关键设计（见 frontend-tauri-refactor.md 3.5 节与调研报告第 8 节）：
- 球→backend 消息直接在 _poll_loop 线程内处理
  （调 run_coordinator / recorder / stream_bridge）。
- QUIT_APPLICATION 不再 os._exit(backend)，改为发 floating_ball.quit WS 事件通知 Tauri。
- backend→球事件（LLM_STATE_UPDATE / CHAT_RECEIVE_MESSAGE）由 StreamBridge._emit 分流转发。
- 子进程入口 run_floating_ball_process / FloatingBallWindow / IPC 协议保持不变。
"""
from __future__ import annotations

import os
import threading
from multiprocessing import Process, Queue, get_context
from typing import Any

import config
from logger import get_logger
from resource_path import paths
from floating_ball.floating_ball_ipc import (
    MessageType,
    make_llm_state_update_message,
    make_llm_state_warning_message,
)
from floating_ball.floating_ball_process import run_floating_ball_process
from floating_ball.ipc_optimizer import BatchMessageSender, IPCPerformanceMonitor


class FloatingBallManager:
    """悬浮球子进程托管单例。

    由 lifecycle 在 lifespan 启动时创建并注入依赖（stream_bridge / run_coordinator /
    skill_agent / memory / loop）。球→backend 消息在 _poll_loop 内直接处理。
    """

    def __init__(self) -> None:
        self._logger = get_logger()
        # 依赖（由 set_dependencies 注入）
        self._stream_bridge: Any = None
        self._run_coordinator: Any = None
        self._skill_agent: Any = None
        self._memory: Any = None
        self._loop: Any = None
        # 子进程状态
        self._process: Process | None = None
        self._to_ball: Queue | None = None       # 主→球
        self._from_ball: Queue | None = None     # 球→主
        self._poll_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._ipc_sender: BatchMessageSender | None = None
        self._ipc_monitor: IPCPerformanceMonitor | None = None
        self._main_pid: int = os.getpid()

    # ------------------------------------------------------------------
    # 依赖注入
    # ------------------------------------------------------------------

    def set_dependencies(
        self,
        *,
        stream_bridge: Any,
        run_coordinator: Any,
        skill_agent: Any,
        memory: Any,
        loop: Any,
    ) -> None:
        """lifespan 完成组件初始化后调用。"""
        self._stream_bridge = stream_bridge
        self._run_coordinator = run_coordinator
        self._skill_agent = skill_agent
        self._memory = memory
        self._loop = loop

    # ------------------------------------------------------------------
    # 启停
    # ------------------------------------------------------------------

    def start(self, prestart: bool = True) -> bool:
        """启动悬浮球子进程。

        Args:
            prestart: True=预启动（窗口初始隐藏），False=立即显示。

        Returns:
            True 表示启动成功。
        """
        if self._process is not None and self._process.is_alive():
            self._logger.warning("悬浮球子进程已在运行，跳过启动")
            return False

        self._stop_event.clear()
        ctx = get_context("spawn")
        self._to_ball = ctx.Queue()
        self._from_ball = ctx.Queue()

        # IPC 优化组件
        if self._ipc_monitor is None:
            self._ipc_monitor = IPCPerformanceMonitor(latency_threshold_ms=100.0)
        if self._ipc_sender is None:
            self._ipc_sender = BatchMessageSender(
                queue=self._to_ball,
                batch_size=20,
                time_window_ms=50.0,
                use_msgpack=True,
                monitor=self._ipc_monitor,
            )
            self._logger.info("IPC 批量消息发送器已初始化")

        # Live2D 配置读取（复刻原 _start_floating_ball_process）
        live2d_enabled = getattr(config, "LIVE2D_ENABLED", False)
        live2d_model_name = getattr(config, "LIVE2D_MODEL_NAME", "")
        live2d_width = getattr(config, "LIVE2D_BALL_WIDTH", 200)
        live2d_height = getattr(config, "LIVE2D_BALL_HEIGHT", 200)
        live2d_model_path = self._resolve_live2d_model_path(
            live2d_enabled, live2d_model_name
        )

        show_immediately = not prestart

        self._process = ctx.Process(
            target=run_floating_ball_process,
            args=(
                self._from_ball,
                self._to_ball,
                self._main_pid,
                live2d_enabled,
                live2d_model_path,
                live2d_width,
                live2d_height,
                show_immediately,
            ),
            name="FloatingBallProcess",
            daemon=False,
        )
        self._process.start()

        # 启动 IPC 轮询线程
        self._poll_thread = threading.Thread(
            target=self._poll_loop,
            name="floating-ball-ipc",
            daemon=True,
        )
        self._poll_thread.start()

        self._logger.info(
            f"悬浮球子进程已{'预启动' if prestart else '启动'} "
            f"(pid={self._process.pid}, main_pid={self._main_pid})"
        )
        return True

    def stop(self) -> None:
        """通知子进程退出并等待结束。"""
        if self._process is None:
            return

        self._logger.info("正在关闭悬浮球子进程...")
        self._stop_event.set()

        # 先关闭批量发送器（flush 缓冲）
        if self._ipc_sender is not None:
            try:
                self._ipc_sender.close()
                self._logger.info("IPC 批量消息发送器已关闭")
            except Exception as e:
                self._logger.warning(f"关闭 IPC 发送器失败: {e}")
            self._ipc_sender = None

        # 通知子进程退出（直接 put，绕过已关闭的 sender）
        if self._to_ball is not None:
            try:
                self._to_ball.put({"type": MessageType.EXIT})
            except Exception as e:
                self._logger.warning(f"通知悬浮球退出失败: {e}")

        # 等待子进程结束
        if self._process.is_alive():
            try:
                self._process.join(timeout=3)
                if self._process.is_alive():
                    self._logger.warning("悬浮球子进程未在 3 秒内退出，强制终止")
                    self._process.terminate()
                    self._process.join(timeout=2)
            except Exception as e:
                self._logger.warning(f"关闭悬浮球子进程异常: {e}")

        self._process = None
        self._to_ball = None
        self._from_ball = None
        self._poll_thread = None
        self._logger.info("悬浮球子进程已停止")

    # ------------------------------------------------------------------
    # 对外 API（供路由 / stream_bridge 调用）
    # ------------------------------------------------------------------

    def send(self, message: dict) -> None:
        """发送消息到悬浮球子进程。"""
        if self._ipc_sender is not None:
            self._ipc_sender.send(message)
        elif self._to_ball is not None:
            try:
                self._to_ball.put(message)
            except Exception as e:
                self._logger.error(f"IPC 发送失败: {e}")
        else:
            self._logger.warning("IPC 发送失败: 悬浮球进程未启动")

    def show(self) -> None:
        """显示悬浮球窗口。"""
        self.send({"type": MessageType.SHOW_WINDOW})

    def hide(self) -> None:
        """隐藏悬浮球窗口。"""
        self.send({"type": MessageType.HIDE_WINDOW})

    def set_theme(self, theme: str) -> None:
        """更新主题色。"""
        self.send({"type": MessageType.SET_THEME, "theme": theme})

    def is_running(self) -> bool:
        """悬浮球子进程是否在运行。"""
        return self._process is not None and self._process.is_alive()

    def get_stats(self) -> Any:
        """获取 IPC 性能统计。"""
        if self._ipc_monitor is not None:
            return self._ipc_monitor.get_stats()
        return None

    def send_chat_reply(self, content: str) -> None:
        """把助手回复下发到悬浮球聊天窗口。"""
        self.send({"type": MessageType.CHAT_RECEIVE_MESSAGE, "content": content})

    def send_llm_state_update(self, state_data: dict) -> None:
        """把 LLM 状态更新下发到悬浮球。"""
        msg = make_llm_state_update_message(
            state=state_data.get("state", "IDLE"),
            timestamp=state_data.get("timestamp", 0),
            model=state_data.get("model"),
            session_id=state_data.get("session_id"),
            duration_ms=state_data.get("duration_ms"),
            error_message=state_data.get("error_message"),
        )
        self.send(msg)

    def send_llm_state_warning(self, warning_data: dict) -> None:
        """把 LLM 状态告警下发到悬浮球。"""
        msg = make_llm_state_warning_message(
            warning_type=warning_data.get("warning_type", "unknown"),
            timestamp=warning_data.get("timestamp", 0),
            state=warning_data.get("state", "UNKNOWN"),
            duration_ms=warning_data.get("duration_ms"),
            model=warning_data.get("model"),
            session_id=warning_data.get("session_id"),
            message=warning_data.get("message"),
        )
        self.send(msg)

    # ------------------------------------------------------------------
    # 球→backend 消息轮询
    # ------------------------------------------------------------------

    def _poll_loop(self) -> None:
        """后台线程：轮询球→主消息并处理。"""
        assert self._from_ball is not None
        while not self._stop_event.is_set():
            try:
                msg = self._from_ball.get(timeout=0.2)
            except Exception:
                continue
            if not isinstance(msg, dict):
                continue
            msg_type = msg.get("type")
            self._logger.info(f"收到悬浮球消息: {msg_type}")
            try:
                self._handle_ball_message(msg_type, msg)
            except Exception as e:
                self._logger.exception(f"处理悬浮球消息 {msg_type} 失败: {e}")

    def _handle_ball_message(self, msg_type: str | None, msg: dict) -> None:
        """处理球→backend 消息（替代原 page.run_task 调度）。"""
        if msg_type == MessageType.SHOW_MAIN_WINDOW:
            # 通知 Tauri 前端显示主窗口
            self._emit_window_show()
        elif msg_type == MessageType.TOGGLE_CHAT:
            # 球内部处理，仅日志
            self._logger.info("悬浮球切换聊天窗口（球内部处理）")
        elif msg_type == MessageType.START_RECORDING:
            self._start_recording()
        elif msg_type == MessageType.STOP_RECORDING:
            self._stop_recording()
        elif msg_type == MessageType.QUIT_APPLICATION:
            # 通知 Tauri 关闭应用（禁止 os._exit backend 进程）
            self._emit_quit()
        elif msg_type == MessageType.CHAT_SEND_MESSAGE:
            content = msg.get("content", "")
            self._handle_chat_send(content)
        elif msg_type == MessageType.CHAT_REQUEST_HISTORY:
            self._handle_request_history()
        else:
            self._logger.debug(f"未处理的悬浮球消息类型: {msg_type}")

    # ------------------------------------------------------------------
    # 球消息处理实现
    # ------------------------------------------------------------------

    def _emit_window_show(self) -> None:
        """发 window.show WS 事件，Tauri 前端收到后显示主窗口。"""
        if self._stream_bridge is None:
            return
        from backend_service.ws.events import WSEvent, EVENT_WINDOW_SHOW

        event = WSEvent(
            event=EVENT_WINDOW_SHOW,
            conversation_id="",
            run_id="",
            data={"source": "floating_ball"},
        )
        self._stream_bridge._emit(event)

    def _emit_quit(self) -> None:
        """发 floating_ball.quit WS 事件，Tauri 前端收到后关闭应用。"""
        if self._stream_bridge is None:
            return
        from backend_service.ws.events import WSEvent, EVENT_FLOATING_BALL_QUIT

        event = WSEvent(
            event=EVENT_FLOATING_BALL_QUIT,
            conversation_id="",
            run_id="",
            data={"source": "floating_ball"},
        )
        self._stream_bridge._emit(event)

    def _start_recording(self) -> None:
        """开始录音（直接调 recorder 模块，在轮询线程内阻塞）。"""
        try:
            from recorder import is_recording, start_recording

            if not is_recording():
                start_recording()
                self._logger.info("悬浮球触发录音已开始")
            else:
                self._logger.info("录音已在进行中，忽略悬浮球开始请求")
        except Exception as e:
            self._logger.exception(f"悬浮球触发开始录音失败: {e}")

    def _stop_recording(self) -> None:
        """停止录音。"""
        try:
            from recorder import is_recording, stop_recording

            if is_recording():
                stop_recording()
                self._logger.info("悬浮球触发录音已停止")
            else:
                self._logger.info("录音未在进行，忽略悬浮球停止请求")
        except Exception as e:
            self._logger.exception(f"悬浮球触发停止录音失败: {e}")

    def _handle_chat_send(self, content: str) -> None:
        """处理悬浮球聊天消息：创建会话 + submit run（source=floating_ball）。

        与 scheduler._trigger_agent_conversation_backend 同模式：
        1. 创建新会话
        2. 构造 RunContext(source="floating_ball")
        3. 注入 stream_bridge 的 executor/on_complete/on_error
        4. 调 run_coordinator.submit(ctx, queued_ok=False)
        """
        if not content.strip():
            return
        if self._skill_agent is None or self._run_coordinator is None:
            self._logger.warning("SkillAgent/RunCoordinator 未就绪，无法处理悬浮球消息")
            return
        if self._run_coordinator.is_busy():
            self._logger.info("RunCoordinator 忙碌，悬浮球消息被丢弃（queued_ok=False）")
            # 通知球当前忙
            self.send_chat_reply("当前正在处理其他请求，请稍后再试。")
            return

        try:
            conversation_id, _title = self._skill_agent.start_new_conversation(
                conversation_type="agent_conversation",
            )
        except Exception as e:
            self._logger.exception(f"悬浮球创建会话失败: {e}")
            return

        from backend_service.runner import RunContext
        from backend_service.ws.events import new_run_id

        run_id = new_run_id()
        ctx = RunContext(
            run_id=run_id,
            conversation_id=conversation_id,
            source="floating_ball",
            query=content,
        )
        assert self._stream_bridge is not None
        ctx.executor = self._stream_bridge.build_executor(ctx)
        ctx.on_complete = self._stream_bridge.make_on_complete(ctx)
        ctx.on_error = self._stream_bridge.make_on_error(ctx)

        try:
            result = self._run_coordinator.submit(ctx, queued_ok=False)
            self._logger.info(
                f"悬浮球消息已提交: run_id={run_id[:8]}, "
                f"conversation_id={conversation_id[:8]}, status={result.status}"
            )
        except Exception as e:
            self._logger.exception(f"悬浮球消息提交 RunCoordinator 失败: {e}")

    def _handle_request_history(self) -> None:
        """请求历史消息：从 memory 取最近会话历史下发给球。"""
        if self._memory is None or self._skill_agent is None:
            return
        try:
            # 取当前会话的消息记录
            conversation_id = getattr(self._skill_agent, "conversation_id", "")
            if not conversation_id:
                self.send({"type": MessageType.CHAT_RECEIVE_HISTORY, "messages": []})
                return
            records = self._memory.message_records_for_conversation(conversation_id)
            # 简化：只取最近 20 条
            recent = records[-20:] if records else []
            self.send({
                "type": MessageType.CHAT_RECEIVE_HISTORY,
                "messages": recent,
            })
        except Exception as e:
            self._logger.exception(f"悬浮球请求历史失败: {e}")

    # ------------------------------------------------------------------
    # Live2D 模型路径解析
    # ------------------------------------------------------------------

    def _resolve_live2d_model_path(
        self, live2d_enabled: bool, live2d_model_name: str
    ) -> str | None:
        """解析 Live2D 模型 .model3.json 路径（复刻原 _start_floating_ball_process）。"""
        if not live2d_enabled or not live2d_model_name:
            return None
        try:
            from floating_ball.live2d_model_manager import _find_model3_json

            model_dir = paths.personal_data_dir / "2DLiveFiles" / live2d_model_name
            model_json_path = _find_model3_json(model_dir)
            if model_json_path:
                self._logger.info(f"找到 Live2D 模型文件: {model_json_path}")
                return str(model_json_path)
            self._logger.warning(
                f"未找到 Live2D 模型文件，禁用 Live2D: {model_dir}"
            )
            return None
        except Exception as e:
            self._logger.warning(f"解析 Live2D 模型路径失败: {e}")
            return None
