from __future__ import annotations

import json
import re
import secrets
import sys
from html import escape
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QPointF, Qt, QThread, QTimer, Signal, QSize
from PySide6.QtGui import QColor, QFont, QIcon, QMouseEvent, QPainter, QPen, QPixmap, QTextCursor
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QCheckBox,
    QDialog,
    QButtonGroup,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QStyleFactory,
    QTabBar,
    QTabWidget,
    QToolButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import config
from executor import Executor
from llm import get_chat_model
from llm.llm_config_manager import get_current_config, set_config, reset_to_default, LLMConfig
from memory import SqliteMemory
from skill_agent import SKILL_AGENT_AWAITING_USER_REPLY, SkillAgent
from skill_agent_preferences import load_disabled_skill_ids, save_disabled_skill_ids


def _load_ui_style_sections() -> dict[str, str]:
    """从 ui_skill_agent_styles.css 解析 /* === section:<id> === */ 分块为字典。"""
    css_path = Path(__file__).with_name("ui_skill_agent_styles.css")
    raw = css_path.read_text(encoding="utf-8")
    parts = re.split(r"/\* === section:(\w+) === \*/", raw)
    if len(parts) < 2:
        return {}
    out: dict[str, str] = {}
    for i in range(1, len(parts), 2):
        key = parts[i]
        body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        out[key] = body
    return out


_UI_STYLES = _load_ui_style_sections()

_INPUT_PLACEHOLDER_DEFAULT = "输入业务问题后发送…"
_INPUT_PLACEHOLDER_AWAIT_USER = "Agent 正在等待你的补充回复…"

# 助手气泡：按字符逐步显示（模型仍是一次性返回，此处为界面流式效果）
_STREAM_TIMER_MS = 22
_STREAM_CHARS_PER_TICK = 2

# 待回复卡片内选项区最大高度（超出可滚动），避免选项过多时挤掉「确定」按钮
_AWAIT_USER_SCROLL_MAX_RATIO = 0.32
_AWAIT_USER_SCROLL_MIN_PX = 200
_AWAIT_USER_SCROLL_MAX_PX = 420

_TAB_CLOSE_BTN_OBJECT_NAME = "skillAgentTabCloseButton"
_TAB_CLOSE_ICON: QIcon | None = None


def _tab_close_pixmap(px: int, color: QColor) -> QPixmap:
    """绘制与主界面一致的细线 ×（避免 QStyle 系统图标灰框、风格割裂）。"""
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(color)
    pen.setWidthF(max(1.35, px * 0.105))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    m = px * 0.3
    painter.drawLine(QPointF(m, m), QPointF(px - m, px - m))
    painter.drawLine(QPointF(px - m, m), QPointF(m, px - m))
    painter.end()
    return pm


def _tab_close_icon() -> QIcon:
    global _TAB_CLOSE_ICON
    if _TAB_CLOSE_ICON is None:
        # 与 ui_skill_agent_styles.css 中 slate / 主色体系一致
        base = QColor("#64748b")
        ico = QIcon()
        for d in (16, 20, 24):
            ico.addPixmap(_tab_close_pixmap(d, base))
        _TAB_CLOSE_ICON = ico
    return _TAB_CLOSE_ICON


class _ClickableChoiceLabel(QLabel):
    """与 `QRadioButton` 配对：点击换行文案时选中该选项。"""

    def __init__(self, text: str, radio: QRadioButton) -> None:
        super().__init__(text)
        self._radio = radio
        self.setWordWrap(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("color: #374151; background: transparent;")

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        self._radio.setChecked(True)
        super().mousePressEvent(event)


def _apply_chat_view_style(chat: QTextEdit) -> None:
    chat.setReadOnly(True)
    chat.setFont(QFont("Microsoft YaHei", 10))
    chat.setAcceptRichText(True)
    chat.setPlaceholderText("对话记录将显示在这里…")
    chat.setStyleSheet(_UI_STYLES["chat_view_qtextedit"])
    chat.setMinimumHeight(200)
    chat.document().setDefaultStyleSheet(_UI_STYLES["chat_document_default"])


class ChatSessionTab(QWidget):
    """单个会话标签页：聊天记录 + 底部「待你回复」交互区（问题 + 单选建议项）。"""

    def __init__(self, conversation_id: str, *, pending_db_history: bool = False) -> None:
        super().__init__()
        self.conversation_id = (conversation_id or "").strip()
        self.pending_db_history = pending_db_history
        self.chat_view = QTextEdit()
        _apply_chat_view_style(self.chat_view)
        if pending_db_history:
            self.chat_view.setPlaceholderText("请点击本会话标签，加载数据库中的历史聊天记录…")

        self._await_user_card = QFrame()
        self._await_user_card.setObjectName("skillAgentAwaitUserCard")
        self._await_user_card.setVisible(False)
        self._await_user_card.setStyleSheet(_UI_STYLES.get("await_user_card_frame", ""))
        self._await_inner = QVBoxLayout(self._await_user_card)
        self._await_inner.setContentsMargins(12, 10, 12, 10)
        self._await_inner.setSpacing(8)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(self.chat_view, stretch=1)
        lay.addWidget(self._await_user_card, stretch=0)

    def has_active_await_user_prompt(self) -> bool:
        """底部「待你回复」交互区是否正在展示（用于恢复挂起会话时避免重复搭建）。"""
        return self._await_user_card.isVisible()

    def clear_await_user_ui(self) -> None:
        self._await_user_card.setVisible(False)
        while self._await_inner.count():
            item = self._await_inner.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def show_await_user_prompt(
        self,
        spec: dict[str, Any],
        *,
        on_confirm_send: Callable[[str], None] | None = None,
    ) -> None:
        """首行展示问题；若有 choices 则下列单选组 +「确定」：选中后启用确定，点击后直接发送该文案。"""
        self.clear_await_user_ui()
        question = str(spec.get("question") or "").strip()
        context = str(spec.get("context") or "").strip()
        choices_raw = spec.get("choices")
        choices: list[str] = []
        if isinstance(choices_raw, list):
            for c in choices_raw:
                if c is None:
                    continue
                s = str(c).strip()
                if s:
                    choices.append(s)

        q_lab = QLabel(question or "（模型未提供具体问题）")
        q_lab.setObjectName("skillAgentAwaitUserQuestion")
        q_lab.setWordWrap(True)

        if choices:
            scroll = QScrollArea()
            scroll.setObjectName("skillAgentAwaitUserScroll")
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            scr = QApplication.primaryScreen()
            scr_h = scr.availableGeometry().height() if scr is not None else 900
            scroll.setMaximumHeight(
                max(
                    _AWAIT_USER_SCROLL_MIN_PX,
                    min(_AWAIT_USER_SCROLL_MAX_PX, int(scr_h * _AWAIT_USER_SCROLL_MAX_RATIO)),
                )
            )
            scroll.setMinimumHeight(100)
            scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

            scroll_inner = QWidget()
            s_layout = QVBoxLayout(scroll_inner)
            s_layout.setContentsMargins(0, 0, 6, 0)
            s_layout.setSpacing(8)
            s_layout.addWidget(q_lab)
            if context:
                ctx_lab = QLabel(context)
                ctx_lab.setObjectName("skillAgentAwaitUserHint")
                ctx_lab.setWordWrap(True)
                s_layout.addWidget(ctx_lab)
            hint = QLabel("请选择一个建议回答，点击下方「确定」将立即发送（无需再点发送）：")
            hint.setObjectName("skillAgentAwaitUserHint")
            hint.setWordWrap(True)
            s_layout.addWidget(hint)

            group = QButtonGroup(self._await_user_card)
            group.setExclusive(True)
            selected: dict[str, str | None] = {"text": None}
            for label in choices:
                row = QWidget()
                row_l = QHBoxLayout(row)
                row_l.setContentsMargins(0, 0, 0, 0)
                row_l.setSpacing(8)
                rb = QRadioButton()
                rb.setProperty("choice_answer", label)
                lab = _ClickableChoiceLabel(label, rb)
                lab.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
                row_l.addWidget(rb, alignment=Qt.AlignmentFlag.AlignTop)
                row_l.addWidget(lab, stretch=1)
                group.addButton(rb)
                s_layout.addWidget(row)

            scroll.setWidget(scroll_inner)
            self._await_inner.addWidget(scroll)

            confirm_btn = QPushButton("确定")
            confirm_btn.setObjectName("skillAgentAwaitUserConfirmButton")
            confirm_btn.setEnabled(False)
            confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)

            def _on_choice(btn: QAbstractButton) -> None:
                ans = btn.property("choice_answer")
                text = str(ans) if ans is not None and str(ans) else btn.text()
                selected["text"] = text.strip() or None
                confirm_btn.setEnabled(bool(selected["text"]))

            group.buttonClicked.connect(_on_choice)

            def _on_confirm() -> None:
                t = selected.get("text")
                if not t or on_confirm_send is None:
                    return
                on_confirm_send(t)

            confirm_btn.clicked.connect(_on_confirm)
            self._await_inner.addWidget(confirm_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        else:
            self._await_inner.addWidget(q_lab)
            if context:
                ctx_lab = QLabel(context)
                ctx_lab.setObjectName("skillAgentAwaitUserHint")
                ctx_lab.setWordWrap(True)
                self._await_inner.addWidget(ctx_lab)
            free = QLabel("未提供固定选项：请在下方输入框自由输入后发送。")
            free.setObjectName("skillAgentAwaitUserHint")
            free.setWordWrap(True)
            self._await_inner.addWidget(free)

        self._await_user_card.setVisible(True)


class SkillAgentWorkerThread(QThread):
    """绑定发起请求时的 conversation 与会话页，避免切换标签后日志串页。"""

    log_signal = Signal(str, str, object)
    finished_signal = Signal(str, object)

    def __init__(
        self,
        agent: SkillAgent,
        query: str,
        *,
        conversation_id: str,
        session_tab: ChatSessionTab,
    ) -> None:
        super().__init__()
        self.agent = agent
        self.query = query
        self.conversation_id = conversation_id
        self.session_tab = session_tab

    def run(self) -> None:
        self.agent.set_conversation_id(self.conversation_id)
        result = self.agent.run(self.query, self._log_callback)
        self.finished_signal.emit(result, self.session_tab)

    def _log_callback(self, message: str, msg_type: str = "info") -> None:
        self.log_signal.emit(message, msg_type, self.session_tab)


def _normalize_newlines(text: str) -> str:
    if not text:
        return text
    t = text.replace("\r\n", "\n")
    t = t.replace("\\r\\n", "\n").replace("\\n", "\n")
    return t


def _markdown_fragment_html(markdown: str) -> str:
    """将 Markdown 转为可嵌入 QTextEdit 的 HTML 片段（避免整页 <!DOCTYPE> 结构）。"""
    md = _normalize_newlines(markdown)
    tmp = QTextEdit()
    tmp.setMarkdown(md)
    raw = tmp.toHtml()
    m = re.search(r"<body[^>]*>(.*)</body>", raw, re.DOTALL | re.IGNORECASE)
    inner = m.group(1).strip() if m else ""
    if not inner:
        return f"<p>{escape(md).replace(chr(10), '<br/>')}</p>"
    wrap = _UI_STYLES["markdown_fragment_wrapper"]
    return f'<div style="{wrap}">{inner}</div>'


def _plain_block_html(text: str) -> str:
    t = _normalize_newlines(text)
    return f"<p>{escape(t).replace(chr(10), '<br/>')}</p>"


def _llm_request_params_text() -> str:
    m = get_chat_model()
    try:
        body = m.extra_body if isinstance(m.extra_body, dict) else dict(m.extra_body or {})
    except (TypeError, ValueError):
        body = m.extra_body
    body_s = json.dumps(body, ensure_ascii=False, indent=2) if isinstance(body, dict) else repr(body)
    key = m.api_key or ""
    key_disp = "（未设置）" if not key else f"{key[:4]}…{key[-2:]}" if len(key) > 8 else "（已设置）"
    parts = [
        f"model_name: {m.model_name}",
        f"temperature: {m.temperature}",
        f"top_p: {getattr(m, 'top_p', 0.95)}",
        f"frequency_penalty: {getattr(m, 'frequency_penalty', 0.6)}",
        f"enable_thinking: {body.get('enable_thinking', True)}",
        f"base_url: {m.base_url}",
        f"api_key: {key_disp}",
        f"extra_body:\n{body_s}",
        f"SKILL_AGENT_MAX_STEPS（Agent 循环上限）: {config.SKILL_AGENT_MAX_STEPS}",
    ]
    return "\n".join(parts)


class SkillAgentSettingsDialog(QDialog):
    """会话设置：模型信息、LLM 请求参数摘要、Skill 启用/禁用（禁用后不可加载到会话）。"""

    def __init__(self, parent: QWidget | None, skill_agent: SkillAgent) -> None:
        super().__init__(parent)
        self.setObjectName("skillAgentSettingsDialog")
        self.setWindowTitle("会话与模型设置")
        self.setModal(True)
        self.resize(560, 720)
        self._skill_agent = skill_agent
        self._disabled: set[str] = set(load_disabled_skill_ids())
        self._skill_checks: list[tuple[str, QCheckBox]] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        lm = QLabel("大模型配置")
        f = lm.font()
        f.setBold(True)
        lm.setFont(f)
        root.addWidget(lm)

        self._model_name_edit = QLineEdit()
        self._model_name_edit.setPlaceholderText("模型名称（如：qwen3.5-plus、glm-4）")
        root.addWidget(self._model_name_edit)

        self._api_key_edit = QLineEdit()
        self._api_key_edit.setPlaceholderText("API Key")
        root.addWidget(self._api_key_edit)

        self._base_url_edit = QLineEdit()
        self._base_url_edit.setPlaceholderText("API 基础 URL")
        root.addWidget(self._base_url_edit)

        temp_layout = QHBoxLayout()
        temp_label = QLabel("温度系数：")
        temp_label.setFont(QFont("Microsoft YaHei", 9))
        temp_layout.addWidget(temp_label)
        self._temperature_edit = QLineEdit()
        self._temperature_edit.setPlaceholderText("0.7")
        self._temperature_edit.setFixedWidth(80)
        temp_layout.addWidget(self._temperature_edit)
        temp_hint = QLabel("（控制输出随机性，0-2之间，值越高越随机）")
        temp_hint.setFont(QFont("Microsoft YaHei", 9))
        temp_hint.setStyleSheet("color: #6b7280;")
        temp_layout.addWidget(temp_hint)
        root.addLayout(temp_layout)

        top_p_layout = QHBoxLayout()
        top_p_label = QLabel("Top P：")
        top_p_label.setFont(QFont("Microsoft YaHei", 9))
        top_p_layout.addWidget(top_p_label)
        self._top_p_edit = QLineEdit()
        self._top_p_edit.setPlaceholderText("0.95")
        self._top_p_edit.setFixedWidth(80)
        top_p_layout.addWidget(self._top_p_edit)
        top_p_hint = QLabel("（核采样，0-1之间，值越小越聚焦）")
        top_p_hint.setFont(QFont("Microsoft YaHei", 9))
        top_p_hint.setStyleSheet("color: #6b7280;")
        top_p_layout.addWidget(top_p_hint)
        root.addLayout(top_p_layout)

        freq_pen_layout = QHBoxLayout()
        freq_pen_label = QLabel("频率惩罚：")
        freq_pen_label.setFont(QFont("Microsoft YaHei", 9))
        freq_pen_layout.addWidget(freq_pen_label)
        self._frequency_penalty_edit = QLineEdit()
        self._frequency_penalty_edit.setPlaceholderText("0.6")
        self._frequency_penalty_edit.setFixedWidth(80)
        freq_pen_layout.addWidget(self._frequency_penalty_edit)
        freq_pen_hint = QLabel("（控制重复输出，值越高越避免重复）")
        freq_pen_hint.setFont(QFont("Microsoft YaHei", 9))
        freq_pen_hint.setStyleSheet("color: #6b7280;")
        freq_pen_layout.addWidget(freq_pen_hint)
        root.addLayout(freq_pen_layout)

        enable_thinking_layout = QHBoxLayout()
        self._enable_thinking_check = QCheckBox("启用深度思考模式")
        self._enable_thinking_check.setFont(QFont("Microsoft YaHei", 9))
        enable_thinking_layout.addWidget(self._enable_thinking_check)
        thinking_hint = QLabel("（启用后模型会输出思考过程）")
        thinking_hint.setFont(QFont("Microsoft YaHei", 9))
        thinking_hint.setStyleSheet("color: #6b7280;")
        enable_thinking_layout.addWidget(thinking_hint)
        root.addLayout(enable_thinking_layout)

        config_buttons = QHBoxLayout()
        self._apply_btn = QPushButton("应用配置")
        self._apply_btn.setObjectName("skillAgentSettingsApplyButton")
        self._apply_btn.clicked.connect(self._on_apply_config)
        config_buttons.addWidget(self._apply_btn)

        self._reset_btn = QPushButton("恢复默认")
        self._reset_btn.setObjectName("skillAgentSettingsResetButton")
        self._reset_btn.clicked.connect(self._on_reset_config)
        config_buttons.addWidget(self._reset_btn)
        root.addLayout(config_buttons)

        lp = QLabel("当前 LLM 请求参数（只读）")
        fp = lp.font()
        fp.setBold(True)
        lp.setFont(fp)
        root.addWidget(lp)
        self._params_edit = QTextEdit()
        self._params_edit.setReadOnly(True)
        self._params_edit.setFont(QFont("Consolas", 9))
        self._params_edit.setMinimumHeight(100)
        self._params_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        root.addWidget(self._params_edit)

        ls = QLabel(
            "Skill 列表：勾选「启用」表示可用；取消勾选即禁用，禁用后不出现在系统列表中，且无法 select_skill 加载。"
        )
        ls.setWordWrap(True)
        fs = ls.font()
        fs.setBold(True)
        ls.setFont(fs)
        root.addWidget(ls)

        self._skills_scroll = QScrollArea()
        self._skills_scroll.setWidgetResizable(True)
        self._skills_scroll.setMinimumHeight(200)
        self._skills_inner = QWidget()
        self._skills_inner.setObjectName("skillAgentSettingsSkillsInner")
        self._skills_layout = QVBoxLayout(self._skills_inner)
        self._skills_layout.setContentsMargins(8, 8, 8, 8)
        self._skills_layout.setSpacing(6)
        self._skills_scroll.setWidget(self._skills_inner)
        root.addWidget(self._skills_scroll, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_btn = buttons.button(QDialogButtonBox.StandardButton.Close)
        if close_btn is not None:
            close_btn.setText("关闭")
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.setStyleSheet(_UI_STYLES["settings_dialog_stylesheet"])
        self._repopulate_skill_rows()
        self._refresh_llm_block()

    def _refresh_llm_block(self) -> None:
        current = get_current_config()
        self._model_name_edit.setText(current.model_name)
        self._api_key_edit.setText(current.api_key)
        self._base_url_edit.setText(current.base_url)
        self._temperature_edit.setText(str(current.temperature))
        self._top_p_edit.setText(str(current.top_p))
        self._frequency_penalty_edit.setText(str(current.frequency_penalty))
        self._enable_thinking_check.setChecked(current.enable_thinking)
        
        m = get_chat_model()
        self._params_edit.setPlainText(_llm_request_params_text())

    def _repopulate_skill_rows(self) -> None:
        self._skill_checks.clear()
        self._skills_inner = QWidget()
        self._skills_inner.setObjectName("skillAgentSettingsSkillsInner")
        self._skills_layout = QVBoxLayout(self._skills_inner)
        self._skills_layout.setContentsMargins(8, 8, 8, 8)
        self._skills_layout.setSpacing(6)
        self._skills_scroll.setWidget(self._skills_inner)

        skills = sorted(
            self._skill_agent.registry.list_skills(),
            key=lambda s: (s.skill_id or "").lower(),
        )
        for s in skills:
            sid = (s.skill_id or "").strip()
            if not sid:
                continue
            cb = QCheckBox("启用")
            cb.setChecked(sid not in self._disabled)
            cb.stateChanged.connect(lambda _st, _sid=sid, _cb=cb: self._on_skill_toggled(_sid, _cb))
            row = QHBoxLayout()
            row.addWidget(cb)
            name_lab = QLabel(f"{sid} · {s.name or ''}")
            name_lab.setWordWrap(True)
            row.addWidget(name_lab, stretch=1)
            self._skills_layout.addLayout(row)
            self._skill_checks.append((sid, cb))
        self._skills_layout.addStretch(1)

    def _on_skill_toggled(self, skill_id: str, cb: QCheckBox) -> None:
        if cb.isChecked():
            self._disabled.discard(skill_id)
        else:
            self._disabled.add(skill_id)
        save_disabled_skill_ids(self._disabled)

    def _on_apply_config(self) -> None:
        model_name = self._model_name_edit.text().strip()
        api_key = self._api_key_edit.text().strip()
        base_url = self._base_url_edit.text().strip()
        
        temperature = 0.7
        try:
            temp_val = float(self._temperature_edit.text().strip())
            if 0 <= temp_val <= 2:
                temperature = temp_val
            else:
                QMessageBox.warning(self, "警告", "温度系数必须在 0 到 2 之间")
                return
        except ValueError:
            QMessageBox.warning(self, "警告", "温度系数必须是数字")
            return
        
        top_p = 0.95
        try:
            top_p_val = float(self._top_p_edit.text().strip())
            if 0 <= top_p_val <= 1:
                top_p = top_p_val
            else:
                QMessageBox.warning(self, "警告", "Top P 必须在 0 到 1 之间")
                return
        except ValueError:
            QMessageBox.warning(self, "警告", "Top P 必须是数字")
            return
        
        frequency_penalty = 0.6
        try:
            freq_val = float(self._frequency_penalty_edit.text().strip())
            frequency_penalty = freq_val
        except ValueError:
            QMessageBox.warning(self, "警告", "频率惩罚必须是数字")
            return
        
        enable_thinking = self._enable_thinking_check.isChecked()
        
        if not model_name:
            QMessageBox.warning(self, "警告", "请输入模型名称")
            return
        if not api_key:
            QMessageBox.warning(self, "警告", "请输入 API Key")
            return
        if not base_url:
            QMessageBox.warning(self, "警告", "请输入 API 基础 URL")
            return
        
        new_config = LLMConfig(
            model_name=model_name,
            api_key=api_key,
            base_url=base_url,
            temperature=temperature,
            top_p=top_p,
            frequency_penalty=frequency_penalty,
            enable_thinking=enable_thinking,
        )
        set_config(new_config)
        
        QMessageBox.information(self, "提示", "配置已保存并生效，新配置将立即应用到所有会话")
        self._refresh_llm_block()

    def _on_reset_config(self) -> None:
        reply = QMessageBox.question(
            self, "确认", "确定要恢复默认配置吗？这将使用 .env 文件中的设置。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            reset_to_default()
            self._refresh_llm_block()
            QMessageBox.information(self, "提示", "已恢复默认配置")

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._skill_agent.reload_skills()
        self._disabled = set(load_disabled_skill_ids())
        self._repopulate_skill_rows()
        self._refresh_llm_block()


def _tab_title_for_conversation(conversation_id: str) -> str:
    c = (conversation_id or "").strip()
    if len(c) >= 10:
        return f"新会话 · {c[:5]}"
    return f"新会话 · {c[:5] or '?'}"


def _parse_await_user_log_json(message: str) -> dict[str, Any]:
    """解析 `ask_user` 运行时 log 中的 JSON（question / context / choices）。"""
    raw = (message or "").strip()
    if not raw:
        return {"question": "", "context": "", "choices": []}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"question": raw, "context": "", "choices": []}
    if not isinstance(data, dict):
        return {"question": raw, "context": "", "choices": []}
    choices: list[str] = []
    cr = data.get("choices")
    if isinstance(cr, list):
        for c in cr:
            if c is None:
                continue
            s = str(c).strip()
            if s:
                choices.append(s)
    return {
        "question": str(data.get("question") or "").strip(),
        "context": str(data.get("context") or "").strip(),
        "choices": choices,
    }


def _ask_user_spec_from_record(meta: dict[str, Any], content: str) -> dict[str, Any]:
    """从持久化 tool 消息的 metadata.args 恢复 ask_user 结构；失败时从正文兜底。"""
    raw = meta.get("args")
    args: dict[str, Any] = {}
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                args = parsed
        except json.JSONDecodeError:
            pass
    elif isinstance(raw, dict):
        args = raw
    choices: list[str] = []
    cr = args.get("choices")
    if isinstance(cr, list):
        for c in cr:
            if c is None:
                continue
            s = str(c).strip()
            if s:
                choices.append(s)
    q = str(args.get("question") or "").strip()
    ctx = str(args.get("context") or "").strip()
    if not q:
        for line in (content or "").splitlines():
            s = line.strip()
            if s and not s.startswith("（") and not s.startswith("可选"):
                q = s
                break
    return {"question": q, "context": ctx, "choices": choices}


class SkillAgentMainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.work_dir = config.WORKER_DIR
        self.executor = Executor(self.work_dir)
        self._memory = SqliteMemory(username=config.DEFAULT_SKILL_AGENT_USER)
        self.skill_agent = SkillAgent(
            self.work_dir,
            executor=self.executor,
            memory=self._memory,
            username=config.DEFAULT_SKILL_AGENT_USER,
        )
        self.worker_thread: SkillAgentWorkerThread | None = None
        self._assistant_stream_timer: QTimer | None = None
        self._assistant_stream_state: dict[str, Any] | None = None
        self._init_ui()

    def _init_ui(self) -> None:
        self.setWindowTitle("SkillAgent")
        self.setGeometry(120, 120, 780, 620)

        central = QWidget()
        central.setObjectName("skillAgentCentral")
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        chat_header = QHBoxLayout()
        chat_header.addStretch(1)
        self.new_conversation_btn = QPushButton("新增会话")
        self.new_conversation_btn.setObjectName("skillAgentToolbarButton")
        self.new_conversation_btn.setFont(QFont("Microsoft YaHei", 9))
        self.new_conversation_btn.setFixedHeight(28)
        self.new_conversation_btn.setToolTip("新建一个会话标签页（新的 conversation_id）")
        self.new_conversation_btn.clicked.connect(self._on_new_conversation)
        chat_header.addWidget(self.new_conversation_btn, alignment=Qt.AlignmentFlag.AlignRight)
        self.settings_btn = QPushButton("设置")
        self.settings_btn.setObjectName("skillAgentToolbarButton")
        self.settings_btn.setFont(QFont("Microsoft YaHei", 9))
        self.settings_btn.setFixedHeight(28)
        self.settings_btn.setToolTip("模型、LLM 参数与 Skill 启用状态")
        self.settings_btn.clicked.connect(self._open_settings)
        chat_header.addWidget(self.settings_btn, alignment=Qt.AlignmentFlag.AlignRight)

        self.chat_tabs = QTabWidget()
        self.chat_tabs.setDocumentMode(True)
        self.chat_tabs.setTabsClosable(True)
        self.chat_tabs.setMovable(True)
        self.chat_tabs.tabCloseRequested.connect(self._on_tab_close_requested)
        self.chat_tabs.currentChanged.connect(self._on_current_tab_changed)
        self.chat_tabs.tabBar().tabBarClicked.connect(self._on_tab_bar_clicked)
        self.chat_tabs.setMinimumHeight(280)
        self.chat_tabs.tabBar().setDrawBase(False)

        chat_wrap = QVBoxLayout()
        chat_wrap.setSpacing(4)
        chat_wrap.addLayout(chat_header)
        chat_wrap.addWidget(self.chat_tabs, stretch=1)
        chat_container = QWidget()
        chat_container.setLayout(chat_wrap)
        layout.addWidget(chat_container, stretch=1)

        row = QHBoxLayout()
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText(_INPUT_PLACEHOLDER_DEFAULT)
        self.input_edit.setFont(QFont("Microsoft YaHei", 10))
        self.input_edit.setMinimumHeight(36)
        self.input_edit.returnPressed.connect(self._on_send)
        self.send_btn = QPushButton("发送")
        self.send_btn.setObjectName("skillAgentSendButton")
        self.send_btn.setFont(QFont("Microsoft YaHei", 10))
        self.send_btn.setMinimumHeight(36)
        self.send_btn.setMinimumWidth(88)
        self.send_btn.clicked.connect(self._on_send)
        row.addWidget(self.input_edit, stretch=1)
        row.addWidget(self.send_btn)
        layout.addLayout(row)

        self.setStyleSheet(_UI_STYLES["main_window_stylesheet"])
        self._populate_initial_tabs()
        self._refresh_tab_close_buttons()

    def _refresh_tab_close_buttons(self) -> None:
        """用自绘图标的 QToolButton 替换标签关闭子控件（与主色 / slate 体系统一）。"""
        bar = self.chat_tabs.tabBar()
        if not bar.tabsClosable():
            return
        for i in range(bar.count()):
            self._ensure_custom_tab_close_button(bar, i)

    def _ensure_custom_tab_close_button(self, bar: QTabBar, index: int) -> None:
        existing = bar.tabButton(index, QTabBar.ButtonPosition.RightSide)
        if (
            isinstance(existing, QToolButton)
            and existing.objectName() == _TAB_CLOSE_BTN_OBJECT_NAME
        ):
            existing.setIcon(_tab_close_icon())
            existing.setIconSize(QSize(14, 14))
            return
        btn = QToolButton(bar)
        btn.setObjectName(_TAB_CLOSE_BTN_OBJECT_NAME)
        btn.setAutoRaise(True)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setIcon(_tab_close_icon())
        btn.setIconSize(QSize(14, 14))
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        btn.setFixedSize(20, 20)
        btn.setToolTip("关闭会话")
        btn.clicked.connect(
            lambda _c=False, b=btn: self._on_skill_agent_tab_close_clicked(b)
        )
        bar.setTabButton(index, QTabBar.ButtonPosition.RightSide, btn)

    def _on_skill_agent_tab_close_clicked(self, btn: QToolButton) -> None:
        bar = self.chat_tabs.tabBar()
        for i in range(bar.count()):
            if bar.tabButton(i, QTabBar.ButtonPosition.RightSide) is btn:
                self._on_tab_close_requested(i)
                return

    def _replay_messages_to_chat(
        self,
        chat_view: QTextEdit,
        records: list[dict],
        *,
        conversation_id: str | None = None,
    ) -> None:
        """按库中顺序把消息画回聊天区（与运行时 log_callback 展示规则尽量一致）。"""
        show_tool_ui = config.SKILL_AGENT_UI_SHOW_TOOL_CALLS
        pending_live_ask = False
        if conversation_id and SkillAgent.conversation_awaits_user_clarification(
            self._memory, conversation_id
        ):
            pending_live_ask = True
        n = len(records)
        for idx, m in enumerate(records):
            role = str(m.get("role") or "")
            content = str(m.get("content") or "")
            meta = m.get("metadata")
            if not isinstance(meta, dict):
                meta = {}
            mt = meta.get("type")
            name = str(meta.get("name") or m.get("name") or "")

            if role == "system":
                continue
            if role == "user" and mt == "skill_content":
                continue
            if not content.strip() and role != "tool":
                continue

            if role == "user":
                self._append_user(chat_view, content)
            elif role == "assistant":
                if mt == "think":
                    self._append_assistant_think_markdown(chat_view, content)
                else:
                    self._append_assistant_markdown(chat_view, content)
            elif role == "tool":
                if name == "ask_user" or meta.get("type") == "ask_user":
                    # 仍挂起在 ask_user 的最后一条：改由底部交互区展示，避免仅静态「历史」卡无法点确定
                    if pending_live_ask and idx == n - 1:
                        continue
                    self._append_ask_user_replay_card(chat_view, meta, content)
                    continue
                if not show_tool_ui:
                    continue
                if name == "select_skill" or meta.get("type") == "skill":
                    self._append_doc_markdown(chat_view, content)
                else:
                    self._append_tool_line(chat_view, content)

    def _populate_initial_tabs(self) -> None:
        sessions = [
            c
            for c in self.skill_agent.list_saved_conversations()
            if (c.conversation_id or "").strip()
        ]
        if not sessions:
            cid, title = self.skill_agent.start_new_conversation()
            tab = ChatSessionTab(cid, pending_db_history=False)
            idx = self.chat_tabs.addTab(tab, title or _tab_title_for_conversation(cid))
            self.chat_tabs.setTabToolTip(idx, cid)
            self.skill_agent.set_conversation_id(cid)
            return
        for conv in sessions:
            cid = (conv.conversation_id or "").strip()
            tab = ChatSessionTab(cid, pending_db_history=True)
            disp = (conv.title or "").strip() or _tab_title_for_conversation(cid)
            idx = self.chat_tabs.addTab(tab, disp)
            self.chat_tabs.setTabToolTip(idx, cid)
        self.chat_tabs.setCurrentIndex(0)
        self.skill_agent.set_conversation_id((sessions[0].conversation_id or "").strip())
        first_tab = self.chat_tabs.widget(0)
        if isinstance(first_tab, ChatSessionTab):
            self._ensure_tab_history_loaded(first_tab)
        self._sync_input_placeholder_for_active_tab()

    def _ensure_tab_history_loaded(self, tab: ChatSessionTab) -> None:
        """仅在需要时调用 Memory 拉取消息并渲染；不触发大模型。"""
        if not tab.pending_db_history:
            return
        tab.pending_db_history = False
        tab.chat_view.setPlaceholderText("对话记录将显示在这里…")
        records = self.skill_agent.message_records_for_conversation(tab.conversation_id)
        self._replay_messages_to_chat(
            tab.chat_view, records, conversation_id=tab.conversation_id
        )
        if SkillAgent.conversation_awaits_user_clarification(self._memory, tab.conversation_id):
            self._restore_pending_await_user_panel(tab)
        if self.chat_tabs.currentWidget() is tab:
            self._sync_input_placeholder_for_active_tab()

    def _restore_pending_await_user_panel(self, tab: ChatSessionTab) -> None:
        """从库中最后一条 ask_user 恢复可选项与「确定」，与线上一致。"""
        records = self.skill_agent.message_records_for_conversation(tab.conversation_id)
        if not records:
            return
        last = records[-1]
        if str(last.get("role") or "") != "tool":
            return
        meta = last.get("metadata")
        if not isinstance(meta, dict):
            meta = {}
        if meta.get("name") != "ask_user":
            return
        content = str(last.get("content", "") or "")
        if content.startswith("错误"):
            return
        spec = _ask_user_spec_from_record(meta, content)
        st = tab
        tab.show_await_user_prompt(
            spec,
            on_confirm_send=lambda t, _st=st: self._send_user_message(t, session_tab=_st),
        )

    def _active_session_tab(self) -> ChatSessionTab | None:
        w = self.chat_tabs.currentWidget()
        return w if isinstance(w, ChatSessionTab) else None

    def _active_chat_view(self) -> QTextEdit | None:
        t = self._active_session_tab()
        return t.chat_view if t else None

    def _on_current_tab_changed(self, _index: int) -> None:
        tab = self._active_session_tab()
        if tab is not None:
            self.skill_agent.set_conversation_id(tab.conversation_id)
            if (
                not tab.pending_db_history
                and SkillAgent.conversation_awaits_user_clarification(
                    self._memory, tab.conversation_id
                )
                and not tab.has_active_await_user_prompt()
            ):
                self._restore_pending_await_user_panel(tab)
        self._sync_input_placeholder_for_active_tab()

    def _sync_input_placeholder_for_active_tab(self) -> None:
        tab = self._active_session_tab()
        if tab is None:
            self.input_edit.setPlaceholderText(_INPUT_PLACEHOLDER_DEFAULT)
            return
        if SkillAgent.conversation_awaits_user_clarification(self._memory, tab.conversation_id):
            self.input_edit.setPlaceholderText(_INPUT_PLACEHOLDER_AWAIT_USER)
        else:
            self.input_edit.setPlaceholderText(_INPUT_PLACEHOLDER_DEFAULT)

    def _on_tab_bar_clicked(self, index: int) -> None:
        """用户点击标签栏时才拉取并渲染该会话的数据库消息（大模型仍在用户点击发送后由 run 触发）。"""
        w = self.chat_tabs.widget(index)
        if isinstance(w, ChatSessionTab):
            self._ensure_tab_history_loaded(w)

    def _on_tab_close_requested(self, index: int) -> None:
        if self.chat_tabs.count() <= 1:
            QMessageBox.information(self, "提示", "至少保留一个会话标签页。")
            return
        page = self.chat_tabs.widget(index)
        if not isinstance(page, ChatSessionTab):
            return
        if self.worker_thread and self.worker_thread.isRunning():
            if page.conversation_id == self.worker_thread.conversation_id:
                QMessageBox.warning(self, "提示", "该会话正在执行中，请结束后再关闭标签。")
                return
        self._memory.clear_conversation(page.conversation_id)
        self.chat_tabs.removeTab(index)
        page.deleteLater()

    def _scroll_to_end(self, chat_view: QTextEdit) -> None:
        bar = chat_view.verticalScrollBar()
        bar.setValue(bar.maximum())
        chat_view.moveCursor(QTextCursor.End)

    @staticmethod
    def _assistant_stream_marker() -> str:
        # 使用全零宽字符编码随机 token，避免流式过程中出现可见占位字母。
        token = secrets.token_hex(10)
        bits = "".join(format(int(ch, 16), "04b") for ch in token)
        zw0 = "\u200b"  # zero-width space
        zw1 = "\u200c"  # zero-width non-joiner
        encoded = "".join(zw1 if b == "1" else zw0 for b in bits)
        return "\u2060" + encoded + "\u2060"

    def _stop_assistant_stream_timer(self) -> None:
        if self._assistant_stream_timer is not None:
            self._assistant_stream_timer.stop()
            self._assistant_stream_timer.deleteLater()
            self._assistant_stream_timer = None

    def _find_stream_marker_span(
        self, chat_view: QTextEdit, marker_start: str, marker_end: str
    ) -> tuple[int, int, int, int] | None:
        """
        返回 (start_marker_pos, content_start_pos, content_end_pos, end_marker_end_pos)。
        用双 marker 重新定位区间，避免文档重排导致的绝对位置漂移。
        """
        doc = chat_view.document()
        hit_start = doc.find(marker_start, 0)
        if hit_start.isNull():
            return None
        start_pos = min(hit_start.anchor(), hit_start.position())
        content_start = max(hit_start.anchor(), hit_start.position())
        hit_end = doc.find(marker_end, content_start)
        if hit_end.isNull():
            return None
        content_end = min(hit_end.anchor(), hit_end.position())
        end_marker_end = max(hit_end.anchor(), hit_end.position())
        return (start_pos, content_start, content_end, end_marker_end)

    def _replace_stream_range_with_markdown(self, chat_view: QTextEdit, marker_start: str, marker_end: str, full: str) -> None:
        span = self._find_stream_marker_span(chat_view, marker_start, marker_end)
        if span is None:
            self._append_assistant_markdown(chat_view, full)
            return
        start_marker_pos, _, _, end_marker_end = span
        doc = chat_view.document()
        cur = QTextCursor(doc)
        cur.setPosition(start_marker_pos)
        cur.setPosition(end_marker_end, QTextCursor.MoveMode.KeepAnchor)
        cur.removeSelectedText()
        cur.insertHtml(_markdown_fragment_html(full))
        self._scroll_to_end(chat_view)

    def _flush_assistant_stream_to_markdown(self) -> None:
        """将当前流式占位区间替换为完整 Markdown（用于打断或收尾）。"""
        st = self._assistant_stream_state
        if st is None:
            return
        chat_view: QTextEdit = st["chat_view"]
        self._replace_stream_range_with_markdown(
            chat_view, st["marker_start"], st["marker_end"], st["full"]
        )
        self._assistant_stream_state = None
        self._stop_assistant_stream_timer()

    def _assistant_stream_tick(self) -> None:
        st = self._assistant_stream_state
        if st is None:
            self._stop_assistant_stream_timer()
            return
        chat_view: QTextEdit = st["chat_view"]
        full: str = st["full"]
        n = len(full)
        step = int(st.get("chars_per_tick") or _STREAM_CHARS_PER_TICK)
        next_shown = min(n, int(st["shown"]) + max(1, step))
        marker_start: str = st["marker_start"]
        marker_end: str = st["marker_end"]
        span = self._find_stream_marker_span(chat_view, marker_start, marker_end)
        if span is None:
            self._assistant_stream_state = None
            self._stop_assistant_stream_timer()
            self._append_assistant_markdown(chat_view, full)
            return
        _, content_start, content_end, _ = span
        doc = chat_view.document()
        cur = QTextCursor(doc)
        cur.setPosition(content_start)
        cur.setPosition(content_end, QTextCursor.MoveMode.KeepAnchor)
        cur.removeSelectedText()
        cur.insertText(full[:next_shown])
        st["shown"] = next_shown
        self._scroll_to_end(chat_view)
        if next_shown >= n:
            self._replace_stream_range_with_markdown(
                chat_view, marker_start, marker_end, full
            )
            self._assistant_stream_state = None
            self._stop_assistant_stream_timer()

    def _append_assistant_markdown_streaming(self, chat_view: QTextEdit, markdown: str) -> None:
        """助手气泡：先按字符铺开，再一次性替换为 Markdown 渲染结果。"""
        full = _normalize_newlines(markdown or "")
        if not full.strip():
            self._append_assistant_markdown(chat_view, markdown)
            return
        if self._assistant_stream_state is not None:
            self._flush_assistant_stream_to_markdown()
        marker_start = self._assistant_stream_marker()
        marker_end = self._assistant_stream_marker()
        st_o = _UI_STYLES["chat_bubble_assistant_outer"]
        st_c = _UI_STYLES["chat_bubble_assistant_caption"]
        st_b = _UI_STYLES["chat_bubble_assistant_body"]
        body_html = (
            f'<span style="white-space: pre-wrap;">'
            f'{escape(marker_start)}{escape(marker_end)}'
            f'</span>'
        )
        bubble = (
            f'<div style="{st_o}">'
            f'<div style="{st_c}">{escape("助手")}</div>'
            f'<div style="{st_b}">{body_html}</div></div>'
        )
        row_margin = _UI_STYLES["chat_message_row_table"]
        row = (
            f'<table width="100%" cellspacing="0" cellpadding="0" style="{row_margin}">'
            f'<tr><td align="left">{bubble}</td></tr></table>'
        )
        chat_view.moveCursor(QTextCursor.End)
        chat_view.insertHtml(row)
        span = self._find_stream_marker_span(chat_view, marker_start, marker_end)
        if span is None:
            self._append_assistant_markdown(chat_view, markdown)
            return
        self._assistant_stream_state = {
            "chat_view": chat_view,
            "marker_start": marker_start,
            "marker_end": marker_end,
            "full": full,
            "shown": 0,
            "chars_per_tick": _STREAM_CHARS_PER_TICK,
        }
        self._assistant_stream_timer = QTimer(self)
        self._assistant_stream_timer.setInterval(_STREAM_TIMER_MS)
        self._assistant_stream_timer.timeout.connect(self._assistant_stream_tick)
        self._assistant_stream_timer.start()
        self._assistant_stream_tick()

    def _insert_row(self, chat_view: QTextEdit, inner_html: str, *, align: str) -> None:
        al = "right" if align == "right" else "left"
        chat_view.moveCursor(QTextCursor.End)
        row_margin = _UI_STYLES["chat_message_row_table"]
        chat_view.insertHtml(
            f'<table width="100%" cellspacing="0" cellpadding="0" style="{row_margin}">'
            f'<tr><td align="{al}">{inner_html}</td></tr></table>'
        )
        self._scroll_to_end(chat_view)

    def _open_settings(self) -> None:
        SkillAgentSettingsDialog(self, self.skill_agent).exec()

    def _on_new_conversation(self) -> None:
        if self.worker_thread and self.worker_thread.isRunning():
            QMessageBox.warning(self, "提示", "当前仍有对话在执行，请结束后再新建会话。")
            return
        cid, default_title = self.skill_agent.start_new_conversation()
        tab = ChatSessionTab(cid, pending_db_history=False)
        idx = self.chat_tabs.addTab(tab, default_title or _tab_title_for_conversation(cid))
        self.chat_tabs.setTabToolTip(idx, cid)
        self.chat_tabs.setCurrentIndex(idx)
        hint = _plain_block_html(
            f"已新建会话标签页，后续消息将写入本页对应的 conversation。\nconversation_id：{cid}"
        )
        self._append_assistant_card(tab.chat_view, hint, subtitle="系统")
        self._refresh_tab_close_buttons()
        self._sync_input_placeholder_for_active_tab()

    def _append_user(self, chat_view: QTextEdit, text: str) -> None:
        body = _plain_block_html(text)
        st_o = _UI_STYLES["chat_bubble_user_outer"]
        st_c = _UI_STYLES["chat_bubble_user_caption"]
        st_b = _UI_STYLES["chat_bubble_user_body"]
        bubble = (
            f'<div style="{st_o}">'
            f'<div style="{st_c}">用户</div>'
            f'<div style="{st_b}">{body}</div></div>'
        )
        self._insert_row(chat_view, bubble, align="right")

    def _append_assistant_card(
        self, chat_view: QTextEdit, body_html: str, *, subtitle: str = "助手"
    ) -> None:
        st_o = _UI_STYLES["chat_bubble_assistant_outer"]
        st_c = _UI_STYLES["chat_bubble_assistant_caption"]
        st_b = _UI_STYLES["chat_bubble_assistant_body"]
        bubble = (
            f'<div style="{st_o}">'
            f'<div style="{st_c}">{escape(subtitle)}</div>'
            f'<div style="{st_b}">{body_html}</div></div>'
        )
        self._insert_row(chat_view, bubble, align="left")
    def _append_assistant_think_card(
        self, chat_view: QTextEdit, body_html: str, *, subtitle: str = "助手"
    ) -> None:
        st_o = _UI_STYLES["chat_bubble_think_outer"]
        st_c = _UI_STYLES["chat_bubble_think_caption"]
        st_b = _UI_STYLES["chat_bubble_think_body"]
        bubble = (
            f'<div style="{st_o}">'
            f'<div style="{st_c}">{escape(subtitle)}</div>'
            f'<div style="{st_b}">{body_html}</div></div>'
        )
        self._insert_row(chat_view, bubble, align="left")

    def _append_tool_line(self, chat_view: QTextEdit, text: str) -> None:
        safe = escape(_normalize_newlines(text))
        st_o = _UI_STYLES["chat_tool_outer"]
        st_cap = _UI_STYLES["chat_tool_caption"]
        st_txt = _UI_STYLES["chat_tool_text"]
        inner = (
            f'<div style="{st_o}">'
            f'<span style="{st_cap}">工具</span>'
            f'<span style="{st_txt}"> · {safe}</span></div>'
        )
        self._insert_row(chat_view, inner, align="left")

    def _append_assistant_markdown(self, chat_view: QTextEdit, markdown: str) -> None:
        frag = _markdown_fragment_html(markdown)
        self._append_assistant_card(chat_view, frag, subtitle="助手")
    def _append_assistant_think_markdown(self, chat_view: QTextEdit, markdown: str):
        frag = _markdown_fragment_html(markdown)
        self._append_assistant_think_card(chat_view, frag, subtitle="助手-think")

    def _append_doc_markdown(self, chat_view: QTextEdit, markdown: str) -> None:
        frag = _markdown_fragment_html(markdown)
        self._append_assistant_card(chat_view, frag, subtitle="Skill 文档")

    def _append_ask_user_replay_card(
        self, chat_view: QTextEdit, meta: dict[str, Any], content: str
    ) -> None:
        """历史记录中的 ask_user：首行问题 + 下方静态「建议选项」列表（无交互）。"""
        spec = _ask_user_spec_from_record(meta, content)
        q = escape(spec["question"] or "（无问题摘要）")
        parts = [
            f'<p style="font-weight:600;font-size:11pt;margin:0 0 10px 0;color:#1f2937;">{q}</p>'
        ]
        ctx = str(spec.get("context") or "").strip()
        if ctx:
            parts.append(
                f'<p style="color:#6b7280;font-size:10pt;margin:4px 0 8px 0;">{escape(ctx)}</p>'
            )
        raw_choices = spec.get("choices")
        if not isinstance(raw_choices, list):
            raw_choices = []
        opts: list[str] = []
        for c in raw_choices:
            if c is None:
                continue
            s = str(c).strip()
            if s:
                opts.append(s)
        if opts:
            parts.append(
                '<p style="color:#6b7280;font-size:10pt;margin:0 0 6px 0;">建议选项（历史）：</p>'
            )
            parts.append(
                '<table cellspacing="0" cellpadding="0" '
                'style="border:1px solid #e5e7eb;border-radius:8px;width:100%;">'
            )
            for i, c in enumerate(opts):
                bt = "border-top:1px solid #e5e7eb;" if i else ""
                parts.append(
                    f'<tr><td style="padding:8px 12px;{bt}">'
                    f'<span style="color:#2563eb;font-weight:600;">○</span> '
                    f'<span style="color:#374151;">{escape(c)}</span></td></tr>'
                )
            parts.append("</table>")
        body = "".join(parts)
        self._append_assistant_card(chat_view, body, subtitle="待你回复（历史）")

    def _send_user_message(self, text: str, *, session_tab: ChatSessionTab | None = None) -> None:
        """将用户文案写入会话并启动 Agent（与点「发送」相同，不经过输入框）。"""
        text = (text or "").strip()
        if not text:
            QMessageBox.warning(self, "提示", "请输入内容")
            return
        if self.worker_thread and self.worker_thread.isRunning():
            QMessageBox.warning(self, "提示", "上一轮流式仍在执行，请稍候")
            return
        tab = session_tab if session_tab is not None else self._active_session_tab()
        chat = tab.chat_view if tab is not None else None
        if tab is None or chat is None:
            QMessageBox.warning(self, "提示", "没有可用的会话标签页")
            return

        self.skill_agent.set_conversation_id(tab.conversation_id)
        self._append_user(chat, text)
        tab.clear_await_user_ui()
        self.input_edit.clear()

        self.send_btn.setEnabled(False)
        self.input_edit.setEnabled(False)

        self.worker_thread = SkillAgentWorkerThread(
            self.skill_agent,
            text,
            conversation_id=tab.conversation_id,
            session_tab=tab,
        )
        self.worker_thread.log_signal.connect(self._on_log)
        self.worker_thread.finished_signal.connect(self._on_worker_finished)
        self.worker_thread.start()

    def _on_send(self) -> None:
        text = self.input_edit.text().strip()
        if not text:
            QMessageBox.warning(self, "提示", "请输入内容")
            return
        self._send_user_message(text)

    def _on_log(self, message: str, msg_type: str, session_tab: object) -> None:
        if not isinstance(session_tab, ChatSessionTab):
            return
        target_chat = session_tab.chat_view
        show_tool_ui = config.SKILL_AGENT_UI_SHOW_TOOL_CALLS
        if msg_type in ("tool", "base_tool"):
            if show_tool_ui:
                self._append_tool_line(target_chat, message)
        elif msg_type == "doc":
            if show_tool_ui:
                self._append_doc_markdown(target_chat, message)
        elif msg_type in ("assistant", "response"):
            self._append_assistant_markdown_streaming(target_chat, message)
        elif msg_type in ("think",):
            self._append_assistant_think_markdown(target_chat, message)
        elif msg_type == "await_user":
            spec = _parse_await_user_log_json(message)
            st = session_tab
            session_tab.show_await_user_prompt(
                spec,
                on_confirm_send=lambda t, _st=st: self._send_user_message(t, session_tab=_st),
            )

    def _on_worker_finished(self, result: str, session_tab: object) -> None:
        self.send_btn.setEnabled(True)
        self.input_edit.setEnabled(True)
        if isinstance(session_tab, ChatSessionTab) and result != SKILL_AGENT_AWAITING_USER_REPLY:
            session_tab.clear_await_user_ui()
        self._sync_input_placeholder_for_active_tab()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._assistant_stream_state is not None:
            self._flush_assistant_stream_to_markdown()
        if self.worker_thread and self.worker_thread.isRunning():
            self.worker_thread.terminate()
            self.worker_thread.wait(2000)
        super().closeEvent(event)


def main() -> None:
    app = QApplication(sys.argv)
    # Windows 原生样式下标签关闭按钮常忽略 QSS；Fusion 下排版与配色更可控。
    fusion = QStyleFactory.create("Fusion")
    if fusion is not None:
        app.setStyle(fusion)
    w = SkillAgentMainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
