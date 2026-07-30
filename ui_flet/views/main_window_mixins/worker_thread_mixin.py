"""
工作线程管理 Mixin

负责 SkillAgent 工作线程的启动、消息处理、停止等。
"""
from __future__ import annotations

import json
import threading

from logger import get_logger
from skill_agent import SKILL_AGENT_AWAITING_USER_REPLY
from ui_flet.state import StreamType, LLMCommunicationState
from ui_flet.views.main_window_mixins._utils import _get_state_display_text, _get_warning_display_text


class WorkerThreadMixin:
    """
    工作线程管理 Mixin

    包含 SkillAgent 工作线程的启动、消息处理、停止等方法。
    通过 self 访问 MainWindow 的属性（如 self._page, self._logger, self._message_list 等）。
    """

    # ==================================================================
    # 工作线程管理
    # ==================================================================

    def _start_skill_agent_worker(self, query: str, conversation_id: str) -> None:
        """启动 SkillAgent 工作线程"""
        # 重置停止事件
        self._stop_event.clear()

        # 设置思考模式状态
        if self.skill_agent and self._input_area:
            self.skill_agent.set_enable_thinking(self._input_area.is_thinking_enabled())

        # 创建并启动工作线程
        self._worker_thread = threading.Thread(
            target=self._skill_agent_worker_thread,
            args=(query, conversation_id),
            name=f"skill-agent-worker-{conversation_id[:8]}",
            daemon=True,
        )
        self._worker_thread.start()

        self._logger.info(f"启动工作线程: {conversation_id}")

    def _skill_agent_worker_thread(self, query: str, conversation_id: str) -> None:
        """SkillAgent 工作线程"""
        try:
            # 设置会话 ID
            if self.skill_agent:
                self.skill_agent.set_conversation_id(conversation_id)

            # 定义日志回调函数
            def log_callback(message: str, msg_type: str) -> None:
                # 检查是否被请求停止
                if self._stop_event.is_set():
                    return

                # 在主线程中更新 UI
                self._page.run_task(self._handle_worker_message, message, msg_type, conversation_id)

            # 调用 SkillAgent
            result = self.skill_agent.run(
                query,
                log_callback=log_callback,
                stop_check_callback=self._stop_event.is_set,
            )

            # 处理完成
            self._page.run_task(self._handle_worker_finished, result, conversation_id)

        except Exception as e:
            self._logger.exception(f"工作线程执行失败: {e}")
            # 处理错误
            self._page.run_task(self._handle_worker_finished, f"执行出错: {e}", conversation_id)

    async def _handle_worker_message(self, message: str, msg_type: str, conversation_id: str) -> None:
        """处理工作线程的消息（在主线程中运行）"""
        # 添加调试日志：确认消息是否被接收
        self._logger.debug("[_handle_worker_message] 收到消息: type=%s, conversation_id=%s, content前50字=%s",
                           msg_type, conversation_id[:8] + "...", message[:50] if message else "(空)")

        # 检查是否为当前会话
        current_cid = self._app_state.session.get_current_conversation()
        if current_cid != conversation_id:
            self._logger.debug("[_handle_worker_message] 非当前会话，跳过处理: current_cid=%s", current_cid[:8] + "..." if current_cid else "(空)")
            return

        # 根据消息类型处理
        if msg_type == "assistant":
            # 流式助手消息
            self._handle_stream_message(message, "assistant", conversation_id)
            # 注意：不在此处同步到悬浮窗口，流式消息已在 _handle_stream_message 中处理
        elif msg_type == "think":
            # 思考消息
            self._handle_stream_message(message, "think", conversation_id)
            # 注意：不在此处同步到悬浮窗口，流式消息已在 _handle_stream_message 中处理
        elif msg_type == "tool_call":
            # 工具调用流式消息（新增）
            self._handle_stream_message(message, "tool_call", conversation_id)
            # 注意：不在此处同步到悬浮窗口，流式消息已在 _handle_stream_message 中处理
        elif msg_type == "tool":
            # 工具调用消息（只在主窗口显示）
            # 关键修复：必须先 complete 当前流，再添加 tool_call 卡片。
            # 否则打字机任务仍会继续运行，把 stream buffer 累积的 assistant
            # 文本通过 update_last_message 写入新创建的 tool_call 卡片，
            # 同时下一个 step 的 LLM 流来时 stream_state.is_streaming() 仍为
            # True，会走 append_to_stream 分支造成 buffer 跨 step 累积，
            # 最终导致多个"调用工具"卡片重复显示流式 assistant 文本。
            stream_state = self._app_state.stream
            if stream_state.is_streaming():
                stream_state.complete_stream()
            if self._message_list:
                self._message_list.add_message("tool_call", message)
        elif msg_type == "base_tool":
            # 基础工具结果（只在主窗口显示）
            # 同样需要先 complete 当前流，避免 typing 写入新的 tool 卡片
            stream_state = self._app_state.stream
            if stream_state.is_streaming():
                stream_state.complete_stream()
            if self._message_list:
                self._message_list.add_message("tool", message)
        elif msg_type == "token_usage":
            # Token 使用信息
            self._handle_token_usage(message, conversation_id)
            # 同步到悬浮窗口
            if self._floating_chat_window:
                try:
                    token_usage = json.loads(message)
                    self._floating_chat_window.finalize_last_message(token_usage)
                except Exception as e:
                    self._logger.debug(f"解析 token_usage JSON 失败: {e}")
        elif msg_type == "await_user":
            # 等待用户回复
            self._handle_await_user(message, conversation_id)
            # 同步到悬浮窗口
            if self._floating_chat_window:
                try:
                    spec = json.loads(message)
                    self._floating_chat_window.show_await_user_prompt(
                        spec,
                        on_confirm_send=lambda t: self._on_floating_chat_send(t)
                    )
                except Exception as e:
                    self._logger.debug(f"解析 await_user JSON 失败: {e}")
        elif msg_type == "mode":
            # 模式消息（用于显示徽章）
            pass  # 可以在这里添加模式徽章显示
        elif msg_type == "plan":
            # 计划消息
            # 同样需要先 complete 当前流，避免 typing 写入新的 assistant 卡片
            stream_state = self._app_state.stream
            if stream_state.is_streaming():
                stream_state.complete_stream()
            if self._message_list:
                self._message_list.add_message("assistant", message)
            # 同步到悬浮窗口
            if self._floating_chat_window:
                self._floating_chat_window.add_message("assistant", message)
        elif msg_type == "llm_state_update":
            # LLM通信状态更新
            state_data = json.loads(message)
            # 更新前端状态
            new_state = LLMCommunicationState(
                state=state_data.get("state", "IDLE"),
                timestamp=state_data.get("timestamp", 0.0),
                model=state_data.get("model"),
                session_id=state_data.get("session_id"),
                duration_ms=state_data.get("duration_ms", 0),
                error_message=state_data.get("error_message")
            )
            self._app_state.llm_communication = new_state

            # 更新状态指示器UI
            if self._llm_status_indicator:
                self._llm_status_indicator.update_state(new_state)

            # 在控制台日志中显示状态信息
            state_display = _get_state_display_text(state_data.get("state", "IDLE"))
            duration_ms = state_data.get("duration_ms", 0)
            self._logger.info(f"[LLM通信] {state_display} (耗时: {duration_ms}ms)")
        elif msg_type == "llm_state_warning":
            # LLM通信超时告警
            try:
                warning_data = json.loads(message)
                warning_type = warning_data.get("warning_type", "unknown")
                state = warning_data.get("state", "UNKNOWN")
                duration_ms = warning_data.get("duration_ms", 0)
                warning_msg = warning_data.get("message", "")

                # 转换为友好显示文本
                display_text = _get_warning_display_text(warning_type, state, duration_ms)

                # 记录告警日志（WARNING级别）
                self._logger.warning(
                    f"[LLM告警] {display_text} (详情: {warning_msg})"
                )

                # 可选：在UI中显示告警通知（SnackBar）
                # 注意：SnackBar 可能会干扰用户操作，建议仅在严重超时时启用
                # self._page.snack_bar = ft.SnackBar(
                #     content=ft.Text(display_text, color=ft.Colors.WHITE),
                #     bgcolor=ft.Colors.ORANGE_700,
                #     duration=3000,
                # )
                # self._page.snack_bar.open = True

            except json.JSONDecodeError:
                self._logger.error(f"[LLM告警] 解析告警数据失败: {message}")
            except Exception as e:
                self._logger.exception(f"[LLM告警] 处理告警异常: {e}")
        else:
            # 其他消息类型（info, tool_call等）
            if self._message_list and msg_type in ["info", "tool_call"]:
                pass  # 暂不处理

        # 更新页面
        self._page.update()

    async def _handle_worker_finished(self, result: str, conversation_id: str) -> None:
        """处理工作线程完成"""
        # 重置 UI 状态
        self._app_state.ui.set_task_running(False)

        # 恢复发送按钮为正常状态
        if self._input_area:
            self._input_area.set_inference_running(False)

        # 检查是否为当前会话
        current_cid = self._app_state.session.get_current_conversation()
        if current_cid != conversation_id:
            return

        # 处理结果
        if result == SKILL_AGENT_AWAITING_USER_REPLY:
            # 等待用户回复，不添加额外消息
            self._logger.info("SkillAgent 等待用户回复")
        else:
            # 非等待状态，清除等待用户卡片
            if self._await_user_card:
                self._await_user_card.clear_prompt()

            # 完成当前流（如果还在进行）
            stream_state = self._app_state.stream
            if stream_state.is_streaming():
                stream_state.complete_stream()

            # 仅在流**从未启动**时把 result 补成一张 assistant 卡片。
            # 注意：不能用 `not is_streaming()`，因为 is_streaming() 在流
            # 被 complete_stream 关闭后也会变 False（_is_completed=True），
            # 那样会把已经流式渲染过的 result 重复再写一张卡。
            if (
                result
                and result.strip()
                and stream_state.get_current_type() == StreamType.NONE
            ):
                if self._message_list:
                    self._message_list.add_message("assistant", result)

        # 清理流状态
        self._app_state.stream.clear()

        # 更新页面
        self._page.update()

        self._logger.info(f"工作线程完成: {conversation_id}")

    def _handle_stream_message(self, message: str, msg_type: str, conversation_id: str) -> None:
        """处理流式消息：将内容追加到流缓冲区，由打字机效果异步显示"""
        # 添加调试日志：确认流状态是否正确设置
        self._logger.debug("[_handle_stream_message] 收到流消息: type=%s, conversation_id=%s, content前50字=%s",
                           msg_type, conversation_id[:8] + "...", message[:50] if message else "(空)")

        if not self._message_list:
            self._logger.debug("[_handle_stream_message] message_list 为空，跳过处理")
            return

        stream_state = self._app_state.stream

        # 检查是否需要切换流类型
        current_stream_type = stream_state.get_current_type()
        if msg_type == "think":
            new_stream_type = StreamType.THINK
        elif msg_type == "tool_call":
            new_stream_type = StreamType.TOOL_CALL
        else:
            new_stream_type = StreamType.CONTENT

        self._logger.debug("[_handle_stream_message] 流状态: current_type=%s, new_type=%s, is_streaming=%s",
                           current_stream_type, new_stream_type, stream_state.is_streaming())

        if current_stream_type != new_stream_type or not stream_state.is_streaming():
            # 完成之前的流
            if stream_state.is_streaming():
                self._logger.debug("[_handle_stream_message] 完成之前的流: type=%s", current_stream_type)
                stream_state.complete_stream()

            # 开始新的流
            self._logger.debug("[_handle_stream_message] 开始新流: type=%s", new_stream_type)
            stream_state.start_stream(conversation_id, new_stream_type, message)
        else:
            # 追加到现有流
            self._logger.debug("[_handle_stream_message] 追加到现有流: type=%s", new_stream_type)
            stream_state.append_to_stream(message)

    def _handle_token_usage(self, token_usage_json: str, conversation_id: str) -> None:
        """处理 Token 使用信息"""
        try:
            token_usage = json.loads(token_usage_json)

            # 完成流并附带 token 信息
            stream_state = self._app_state.stream
            if stream_state.is_streaming():
                stream_state.complete_stream(token_usage)

        except Exception as e:
            self._logger.exception(f"处理 Token 使用信息失败: {e}")

    def _is_awaiting_user_reply(self) -> bool:
        """检查当前是否处于等待用户回复状态"""
        return self._await_user_card is not None and self._await_user_card.has_active_prompt()

    def _handle_await_user(self, spec_json: str, conversation_id: str) -> None:
        """处理等待用户回复"""
        try:
            spec = json.loads(spec_json)

            # 完成当前的流
            stream_state = self._app_state.stream
            if stream_state.is_streaming():
                stream_state.complete_stream()

            # 显示等待用户回复卡片
            current_cid = self._app_state.session.get_current_conversation()
            if current_cid == conversation_id and self._await_user_card:
                self._await_user_card.show_prompt(
                    spec,
                    on_confirm_send=lambda text: self._on_message_send(text, []),
                )

            self._logger.info(f"等待用户回复: {spec.get('question', '')}")

        except Exception as e:
            self._logger.exception(f"处理等待用户回复失败: {e}")

    def request_stop_worker(self) -> None:
        """请求停止工作线程"""
        if self._worker_thread and self._worker_thread.is_alive():
            self._stop_event.set()
            if self.skill_agent:
                self.skill_agent.request_stop()
            self._logger.info("请求停止工作线程")

    def is_agent_busy(self) -> bool:
        """Agent 工作线程是否正在运行（供 TaskScheduler 触发前检查，避免线程竞争）"""
        return bool(self._worker_thread and self._worker_thread.is_alive())
