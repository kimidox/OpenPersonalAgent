"""
流式打字机效果 Mixin

负责流式回调设置、打字机效果启停和循环。
"""
from __future__ import annotations

import asyncio
from typing import Any

from logger import get_logger
from ui_flet.state import StreamType


class StreamTypingMixin:
    """
    流式打字机效果 Mixin

    包含流状态回调设置、打字机效果启停和循环等方法。
    通过 self 访问 MainWindow 的属性（如 self._page, self._logger, self._message_list 等）。
    """

    # ==================================================================
    # 流式回调设置
    # ==================================================================

    def _setup_stream_callbacks(self) -> None:
        """设置流状态回调"""
        self._app_state.stream.set_callbacks(
            on_stream_started=self._on_stream_started,
            on_stream_tick=self._on_stream_tick,
            on_stream_completed=self._on_stream_completed,
        )

    def _setup_ui_state_callbacks(self) -> None:
        """设置 UI 状态回调"""
        self._app_state.ui.set_callbacks(
            on_enable_vision_changed=self._on_enable_vision_changed,
        )

    def _on_enable_vision_changed(self, enabled: bool) -> None:
        """视觉能力状态变化回调

        Args:
            enabled: 是否启用视觉能力
        """
        self._logger.info(f"UIState: enable_vision 变更为 {enabled}")

        if self._input_area:
            # 调用 InputArea.set_vision_enabled()，会返回被清除的图片文件列表
            removed_files = self._input_area.set_vision_enabled(enabled)

            # 如果禁用视觉能力且有已上传图片，提示用户
            if not enabled and removed_files:
                self._show_snackbar(
                    f"视觉能力已禁用，已清除 {len(removed_files)} 个图片文件"
                )
                self._logger.info(
                    f"因禁用视觉能力，已清除 {len(removed_files)} 个图片文件"
                )

    def _on_stream_started(self, session_id: str) -> None:
        """流开始回调"""
        self._logger.info(f"[StreamCallback] _on_stream_started 被调用, session_id={session_id}")
        try:
            if not self._message_list:
                self._logger.warning("[StreamCallback] _message_list 为空，跳过处理")
                return

            stream_type = self._app_state.stream.get_current_type()
            if stream_type == StreamType.THINK:
                msg_type = "think"
            elif stream_type == StreamType.TOOL_CALL:
                msg_type = "tool_call"
            else:
                msg_type = "assistant"
            self._logger.info(f"[StreamCallback] 流类型: {stream_type}, 消息类型: {msg_type}")

            # 添加一条空消息卡片，并立即把它登记为本次流的"打字机目标卡片"。
            # 之后无论 LLM 在同一 step 内追加多少 tool_call/tool 卡片，
            # 打字机任务都只更新这张卡片，不会污染后续卡片。
            new_card = self._message_list.add_message(msg_type, "")
            self._current_typing_card = new_card
            self._logger.info(f"[StreamCallback] 已添加空消息卡片, target_card_id={id(new_card)}")

            # 启动打字机效果任务
            self._start_stream_typing()
            self._logger.info("[StreamCallback] 打字机效果已启动")
        except Exception as e:
            self._logger.exception(f"[StreamCallback] _on_stream_started 执行异常: {e}")

    def _on_stream_tick(self, session_id: str, shown_chars: int) -> None:
        """流推进回调（已废弃 UI 副作用）

        历史问题：此处调用 `_message_list.update_last_message(shown_text)`，会把流式
        assistant 文本写到"最后一条卡片"。但多 step 场景下"最后一条卡片"经常不是本次流
        的目标卡片（tool_call/tool 卡片刚被插入到末尾），导致 assistant 文本被错误写进
        tool 卡片，表现为"工具消息卡片和助手消息卡片内容一样"。

        修复后：UI 增量直接由 `typing_loop` 通过闭包内捕获的 `target_card` 驱动，
        此回调仅保留用于调试观测，不再产生任何 UI 副作用。
        """
        self._logger.debug(
            f"[StreamCallback] _on_stream_tick (no-op): session_id={session_id}, shown_chars={shown_chars}"
        )

    def _on_stream_completed(self, session_id: str, token_usage: dict[str, Any] | None) -> None:
        """流完成回调"""
        self._logger.info(f"[StreamCallback] _on_stream_completed 被调用, session_id={session_id}, token_usage={token_usage}")
        try:
            # 先在清除目标卡片之前保留引用——下面 _stop_stream_typing 会清空它
            target_card = self._current_typing_card

            # 停止打字机效果
            self._stop_stream_typing()
            self._logger.info("[StreamCallback] 打字机效果已停止")

            if not self._message_list:
                self._logger.warning("[StreamCallback] _on_stream_completed: _message_list 为空")
                return

            # 确保显示完整文本
            full_text = self._app_state.stream.get_full_text()
            self._logger.info(f"[StreamCallback] 完整文本长度: {len(full_text)}")

            # 关键：直接更新"目标卡片"（即本次流开始时新建的卡片），
            # 而不是 update_last_message。原因：在 tool/base_tool 处理器中，
            # 流的 complete 会在 add_message 之前触发；如果按最后一条卡片更新，
            # 会把 assistant 的最终文本写进刚追加的 tool_call/tool 卡片。
            if target_card is not None:
                target_card.update_content(full_text)
                target_card.finalize_content(token_usage)
                self._logger.info(
                    f"[StreamCallback] 已更新并完成目标卡片 (id={id(target_card)}, length={len(full_text)})"
                )
            else:
                # 目标卡片丢失：放弃写入，而不是回退到 update_last_message。
                # 历史回退路径会调用 update_last_message(full_text)，但多 step 场景下
                # "最后一条卡片"可能是新一轮流刚创建的卡片，写入会造成跨流污染
                # （表现为"工具卡片内容 == 助手卡片内容"）。丢失单条消息比污染更可接受。
                self._logger.warning(
                    f"[StreamCallback] 目标卡片为空，跳过写入 "
                    f"(full_text 长度={len(full_text)})；"
                    f"该情况通常意味着 _on_stream_started 未创建卡片"
                )

            # 同步完整消息到悬浮窗口（Flet overlay）
            if self._floating_chat_window:
                stream_type = self._app_state.stream.get_current_type()
                if stream_type == StreamType.THINK:
                    msg_type = "think"
                elif stream_type == StreamType.TOOL_CALL:
                    msg_type = "tool_call"
                else:
                    msg_type = "assistant"
                self._floating_chat_window.add_message(msg_type, full_text)
                self._logger.info(f"[StreamCallback] 已同步完整消息到悬浮窗口: type={msg_type}, length={len(full_text)}")

            # 同步完整消息到独立悬浮聊天窗口进程（PySide6）
            self._send_to_floating_chat_process(full_text, token_usage)
        except Exception as e:
            self._logger.exception(f"[StreamCallback] _on_stream_completed 执行异常: {e}")

    def _send_to_floating_chat_process(self, content: str, token_usage: dict | None = None) -> None:
        """发送助手回复到悬浮聊天窗口（通过悬浮球进程）"""
        try:
            from ui_flet import main as main_module
            from ui_flet.floating_ball_ipc import MessageType, make_message

            # 使用优化的 IPC 发送函数（批量发送）
            send_ipc_message = getattr(main_module, 'send_ipc_message', None)
            if send_ipc_message is not None:
                send_ipc_message(make_message(MessageType.CHAT_RECEIVE_MESSAGE, content=content))
                self._logger.debug(f"[StreamCallback] 已发送助手回复到悬浮聊天窗口: length={len(content)}")
            else:
                # 回退到原始方式
                _to_ball_queue = getattr(main_module, '_to_ball_queue', None)
                if _to_ball_queue is not None:
                    _to_ball_queue.put(make_message(MessageType.CHAT_RECEIVE_MESSAGE, content=content))
                    self._logger.debug(f"[StreamCallback] 已发送助手回复到悬浮聊天窗口: length={len(content)}")
        except Exception as e:
            self._logger.warning(f"[StreamCallback] 发送助手回复到悬浮聊天窗口失败: {e}")

    def _start_stream_typing(self) -> None:
        """启动打字机效果循环"""
        self._logger.info("[打字机] _start_stream_typing 被调用")

        if self._stream_typing_active:
            self._logger.warning("[打字机] _start_stream_typing: 已经有打字机任务在运行，跳过")
            return

        self._stream_typing_active = True
        # 增加代数：让可能仍在跑的旧任务在下一轮迭代立刻退出。
        # 配合 _stream_typing_active，避免"旧任务被取消后被新任务的 active=True 复活"。
        self._typing_generation += 1
        current_generation = self._typing_generation
        # 在闭包内捕获目标卡片。后续无论 message_list 追加多少 tool_call/tool 卡片，
        # 打字机都只更新这一张卡片，绝不调用 update_last_message。
        target_card = self._current_typing_card
        target_card_id = id(target_card) if target_card is not None else None
        self._logger.info(
            f"[打字机] _stream_typing_active 已设置为 True, "
            f"generation={current_generation}, target_card_id={target_card_id}"
        )

        async def typing_loop() -> None:
            self._logger.info(
                f"[打字机] typing_loop 开始执行, generation={current_generation}, target_card_id={target_card_id}"
            )
            iteration_count = 0

            while self._stream_typing_active and self._typing_generation == current_generation:
                iteration_count += 1
                stream_state = self._app_state.stream

                self._logger.debug(
                    f"[打字机] typing_loop 迭代 #{iteration_count}: is_streaming={stream_state.is_streaming()}, "
                    f"active={self._stream_typing_active}, gen_ok={self._typing_generation == current_generation}"
                )

                if not stream_state.is_streaming():
                    self._logger.info(
                        f"[打字机] typing_loop: 流已停止，退出循环 (迭代 #{iteration_count})"
                    )
                    break

                # 关键修复（脆弱点 A）：目标卡片漂移检测。
                # 闭包内捕获的 target_card 是局部变量，但 buf 每轮从 stream_state 重新取。
                # 如果新一轮流已经在 _on_stream_started 中把 _current_typing_card 替换成
                # 新卡片，本轮 typing_loop 就不该再写旧卡片——否则会把新流的 buffer 文本
                # 错误地写入上一轮已 finalize 的 assistant / tool 卡片，表现为
                # "工具消息卡片和助手消息卡片内容一样"。
                if target_card is not self._current_typing_card:
                    self._logger.info(
                        f"[打字机] typing_loop: 目标卡片已切换"
                        f"（my_target={target_card_id}, "
                        f"current={id(self._current_typing_card) if self._current_typing_card else None}），"
                        f"退出循环 (迭代 #{iteration_count})"
                    )
                    break

                buf = stream_state.get_buffer()
                if buf.is_complete():
                    self._logger.debug(
                        f"[打字机] typing_loop: 缓冲区已完成，等待更多内容 (迭代 #{iteration_count})"
                    )
                    await asyncio.sleep(0.05)
                    continue

                # 手动推进 buffer——直接修改 shown_chars，**不再调用 stream_state.advance_stream()**，
                # 因为 advance_stream 会触发 _on_stream_tick → update_last_message，
                # 在一个 step 内"思考 + 工具调用 + 工具结果 + 下一轮 assistant 文本"混在一起时，
                # 旧任务的最后一次 advance_stream 会把上一次残留的 assistant 文本
                # 写进本轮新增的 tool_call/tool 卡片，表现为"调用工具卡片/工具卡片
                # 重复显示 assistant 文本"。这里只更新本次流的目标卡片。
                next_shown = min(
                    len(buf.full_text),
                    buf.shown_chars + max(1, buf.chars_per_tick),
                )
                buf.shown_chars = next_shown

                if target_card is not None:
                    shown_text = buf.full_text[:next_shown]
                    try:
                        target_card.update_content(shown_text)
                    except Exception as e:
                        self._logger.warning(f"[打字机] 更新目标卡片失败: {e}")

                # 二次检查 generation：即便 active 被新任务置 True，也能立即识别
                if self._typing_generation != current_generation:
                    self._logger.info(
                        f"[打字机] typing_loop: 代数已变更，退出循环 (迭代 #{iteration_count})"
                    )
                    break

                # 控制打字速度
                await asyncio.sleep(0.03)

            self._stream_typing_active = False
            self._logger.info(
                f"[打字机] typing_loop 循环结束，共迭代 {iteration_count} 次, generation={current_generation}"
            )

        try:
            self._logger.info("[打字机] 准备调用 run_task(typing_loop)")
            self._stream_typing_task = self._page.run_task(typing_loop)
            self._logger.info(
                f"[打字机] run_task 已调用，task={self._stream_typing_task}, generation={current_generation}"
            )
        except Exception as e:
            self._logger.warning(f"[打字机] 启动打字机效果失败: {e}")
            self._stream_typing_active = False
            # 失败时让下一次 _start_stream_typing 可以重新启动
            self._typing_generation += 1

    def _stop_stream_typing(self) -> None:
        """停止打字机效果循环"""
        self._logger.info(
            f"[打字机] _stop_stream_typing 被调用, current generation={self._typing_generation}"
        )
        # 关键修复 1：先让代数 +1，让 typing_loop 在下一轮迭代立刻退出，
        # 不再受后续 _start_stream_typing 把 active 重新置 True 的影响。
        self._typing_generation += 1
        # 关键修复 2：立刻清空目标卡片引用，避免 typing_loop 还在飞的最后一帧
        # advance_stream 把残留的 assistant 文本写入本 step 内后续追加的
        # tool_call/tool 卡片（即使 typing_loop 已经"读"了 target_card 的局部变量，
        # 这一步仍可作为防御性兜底）。
        self._current_typing_card = None
        self._stream_typing_active = False
        if self._stream_typing_task and not self._stream_typing_task.done():
            try:
                self._stream_typing_task.cancel()
            except Exception:
                pass
        self._stream_typing_task = None
