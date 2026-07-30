"""
悬浮球 Mixin

负责悬浮球相关功能：显示主窗口、悬浮聊天切换、录音控制等。
"""
from __future__ import annotations

import threading

from logger import get_logger


class FloatingBallMixin:
    """
    悬浮球 Mixin

    包含悬浮球相关的方法：显示主窗口、悬浮聊天切换、录音控制等。
    通过 self 访问 MainWindow 的属性（如 self._page, self._logger, self._floating_chat_window 等）。
    """

    # ==================================================================
    # 悬浮球和应用控制
    # ==================================================================

    def show_main_window(self) -> None:
        """显示并激活主窗口（供桌面悬浮球调用）"""
        try:
            self._page.window.minimized = False
            self._page.window.visible = True
            self._page.window.focused = True
            self._page.update()
            self._logger.info("悬浮球请求：显示主窗口")
        except Exception as e:
            self._logger.warning(f"显示主窗口失败: {e}")

    async def quit_application(self) -> None:
        """退出应用（供桌面悬浮球调用）"""
        self._logger.info("悬浮球请求：退出应用")
        self._stop_scheduler()

        # 使用线程延迟退出，避免在异步上下文中直接退出
        import sys
        import os

        def _force_exit():
            import time
            time.sleep(0.5)  # 等待日志写入
            self._logger.info("强制退出应用")
            os._exit(0)

        # 启动后台线程强制退出
        exit_thread = threading.Thread(target=_force_exit, daemon=True)
        exit_thread.start()

        # 尝试优雅关闭（可能失败，但不影响强制退出）
        try:
            self._page.window.prevent_close = False
            self._page.update()
        except Exception as e:
            self._logger.warning(f"优雅关闭失败: {e}")

    def toggle_floating_chat(self) -> None:
        """切换悬浮聊天窗口显示状态（供桌面悬浮球调用）"""
        if self._floating_chat_window:
            self._floating_chat_window.toggle()
            self._logger.info("悬浮球请求：切换悬浮聊天窗口")
        else:
            self._logger.warning("悬浮聊天窗口未初始化")

    def start_recording(self) -> None:
        """开始录音（供桌面悬浮球调用）"""
        try:
            from recorder import get_recorder, is_online_model_loaded

            if not is_online_model_loaded():
                self._logger.warning("流式 ASR 模型未加载，无法实时识别")
                return

            recorder = get_recorder()
            self._recording_text = ""
            recorder.start_recording(
                realtime_callback=self._on_recording_realtime_result
            )
            self._logger.info("悬浮球请求：开始录音")
        except Exception as e:
            self._logger.exception(f"开始录音失败: {e}")

    def stop_recording(self) -> None:
        """停止录音并发送识别结果（供桌面悬浮球调用）"""
        try:
            from recorder import get_recorder

            recorder = get_recorder()
            audio_path = recorder.stop_recording()
            self._logger.info(f"悬浮球请求：停止录音，音频路径={audio_path}")

            text = getattr(self, "_recording_text", "")
            if not text and audio_path:
                # 实时识别无结果，尝试离线转录
                try:
                    text = recorder.transcribe_audio(audio_path)
                    self._logger.info(f"离线转录结果: {text}")
                except Exception as te:
                    self._logger.warning(f"离线转录失败: {te}")

            self._recording_text = ""
            if text:
                self._on_message_send(text, [])
        except Exception as e:
            self._logger.exception(f"停止录音失败: {e}")

    def _on_recording_realtime_result(self, text: str, is_final: bool) -> None:
        """实时识别结果回调"""
        if text:
            self._recording_text = text
            self._logger.debug(f"实时识别: {text}, is_final={is_final}")
