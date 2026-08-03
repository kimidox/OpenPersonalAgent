"""
会话管理 Mixin

负责会话切换、新建、删除、重命名、消息加载等。
"""
from __future__ import annotations

import json

import flet as ft

from logger import get_logger
from ui_flet.theme import ThemeManager
from ui_flet.viewmodels.conversation_viewmodel import ConversationViewModel
from ui_flet.viewmodels.agent_viewmodel import AgentViewModel


class ConversationManagerMixin:
    """
    会话管理 Mixin

    包含会话切换、新建、删除、重命名、消息加载等方法。
    通过 self 访问 MainWindow 的属性（如 self._page, self._logger, self._message_list 等）。
    """

    # ==================================================================
    # 会话管理
    # ==================================================================

    def _handle_conversation_changed(self, conversation_id: str) -> None:
        """
        会话切换回调

        Args:
            conversation_id: 会话ID
        """
        self._logger.info(f"切换到会话: {conversation_id}")
        # 切换到指定会话
        self._switch_to_conversation(conversation_id)

    def _handle_new_conversation(self) -> None:
        """创建新会话回调"""
        self._logger.info("创建新会话")

        # 检查是否有正在运行的任务
        if self._agent_vm.is_worker_alive():
            self._logger.warning("当前仍有对话在执行，请结束后再新建会话")
            # 可以添加一个提示对话框
            return

        # 创建新会话
        self._create_new_conversation()

    def _handle_delete_conversation(self, conversation_id: str) -> None:
        """
        删除会话回调

        Args:
            conversation_id: 会话ID
        """
        self._logger.info(f"删除会话: {conversation_id}")

        # 检查是否有正在运行的任务
        if self._agent_vm.is_worker_alive():
            self._logger.warning("该会话正在执行中，请结束后再删除")
            self._show_snackbar("该会话正在执行中，请结束后再删除", error=True)
            return

        # 检查是否只剩一个会话
        if self._app_state.session.conversation_count() < 1:
            self._logger.warning("至少保留一个会话")
            self._show_snackbar("至少保留一个会话", error=True)
            return

        # 记录当前会话 ID（用于后续判断是否需要清空消息列表）
        current_cid = self._app_state.session.get_current_conversation()
        is_current_conversation = current_cid == conversation_id

        # Step 1: 如果删除的是当前会话，先切换到另一个会话
        if is_current_conversation:
            all_sessions = self._app_state.session.get_all_conversations()
            for session in all_sessions:
                if session.conversation_id != conversation_id:
                    self._switch_to_conversation(session.conversation_id)
                    break

        # Step 2: 先执行数据库删除（确保持久化成功后再更新 UI）
        try:
            if self._memory:
                self._memory.clear_conversation(conversation_id)
            self._logger.info(f"数据库删除成功: {conversation_id}")
        except Exception as e:
            self._logger.exception(f"数据库删除失败: {e}")
            self._show_snackbar("删除会话失败，请重试", error=True)
            # 数据库删除失败，不更新 UI，保持原状态
            return

        # Step 3: 数据库删除成功后，更新 UI 和状态
        # 更新侧边栏
        if self._conversation_sidebar:
            self._conversation_sidebar.remove_conversation(conversation_id)

        # 从状态管理中移除
        self._app_state.session.remove_conversation(conversation_id)

        # 清空消息列表（如果删除的是当前会话）
        if is_current_conversation and self._message_list:
            self._message_list.clear()

        self._logger.info(f"已删除会话: {conversation_id}")
        self._show_snackbar("会话已删除")

    def _show_snackbar(self, message: str, error: bool = False) -> None:
        """
        显示提示消息

        Args:
            message: 提示消息内容
            error: 是否为错误消息
        """
        colors = ThemeManager().get_color_scheme()
        self._page.snack_bar = ft.SnackBar(
            content=ft.Text(message, color=colors.text_on_primary),
            bgcolor=colors.error if error else colors.success,
        )
        self._page.snack_bar.open = True
        self._page.update()

    def _handle_rename_conversation(self, conversation_id: str, new_title: str) -> None:
        """
        重命名会话回调

        Args:
            conversation_id: 会话ID
            new_title: 新的会话标题
        """
        self._logger.info(f"重命名会话: {conversation_id} -> {new_title}")

        try:
            # 更新状态管理中的标题
            self._app_state.session.update_conversation_title(
                conversation_id, new_title
            )

            # 持久化到数据库
            if self._memory:
                self._memory.update_conversation_title(conversation_id, new_title)

            # 同步更新侧边栏 UI
            if self._conversation_sidebar:
                self._conversation_sidebar.update_conversation_title(
                    conversation_id, new_title
                )

            self._logger.info(f"已重命名会话: {conversation_id}")

        except Exception as e:
            self._logger.exception(f"重命名会话失败: {e}")

    # ==================== 消息复制和朗读 ====================

    def _on_message_copy(self, text: str) -> None:
        """
        消息复制回调

        Args:
            text: 要复制的文本
        """
        self._page.set_clipboard(text)
        self._logger.info("消息已复制到剪贴板")

    def _on_message_speak(self, text: str) -> None:
        """
        消息朗读回调

        Args:
            text: 要朗读的文本
        """
        self._logger.info(f"开始朗读消息: {text[:50]}...")
        # TODO: 实现 TTS 朗读功能

    # ==================== 会话管理方法 ====================

    def _create_new_conversation(self) -> str | None:
        """创建新会话并返回会话ID"""
        vm: ConversationViewModel = self._conversation_vm
        if not vm.is_available:
            self._logger.error("SkillAgent 未初始化，无法创建会话")
            return None

        try:
            # 通过 ViewModel 创建新会话
            result = vm.start_new_conversation()
            if result is None:
                return None
            conversation_id, title = result
            self._logger.info(f"创建新会话: {conversation_id}")

            # 添加到状态管理
            # 注意：session.add_conversation 会触发 SessionState 的
            # on_conversation_added 回调，ConversationSidebar 已在
            # _setup_state_callbacks 中注册该回调并自动添加侧边栏项。
            # 因此这里**不能**再手动调用 sidebar.add_conversation，
            # 否则会出现重复项（与 issue "新增会话创建两个" 对应）。
            self._app_state.session.add_conversation(
                conversation_id,
                title=title or f"新会话-{conversation_id[:5]}",
                pending_db_history=False,
            )

            # 切换到新会话（同时负责把新会话标记为选中）
            self._switch_to_conversation(conversation_id)

            return conversation_id

        except Exception as e:
            self._logger.exception(f"创建新会话失败: {e}")
            return None

    def _switch_to_conversation(self, conversation_id: str) -> None:
        """切换到指定会话"""
        if not conversation_id:
            return

        # 设置当前会话
        self._app_state.session.set_current_conversation(conversation_id)

        # 通过 ViewModel 设置当前会话
        self._conversation_vm.set_conversation_id(conversation_id)

        # 更新侧边栏选中状态
        if self._conversation_sidebar:
            self._conversation_sidebar.set_selected_conversation(conversation_id)

        # 清空消息列表（切换会话时必须清除旧消息，否则会追加到旧消息后面）
        # 注意：update_ui=False —— 不立即触发 page.update()，避免 Flutter 在
        # "清空→逐条添加"的中间布局状态时给 tight=True 的 Column 分配错误
        # 的宽度约束（表现为切换会话后气泡变宽）。全部消息添加完后统一更新。
        if self._message_list:
            self._message_list.clear_all(update_ui=False)

        # 标记为需要重新加载，确保 _load_conversation_messages 不会因
        # pending_db_history=False 而跳过
        self._app_state.session.set_pending_db_history(conversation_id, True)

        # 加载会话历史消息（内部 add_message 使用 update_ui=False）
        self._load_conversation_messages(conversation_id)

        # 清除等待用户回复卡片
        if self._await_user_card:
            self._await_user_card.clear_prompt()

        # 统一触发一次 UI 更新（清空 + 加载全部完成后）
        self._page.update()

        self._logger.info(f"切换到会话: {conversation_id}")

    def _load_conversation_messages(self, conversation_id: str) -> None:
        """加载会话的历史消息（分页加载，默认加载最近10条）"""
        vm: ConversationViewModel = self._conversation_vm
        if not vm.is_available or not self._message_list:
            return

        try:
            # 检查是否需要加载历史
            if not self._app_state.session.is_pending_db_history(conversation_id):
                return

            # 标记为已加载
            self._app_state.session.set_pending_db_history(conversation_id, False)

            # 分页加载配置
            PAGE_SIZE = 10

            # 获取总消息数（用于判断是否有更多消息）
            all_records = vm.message_records_for_conversation(conversation_id)
            total_count = len(all_records)

            # 只加载最近 PAGE_SIZE 条消息
            if total_count > PAGE_SIZE:
                records = all_records[-PAGE_SIZE:]
                has_more = True
                # 记录已加载的偏移量（从后往前数，已加载了 PAGE_SIZE 条）
                self._loaded_message_offset = PAGE_SIZE
                self._logger.info(
                    f"会话 {conversation_id} 共 {total_count} 条消息，"
                    f"分页加载最近 {PAGE_SIZE} 条"
                )
            else:
                records = all_records
                has_more = False
                self._loaded_message_offset = total_count

            # 重放消息
            for record in records:
                role = str(record.get("role", ""))
                raw_content = record.get("content")

                # 通过 ViewModel 解析消息内容
                content = ConversationViewModel.parse_message_content(raw_content)
                # 保留日志：记录多模态情况
                if isinstance(raw_content, list):
                    image_count = sum(1 for item in raw_content if isinstance(item, dict) and item.get("type") == "image_url")
                    self._logger.info(f"检测到多模态历史消息 {role}，图片数量: {image_count}")
                elif isinstance(content, list):
                    image_count = sum(1 for item in content if isinstance(item, dict) and item.get("type") == "image_url")
                    self._logger.info(f"解析多模态历史消息 {role} 成功，图片数量: {image_count}")

                metadata = record.get("metadata", {}) or {}

                # 通过 ViewModel 分类消息类型
                msg_type = ConversationViewModel.classify_message_type(role, metadata)
                if msg_type is None:
                    continue

                # 关键修复：tool_call 卡片在持久化时 content 为空（to_llm_dict
                # 会把空字符串规范化为 None），从数据库加载时如果不补内容，
                # 卡片正文会显示为空（甚至被某些 str 路径变成 "None"）。
                # 运行时 `_handle_worker_message` 处理 log_callback("tool", ...) 时，
                # 传入的是 "调用工具 `<fname>` · {args}" 这种可读格式。
                # 这里从 metadata 中还原出同样的展示文本，保持加载历史与
                # 实时会话的视觉一致。
                if msg_type == "tool_call":
                    content = ConversationViewModel.build_tool_call_display_text(metadata)

                # 添加消息到列表
                # update_ui=False：批量加载时不逐条触发 page.update()，
                # 由 _switch_to_conversation 在全部加载完后统一更新
                card = self._message_list.add_message(msg_type, content, update_ui=False)
                # 历史消息直接 finalize，使悬停时能显示复制按钮
                if card is not None:
                    card.finalize_content()

            # 方案 A 配合修复：检测"半截会话"。
            # 正常结束的对话，最后一条 DB 消息必然是 assistant：
            # - 任务型对话走 finish，最后一条是 finish(message=...) 的 assistant 总结
            # - 闲聊型对话走 _direct_reply，最后一条也是 assistant
            # 若最后一条是 tool_call / tool，说明会话异常中断（程序崩溃 / 用户强停 /
            # 工具调用后未走完 finish 收尾），追加一条提示卡片告知用户。
            if records:
                last_role = str(records[-1].get("role", ""))
                last_meta = records[-1].get("metadata", {}) or {}
                last_type = last_meta.get("type", "")
                # assistant + think 不算正常结束（think 是中间态）
                is_abnormal_end = (
                    last_role == "tool"
                    or (last_role == "assistant" and last_type == "tool_call")
                    or (last_role == "assistant" and last_type == "think")
                )
                if is_abnormal_end and self._message_list:
                    if last_role == "tool":
                        hint = (
                            "⚠️ 本会话在工具执行后异常中断（缺少助手最终回复）。"
                            "如需继续，请重新提问或追问上一轮结果。"
                        )
                    elif last_type == "tool_call":
                        hint = (
                            "⚠️ 本会话在调用工具后异常中断（缺少工具执行结果与助手回复）。"
                            "如需继续，请重新提问。"
                        )
                    else:
                        hint = (
                            "⚠️ 本会话在助手思考阶段异常中断。如需继续，请重新提问。"
                        )
                    self._message_list.add_message("tool", hint, update_ui=False)
                    self._logger.warning(
                        f"检测到半截会话 {conversation_id}：last_role={last_role}, last_type={last_type}"
                    )

            # 显示"加载更多"按钮（如果有更多历史消息）
            if has_more and self._message_list:
                self._message_list.show_load_more_button(True)

        except Exception as e:
            self._logger.exception(f"加载会话消息失败: {e}")

    def _load_more_messages(self) -> None:
        """加载更多历史消息（分页加载）"""
        vm: ConversationViewModel = self._conversation_vm
        if not vm.is_available or not self._message_list:
            return

        conversation_id = self._app_state.session.get_current_conversation()
        if not conversation_id:
            return

        try:
            PAGE_SIZE = 10
            current_offset = getattr(self, '_loaded_message_offset', 0)

            # 获取所有消息记录
            all_records = vm.message_records_for_conversation(conversation_id)
            total_count = len(all_records)

            # 计算要加载的消息范围
            # 从后往前数，已加载了 current_offset 条，再加载 PAGE_SIZE 条
            end_index = total_count - current_offset
            start_index = max(0, end_index - PAGE_SIZE)

            if start_index >= end_index:
                # 没有更多消息了
                self._message_list.hide_load_more_button()
                return

            # 获取要加载的消息
            records_to_load = all_records[start_index:end_index]

            # 处理消息
            messages_to_insert = []
            for record in records_to_load:
                role = str(record.get("role", ""))
                raw_content = record.get("content")

                # 通过 ViewModel 解析消息内容
                content = ConversationViewModel.parse_message_content(raw_content)

                metadata = record.get("metadata", {}) or {}

                # 通过 ViewModel 分类消息类型
                msg_type = ConversationViewModel.classify_message_type(role, metadata)
                if msg_type is None:
                    continue

                # 处理 tool_call 消息
                if msg_type == "tool_call":
                    content = ConversationViewModel.build_tool_call_display_text(metadata)

                messages_to_insert.append((msg_type, content))

            # 在顶部插入消息
            if messages_to_insert:
                self._message_list.insert_messages_at_top(messages_to_insert)
                # 更新偏移量
                self._loaded_message_offset = current_offset + len(messages_to_insert)

                # 检查是否还有更多消息
                if self._loaded_message_offset >= total_count:
                    self._message_list.hide_load_more_button()
                    self._logger.info(f"已加载所有 {total_count} 条消息")
                else:
                    self._message_list.show_load_more_button(True)
                    self._logger.info(
                        f"已加载 {self._loaded_message_offset}/{total_count} 条消息"
                    )

        except Exception as e:
            self._logger.exception(f"加载更多消息失败: {e}")
            # 隐藏按钮，避免重复点击
            if self._message_list:
                self._message_list.hide_load_more_button()

    def _load_initial_conversations_sync(self) -> None:
        """加载初始会话列表"""
        vm: ConversationViewModel = self._conversation_vm
        if not vm.is_available or not self._conversation_sidebar:
            return

        try:
            # 获取所有会话
            all_sessions = [
                c for c in vm.list_saved_conversations()
                if (c.conversation_id or "").strip()
            ]

            # 使用单次查询获取所有有消息的会话 ID
            conversation_ids_with_messages = (
                self._memory.get_conversations_with_messages()
                if self._memory else set()
            )

            # 筛选有消息的会话
            sessions_with_messages = [
                conv for conv in all_sessions
                if (conv.conversation_id or "").strip() in conversation_ids_with_messages
            ]

            # 如果没有会话，创建新会话
            if not sessions_with_messages:
                self._create_new_conversation()
                return

            # 加载会话到状态管理
            self._app_state.session.load_from_conversations(sessions_with_messages)

            # 加载到侧边栏
            self._conversation_sidebar.load_conversations(sessions_with_messages)

            # 切换到第一个会话
            first_cid = (sessions_with_messages[0].conversation_id or "").strip()
            if first_cid:
                self._switch_to_conversation(first_cid)

            self._logger.info(f"加载了 {len(sessions_with_messages)} 个会话")

        except Exception as e:
            self._logger.exception(f"加载初始会话失败: {e}")
            # 创建新会话作为降级方案
            self._create_new_conversation()

    async def _load_initial_conversations_async(self) -> None:
        """异步加载初始会话"""
        try:
            self._logger.info("开始异步加载初始会话")

            # 显示加载状态
            if self._conversation_sidebar:
                self._conversation_sidebar.show_loading()

            # 在后台线程执行同步操作
            import asyncio
            await asyncio.get_event_loop().run_in_executor(
                None, self._load_initial_conversations_sync
            )

            # 隐藏加载状态
            if self._conversation_sidebar:
                self._conversation_sidebar.hide_loading()

            self._logger.info("初始会话加载完成")
        except Exception:
            self._logger.exception("异步加载初始会话失败")
            # 发生异常时也要隐藏加载状态
            if self._conversation_sidebar:
                self._conversation_sidebar.hide_loading()
