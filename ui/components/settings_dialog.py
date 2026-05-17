from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from llm.llm_config_manager import LLMConfig, get_current_config, reset_to_default, set_config
from skill_agent_preferences import load_disabled_skill_ids, save_disabled_skill_ids
from ui.styles.style_manager import StyleManager

if TYPE_CHECKING:
    from skill_agent import SkillAgent


def _llm_request_params_text() -> str:
    from llm import get_chat_model
    import config

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


class SettingsDialog(QDialog):
    """会话设置：模型信息、LLM 请求参数摘要、Skill 启用/禁用（禁用后不可加载到会话）。"""

    def __init__(
        self,
        parent: QWidget | None,
        skill_agent: "SkillAgent",
        *,
        on_config_changed: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("skillAgentSettingsDialog")
        self.setWindowTitle("会话与模型设置")
        self.setModal(True)
        self.resize(560, 720)
        self._skill_agent = skill_agent
        self._on_config_changed = on_config_changed
        self._disabled: set[str] = set(load_disabled_skill_ids())
        self._skill_checks: list[tuple[str, QCheckBox]] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        self._setup_llm_config_section(root)
        self._setup_config_buttons(root)
        self._setup_params_section(root)
        self._setup_skills_section(root)
        self._setup_close_button(root)

        self._apply_style()
        self._repopulate_skill_rows()
        self._refresh_llm_block()

    def _apply_style(self) -> None:
        style = StyleManager.get_style("settings_dialog_stylesheet")
        if style:
            self.setStyleSheet(style)

    def _setup_llm_config_section(self, layout: QVBoxLayout) -> None:
        lm = QLabel("大模型配置")
        f = lm.font()
        f.setBold(True)
        lm.setFont(f)
        layout.addWidget(lm)

        self._model_name_edit = QLineEdit()
        self._model_name_edit.setPlaceholderText("模型名称（如：qwen3.5-plus、glm-4）")
        layout.addWidget(self._model_name_edit)

        self._api_key_edit = QLineEdit()
        self._api_key_edit.setPlaceholderText("API Key")
        layout.addWidget(self._api_key_edit)

        self._base_url_edit = QLineEdit()
        self._base_url_edit.setPlaceholderText("API 基础 URL")
        layout.addWidget(self._base_url_edit)

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
        layout.addLayout(temp_layout)

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
        layout.addLayout(top_p_layout)

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
        layout.addLayout(freq_pen_layout)

        enable_thinking_layout = QHBoxLayout()
        self._enable_thinking_check = QCheckBox("启用深度思考模式")
        self._enable_thinking_check.setFont(QFont("Microsoft YaHei", 9))
        enable_thinking_layout.addWidget(self._enable_thinking_check)
        thinking_hint = QLabel("（启用后模型会输出思考过程）")
        thinking_hint.setFont(QFont("Microsoft YaHei", 9))
        thinking_hint.setStyleSheet("color: #6b7280;")
        enable_thinking_layout.addWidget(thinking_hint)
        layout.addLayout(enable_thinking_layout)

    def _setup_config_buttons(self, layout: QVBoxLayout) -> None:
        config_buttons = QHBoxLayout()
        self._apply_btn = QPushButton("应用配置")
        self._apply_btn.setObjectName("skillAgentSettingsApplyButton")
        self._apply_btn.clicked.connect(self._on_apply_config)
        config_buttons.addWidget(self._apply_btn)

        self._reset_btn = QPushButton("恢复默认")
        self._reset_btn.setObjectName("skillAgentSettingsResetButton")
        self._reset_btn.clicked.connect(self._on_reset_config)
        config_buttons.addWidget(self._reset_btn)
        layout.addLayout(config_buttons)

    def _setup_params_section(self, layout: QVBoxLayout) -> None:
        lp = QLabel("当前 LLM 请求参数（只读）")
        fp = lp.font()
        fp.setBold(True)
        lp.setFont(fp)
        layout.addWidget(lp)
        self._params_edit = QTextEdit()
        self._params_edit.setReadOnly(True)
        self._params_edit.setFont(QFont("Consolas", 9))
        self._params_edit.setMinimumHeight(100)
        self._params_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(self._params_edit)

    def _setup_skills_section(self, layout: QVBoxLayout) -> None:
        ls = QLabel(
            "Skill 列表：勾选「启用」表示可用；取消勾选即禁用，禁用后不出现在系统列表中，且无法 select_skill 加载。"
        )
        ls.setWordWrap(True)
        fs = ls.font()
        fs.setBold(True)
        ls.setFont(fs)
        layout.addWidget(ls)

        self._skills_scroll = QScrollArea()
        self._skills_scroll.setWidgetResizable(True)
        self._skills_scroll.setMinimumHeight(200)
        self._skills_inner = QWidget()
        self._skills_inner.setObjectName("skillAgentSettingsSkillsInner")
        self._skills_layout = QVBoxLayout(self._skills_inner)
        self._skills_layout.setContentsMargins(8, 8, 8, 8)
        self._skills_layout.setSpacing(6)
        self._skills_scroll.setWidget(self._skills_inner)
        layout.addWidget(self._skills_scroll, stretch=1)

    def _setup_close_button(self, layout: QVBoxLayout) -> None:
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_btn = buttons.button(QDialogButtonBox.StandardButton.Close)
        if close_btn is not None:
            close_btn.setText("关闭")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _refresh_llm_block(self) -> None:
        current = get_current_config()
        self._model_name_edit.setText(current.model_name)
        self._api_key_edit.setText(current.api_key)
        self._base_url_edit.setText(current.base_url)
        self._temperature_edit.setText(str(current.temperature))
        self._top_p_edit.setText(str(current.top_p))
        self._frequency_penalty_edit.setText(str(current.frequency_penalty))
        self._enable_thinking_check.setChecked(current.enable_thinking)
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
        if self._on_config_changed:
            self._on_config_changed()

    def _on_reset_config(self) -> None:
        reply = QMessageBox.question(
            self, "确认", "确定要恢复默认配置吗？这将使用 .env 文件中的设置。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            reset_to_default()
            self._refresh_llm_block()
            QMessageBox.information(self, "提示", "已恢复默认配置")
            if self._on_config_changed:
                self._on_config_changed()

    def showEvent(self, event: Any) -> None:
        super().showEvent(event)
        self._skill_agent.reload_skills()
        self._disabled = set(load_disabled_skill_ids())
        self._repopulate_skill_rows()
        self._refresh_llm_block()
