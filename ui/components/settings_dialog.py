from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable

from logger import get_module_logger

logger = get_module_logger("settings_dialog")

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QTimeEdit,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from llm.llm_config_manager import (
    LLMConfig,
    LLMConfigItem,
    add_config,
    delete_config,
    generate_config_id,
    get_active_config_item,
    get_current_config,
    get_current_multi_config,
    get_switch_events,
    is_auto_switch_enabled,
    list_configs,
    move_config_down,
    move_config_up,
    reset_to_default,
    set_active_config,
    set_multi_config,
    update_config,
)
import autostart
import config
import scheduled_tasks
from scheduled_tasks import NotificationType, RepeatType, ScheduledTask, TaskStatus
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


class ConfigItemWidget(QWidget):
    """配置组列表项组件 - 完全自己管理状态"""

    selected = Signal(str)  # 信号：被选中查看/编辑，传递配置ID
    activated = Signal(str)  # 信号：被激活，传递配置ID
    
    def __init__(self, config_item: LLMConfigItem, is_active: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.config_id = config_item.id
        self._is_active = is_active
        self._setup_ui(config_item)
        self._update_appearance()

    def _setup_ui(self, config_item: LLMConfigItem) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        # 使用一个简单的指示器代替 QRadioButton
        self._indicator = QLabel("●")
        self._indicator.setFixedWidth(20)
        self._indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._indicator)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)

        self._name_label = QLabel(config_item.name)
        self._name_label.setFont(QFont("Microsoft YaHei", 9, QFont.Weight.Bold))
        info_layout.addWidget(self._name_label)

        self._model_label = QLabel(config_item.model_name)
        self._model_label.setFont(QFont("Microsoft YaHei", 8))
        self._model_label.setStyleSheet("color: #6b7280;")
        info_layout.addWidget(self._model_label)

        layout.addLayout(info_layout, stretch=1)

        # 让点击整个区域也触发选中
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        # 安装事件过滤器来处理点击
        self._indicator.installEventFilter(self)

    def eventFilter(self, obj, event):
        """事件过滤器，处理指示器的点击"""
        if obj == self._indicator and event.type() == event.Type.MouseButtonPress:
            self.activated.emit(self.config_id)
            return True
        return False

    def mousePressEvent(self, event) -> None:
        """点击整个控件时，选中为编辑对象（不激活）"""
        super().mousePressEvent(event)
        self.selected.emit(self.config_id)

    def set_active(self, is_active: bool) -> None:
        """设置激活状态"""
        logger.debug(f"[ConfigItemWidget] set_active called for {self.config_id}, is_active={is_active}")
        self._is_active = is_active
        self._update_appearance()

    def _update_appearance(self) -> None:
        """更新外观显示 - 简单直接"""
        logger.debug(f"[ConfigItemWidget] _update_appearance called for {self.config_id}, is_active={self._is_active}")
        
        # 更新指示器颜色
        if self._is_active:
            self._indicator.setStyleSheet("color: #10b981; font-weight: bold;")
        else:
            self._indicator.setStyleSheet("color: #d1d5db;")
        
        # 使用 QPalette 来设置背景色
        palette = self.palette()
        if self._is_active:
            palette.setColor(self.backgroundRole(), QColor("#ecfdf5"))
        else:
            palette.setColor(self.backgroundRole(), QColor(0, 0, 0, 0))  # 透明
        
        self.setPalette(palette)
        self.setAutoFillBackground(True)
        self.update()


class ConfigEditPanel(QWidget):
    """配置参数编辑面板"""

    config_saved = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current_config_id: str | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        title = QLabel("配置参数编辑")
        title.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        layout.addWidget(title)

        form_layout = QVBoxLayout()
        form_layout.setSpacing(6)

        self._config_name_edit = QLineEdit()
        self._config_name_edit.setPlaceholderText("配置名称（如：主配置、备用配置）")
        self._config_name_edit.setObjectName("configNameEdit")
        form_layout.addWidget(QLabel("配置名称："))
        form_layout.addWidget(self._config_name_edit)

        self._model_name_edit = QLineEdit()
        self._model_name_edit.setPlaceholderText("模型名称（如：qwen3.5-plus、glm-4）")
        form_layout.addWidget(QLabel("模型名称："))
        form_layout.addWidget(self._model_name_edit)

        self._api_key_edit = QLineEdit()
        self._api_key_edit.setPlaceholderText("API Key")
        self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form_layout.addWidget(QLabel("API Key："))
        form_layout.addWidget(self._api_key_edit)

        self._base_url_edit = QLineEdit()
        self._base_url_edit.setPlaceholderText("API 基础 URL")
        form_layout.addWidget(QLabel("Base URL："))
        form_layout.addWidget(self._base_url_edit)

        temp_layout = QHBoxLayout()
        temp_layout.addWidget(QLabel("温度系数："))
        self._temperature_edit = QLineEdit()
        self._temperature_edit.setPlaceholderText("0.7")
        self._temperature_edit.setFixedWidth(80)
        temp_layout.addWidget(self._temperature_edit)
        temp_hint = QLabel("（0-2，值越高越随机）")
        temp_hint.setStyleSheet("color: #6b7280; font-size: 8pt;")
        temp_layout.addWidget(temp_hint)
        temp_layout.addStretch()
        form_layout.addLayout(temp_layout)

        top_p_layout = QHBoxLayout()
        top_p_layout.addWidget(QLabel("Top P："))
        self._top_p_edit = QLineEdit()
        self._top_p_edit.setPlaceholderText("0.95")
        self._top_p_edit.setFixedWidth(80)
        top_p_layout.addWidget(self._top_p_edit)
        top_p_hint = QLabel("（0-1，值越小越聚焦）")
        top_p_hint.setStyleSheet("color: #6b7280; font-size: 8pt;")
        top_p_layout.addWidget(top_p_hint)
        top_p_layout.addStretch()
        form_layout.addLayout(top_p_layout)

        freq_layout = QHBoxLayout()
        freq_layout.addWidget(QLabel("频率惩罚："))
        self._frequency_penalty_edit = QLineEdit()
        self._frequency_penalty_edit.setPlaceholderText("0.6")
        self._frequency_penalty_edit.setFixedWidth(80)
        freq_layout.addWidget(self._frequency_penalty_edit)
        freq_hint = QLabel("（值越高越避免重复）")
        freq_hint.setStyleSheet("color: #6b7280; font-size: 8pt;")
        freq_layout.addWidget(freq_hint)
        freq_layout.addStretch()
        form_layout.addLayout(freq_layout)

        layout.addLayout(form_layout)

        save_btn = QPushButton("保存参数")
        save_btn.setObjectName("skillAgentSettingsSaveConfigButton")
        save_btn.clicked.connect(self._on_save)
        layout.addWidget(save_btn)

        layout.addStretch()

    def load_config(self, config_item: LLMConfigItem | None) -> None:
        if config_item is None:
            self._current_config_id = None
            self._config_name_edit.clear()
            self._model_name_edit.clear()
            self._api_key_edit.clear()
            self._base_url_edit.clear()
            self._temperature_edit.clear()
            self._top_p_edit.clear()
            self._frequency_penalty_edit.clear()
            self.setEnabled(False)
            return

        self._current_config_id = config_item.id
        self._config_name_edit.setText(config_item.name)
        self._model_name_edit.setText(config_item.model_name)
        self._api_key_edit.setText(config_item.api_key)
        self._base_url_edit.setText(config_item.base_url)
        self._temperature_edit.setText(str(config_item.temperature))
        self._top_p_edit.setText(str(config_item.top_p))
        self._frequency_penalty_edit.setText(str(config_item.frequency_penalty))
        self.setEnabled(True)

    def _on_save(self) -> None:
        if not self._current_config_id:
            QMessageBox.warning(self, "警告", "请先选择一个配置组")
            return

        config_name = self._config_name_edit.text().strip()
        model_name = self._model_name_edit.text().strip()
        api_key = self._api_key_edit.text().strip()
        base_url = self._base_url_edit.text().strip()

        if not config_name:
            QMessageBox.warning(self, "警告", "请输入配置名称")
            return
        if not model_name:
            QMessageBox.warning(self, "警告", "请输入模型名称")
            return
        if not api_key:
            QMessageBox.warning(self, "警告", "请输入 API Key")
            return
        if not base_url:
            QMessageBox.warning(self, "警告", "请输入 API 基础 URL")
            return

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

        updated_config = LLMConfigItem(
            id=self._current_config_id,
            name=config_name,
            model_name=model_name,
            api_key=api_key,
            base_url=base_url,
            temperature=temperature,
            top_p=top_p,
            frequency_penalty=frequency_penalty,
            enable_thinking=True,
        )

        if update_config(self._current_config_id, updated_config):
            QMessageBox.information(self, "提示", "配置已保存")
            self.config_saved.emit()
        else:
            QMessageBox.warning(self, "警告", "保存配置失败")


class TaskEditDialog(QDialog):
    """添加/编辑定时任务对话框"""

    def __init__(
        self,
        parent: QWidget | None = None,
        task: ScheduledTask | None = None,
        user_id: str = "default",
    ) -> None:
        super().__init__(parent)
        self._task = task
        self._user_id = user_id
        self._result_task: ScheduledTask | None = None
        self._setup_ui()
        self._apply_style()
        if task:
            self._load_task(task)
        else:
            self._update_datetime_display()
            self._on_execution_type_changed()

    def _apply_style(self) -> None:
        style = StyleManager.get_style("settings_dialog_stylesheet")
        if style:
            self.setStyleSheet(style)

    def _setup_ui(self) -> None:
        self.setWindowTitle("添加任务" if self._task is None else "编辑任务")
        self.setModal(True)
        self.resize(480, 500)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title_label = QLabel("任务标题：")
        layout.addWidget(title_label)
        self._title_edit = QLineEdit()
        self._title_edit.setPlaceholderText("请输入任务标题")
        layout.addWidget(self._title_edit)

        content_label = QLabel("任务内容：")
        layout.addWidget(content_label)
        self._content_edit = QTextEdit()
        self._content_edit.setPlaceholderText("请输入任务内容")
        self._content_edit.setMaximumHeight(80)
        layout.addWidget(self._content_edit)

        time_layout = QHBoxLayout()
        time_label = QLabel("触发时间：")
        time_layout.addWidget(time_label)
        self._datetime_edit = QDateTimeEdit()
        self._datetime_edit.setCalendarPopup(True)
        self._datetime_edit.setDateTime(datetime.now())
        self._datetime_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        time_layout.addWidget(self._datetime_edit)
        time_layout.addStretch()
        layout.addLayout(time_layout)

        repeat_layout = QHBoxLayout()
        repeat_label = QLabel("重复类型：")
        repeat_layout.addWidget(repeat_label)
        self._repeat_combo = QComboBox()
        self._repeat_combo.addItem("单次", "none")
        self._repeat_combo.addItem("每日", "daily")
        self._repeat_combo.addItem("每周", "weekly")
        self._repeat_combo.addItem("每月", "monthly")
        self._repeat_combo.currentIndexChanged.connect(self._on_repeat_type_changed)
        repeat_layout.addWidget(self._repeat_combo)
        repeat_layout.addStretch()
        layout.addLayout(repeat_layout)

        exec_layout = QHBoxLayout()
        exec_label = QLabel("执行方式：")
        exec_layout.addWidget(exec_label)
        self._execution_combo = QComboBox()
        self._execution_combo.addItem("通知弹窗", "notification")
        self._execution_combo.addItem("智能体会话", "agent_conversation")
        self._execution_combo.currentIndexChanged.connect(self._on_execution_type_changed)
        exec_layout.addWidget(self._execution_combo)
        exec_layout.addStretch()
        layout.addLayout(exec_layout)

        notify_layout = QHBoxLayout()
        notify_label = QLabel("通知方式：")
        notify_layout.addWidget(notify_label)
        self._notify_combo = QComboBox()
        self._notify_combo.addItem("系统通知", "system")
        self._notify_combo.addItem("浮动窗口", "toast")
        notify_layout.addWidget(self._notify_combo)
        notify_layout.addStretch()
        self._notify_group = QWidget()
        self._notify_group.setLayout(notify_layout)
        layout.addWidget(self._notify_group)

        chain_label = QLabel("执行链路（JSON格式，可选）：")
        self._chain_group = QWidget()
        chain_layout = QVBoxLayout(self._chain_group)
        chain_layout.setContentsMargins(0, 0, 0, 0)
        chain_layout.addWidget(chain_label)
        self._chain_edit = QTextEdit()
        self._chain_edit.setPlaceholderText('{\n  "goal": "任务目标",\n  "skills": [],\n  "steps": []\n}')
        self._chain_edit.setMaximumHeight(120)
        chain_layout.addWidget(self._chain_edit)
        layout.addWidget(self._chain_group)

        layout.addStretch()

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        save_btn = btn_box.button(QDialogButtonBox.StandardButton.Save)
        if save_btn:
            save_btn.setText("保存")
        cancel_btn = btn_box.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_btn:
            cancel_btn.setText("取消")
        btn_box.accepted.connect(self._on_save)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _on_execution_type_changed(self) -> None:
        exec_type = self._execution_combo.currentData()
        if exec_type == "notification":
            self._notify_group.setVisible(True)
            self._chain_group.setVisible(False)
        else:
            self._notify_group.setVisible(False)
            self._chain_group.setVisible(True)

    def _load_task(self, task: ScheduledTask) -> None:
        self._title_edit.setText(task.title)
        self._content_edit.setPlainText(task.content)
        self._datetime_edit.setDateTime(task.trigger_time)
        repeat_idx = self._repeat_combo.findData(task.repeat_type)
        if repeat_idx >= 0:
            self._repeat_combo.setCurrentIndex(repeat_idx)
        
        exec_idx = self._execution_combo.findData(task.execution_type)
        if exec_idx >= 0:
            self._execution_combo.setCurrentIndex(exec_idx)
        
        notify_idx = self._notify_combo.findData(task.notification_type)
        if notify_idx >= 0:
            self._notify_combo.setCurrentIndex(notify_idx)
        
        if task.execution_chain:
            self._chain_edit.setPlainText(task.execution_chain)
        
        self._update_datetime_display()
        self._on_execution_type_changed()

    def _on_repeat_type_changed(self) -> None:
        self._update_datetime_display()

    def _update_datetime_display(self) -> None:
        repeat_type = self._repeat_combo.currentData()
        if repeat_type == "none":
            self._datetime_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
            self._datetime_edit.setCalendarPopup(True)
        else:
            self._datetime_edit.setDisplayFormat("HH:mm")
            self._datetime_edit.setCalendarPopup(False)

    def _on_save(self) -> None:
        title = self._title_edit.text().strip()
        content = self._content_edit.toPlainText().strip()
        trigger_time = self._datetime_edit.dateTime().toPython()
        repeat_type: RepeatType = self._repeat_combo.currentData()
        notification_type: NotificationType = self._notify_combo.currentData()
        execution_type: ExecutionType = self._execution_combo.currentData()
        
        execution_chain = None
        if execution_type == "agent_conversation":
            chain_text = self._chain_edit.toPlainText().strip()
            if chain_text:
                try:
                    import json
                    json.loads(chain_text)
                    execution_chain = chain_text
                except Exception as e:
                    QMessageBox.warning(self, "警告", f"执行链路JSON格式错误: {e}")
                    return

        if not title:
            QMessageBox.warning(self, "警告", "请输入任务标题")
            return

        try:
            if self._task:
                self._result_task = scheduled_tasks.update_task(
                    self._task.task_id,
                    title=title,
                    content=content,
                    trigger_time=trigger_time,
                    repeat_type=repeat_type,
                    notification_type=notification_type,
                    execution_type=execution_type,
                    execution_chain=execution_chain,
                )
            else:
                self._result_task = scheduled_tasks.add_task(
                    user_id=self._user_id,
                    title=title,
                    content=content,
                    trigger_time=trigger_time,
                    repeat_type=repeat_type,
                    notification_type=notification_type,
                    execution_type=execution_type,
                    execution_chain=execution_chain,
                )
            self.accept()
        except Exception as e:
            QMessageBox.warning(self, "警告", f"保存任务失败: {e}")

    def get_result(self) -> ScheduledTask | None:
        return self._result_task


class SettingsDialog(QDialog):
    """会话设置：多配置组管理、模型信息、Skill 启用/禁用。"""

    def __init__(
        self,
        parent: QWidget | None,
        skill_agent: "SkillAgent",
        *,
        on_config_changed: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("skillAgentSettingsDialog")
        self.setWindowTitle("大模型配置管理")
        self.setModal(True)
        self.resize(900, 800)
        self._skill_agent = skill_agent
        self._on_config_changed = on_config_changed
        self._disabled: set[str] = set(load_disabled_skill_ids())
        self._skill_checks: list[tuple[str, QCheckBox]] = []
        self._config_widgets: dict[str, ConfigItemWidget] = {}
        self._tasks_data: list[ScheduledTask] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        self._setup_main_content(root)
        self._setup_bottom_buttons(root)

        self._apply_style()
        self._refresh_config_list()
        self._repopulate_skill_rows()
        self._update_status_bar()

    def _apply_style(self) -> None:
        style = StyleManager.get_style("settings_dialog_stylesheet")
        if style:
            self.setStyleSheet(style)

    def _setup_main_content(self, layout: QVBoxLayout) -> None:
        # 创建 QTabWidget
        tab_widget = QTabWidget()
        
        # 第一个页签：大模型配置组管理
        config_tab = QWidget()
        config_tab_layout = QVBoxLayout(config_tab)
        config_tab_layout.setContentsMargins(0, 0, 0, 0)
        
        config_splitter = QSplitter(Qt.Orientation.Horizontal)

        left_panel = self._create_left_panel()
        config_splitter.addWidget(left_panel)

        right_panel = self._create_right_panel()
        config_splitter.addWidget(right_panel)

        config_splitter.setSizes([280, 620])
        config_tab_layout.addWidget(config_splitter)
        
        # 添加自动故障切换选项
        auto_switch_layout = QHBoxLayout()
        self._auto_switch_check = QCheckBox("启用自动故障切换（当当前配置失败时自动切换到下一组）")
        self._auto_switch_check.setChecked(is_auto_switch_enabled())
        self._auto_switch_check.stateChanged.connect(self._on_auto_switch_changed)
        auto_switch_layout.addWidget(self._auto_switch_check)
        auto_switch_layout.addStretch()
        config_tab_layout.addLayout(auto_switch_layout)
        
        # 添加状态栏
        self._status_bar = QStatusBar()
        self._status_bar.setSizeGripEnabled(False)
        config_tab_layout.addWidget(self._status_bar)
        
        tab_widget.addTab(config_tab, "大模型配置组管理")
        
        # 第二个页签：Skill管理
        skills_tab = QWidget()
        skills_tab_layout = QVBoxLayout(skills_tab)
        skills_tab_layout.setContentsMargins(0, 0, 0, 0)
        
        self._skills_scroll = QScrollArea()
        self._skills_scroll.setWidgetResizable(True)
        self._skills_inner = QWidget()
        self._skills_inner.setObjectName("skillAgentSettingsSkillsInner")
        self._skills_layout = QVBoxLayout(self._skills_inner)
        self._skills_layout.setContentsMargins(8, 8, 8, 8)
        self._skills_layout.setSpacing(6)
        self._skills_scroll.setWidget(self._skills_inner)
        skills_tab_layout.addWidget(self._skills_scroll)
        
        tab_widget.addTab(skills_tab, "Skill管理")

        self._tasks_tab = QWidget()
        tasks_tab_layout = QVBoxLayout(self._tasks_tab)
        tasks_tab_layout.setContentsMargins(8, 8, 8, 8)
        tasks_tab_layout.setSpacing(8)

        filter_layout = QHBoxLayout()
        filter_label = QLabel("状态筛选：")
        filter_label.setFont(QFont("Microsoft YaHei", 9))
        filter_layout.addWidget(filter_label)
        self._task_status_filter = QComboBox()
        self._task_status_filter.addItem("全部", "all")
        self._task_status_filter.addItem("待触发", "pending")
        self._task_status_filter.addItem("已触发", "triggered")
        self._task_status_filter.addItem("已取消", "cancelled")
        self._task_status_filter.currentIndexChanged.connect(self._on_task_filter_changed)
        filter_layout.addWidget(self._task_status_filter)
        filter_layout.addStretch()
        tasks_tab_layout.addLayout(filter_layout)

        self._task_table = QTableWidget()
        self._task_table.setColumnCount(8)
        self._task_table.setHorizontalHeaderLabels([
            "标题", "内容", "触发时间", "重复类型", "执行方式", "通知方式", "状态", "操作"
        ])
        self._task_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self._task_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._task_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        self._task_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        self._task_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        self._task_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Interactive)
        self._task_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Interactive)
        self._task_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._task_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._task_table.setAlternatingRowColors(True)
        self._task_table.itemSelectionChanged.connect(self._update_task_button_states)
        tasks_tab_layout.addWidget(self._task_table)

        task_btn_layout = QHBoxLayout()
        self._add_task_btn = QPushButton("添加任务")
        self._add_task_btn.setObjectName("skillAgentSettingsAddConfigButton")
        self._add_task_btn.clicked.connect(self._on_add_task)
        task_btn_layout.addWidget(self._add_task_btn)

        self._edit_task_btn = QPushButton("编辑任务")
        self._edit_task_btn.setObjectName("skillAgentSettingsAddConfigButton")
        self._edit_task_btn.clicked.connect(self._on_edit_task)
        self._edit_task_btn.setEnabled(False)
        task_btn_layout.addWidget(self._edit_task_btn)

        self._delete_task_btn = QPushButton("删除任务")
        self._delete_task_btn.setObjectName("skillAgentSettingsDeleteConfigButton")
        self._delete_task_btn.clicked.connect(self._on_delete_task)
        self._delete_task_btn.setEnabled(False)
        task_btn_layout.addWidget(self._delete_task_btn)

        task_btn_layout.addStretch()
        tasks_tab_layout.addLayout(task_btn_layout)

        autostart_group = QGroupBox("开机自启动设置")
        autostart_layout = QVBoxLayout(autostart_group)
        autostart_check_layout = QHBoxLayout()
        self._autostart_check = QCheckBox("启用开机自启动")
        self._autostart_check.stateChanged.connect(self._on_autostart_changed)
        autostart_check_layout.addWidget(self._autostart_check)
        autostart_check_layout.addStretch()
        autostart_layout.addLayout(autostart_check_layout)

        self._autostart_status_label = QLabel()
        self._autostart_status_label.setStyleSheet("color: #6b7280; font-size: 9pt;")
        autostart_layout.addWidget(self._autostart_status_label)
        tasks_tab_layout.addWidget(autostart_group)

        # 添加定时任务行为设置
        task_behavior_group = QGroupBox("定时任务行为设置")
        task_behavior_layout = QVBoxLayout(task_behavior_group)
        task_behavior_check_layout = QHBoxLayout()
        self._scheduled_task_show_window_check = QCheckBox("定时任务触发智能体会话时自动弹出窗口")
        self._scheduled_task_show_window_check.stateChanged.connect(self._on_scheduled_task_show_window_changed)
        task_behavior_check_layout.addWidget(self._scheduled_task_show_window_check)
        task_behavior_check_layout.addStretch()
        task_behavior_layout.addLayout(task_behavior_check_layout)
        tasks_tab_layout.addWidget(task_behavior_group)

        tab_widget.addTab(self._tasks_tab, "定时任务管理")

        self._tab_widget = tab_widget
        layout.addWidget(tab_widget)

    def _create_left_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        title = QLabel("配置组列表")
        title.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        layout.addWidget(title)

        self._config_list_widget = QWidget()
        self._config_list_layout = QVBoxLayout(self._config_list_widget)
        self._config_list_layout.setContentsMargins(0, 0, 0, 0)
        self._config_list_layout.setSpacing(4)
        self._config_list_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._config_list_widget)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(scroll, stretch=1)

        btn_layout = QVBoxLayout()
        btn_layout.setSpacing(4)

        row1 = QHBoxLayout()
        self._add_btn = QPushButton("添加配置组")
        self._add_btn.setObjectName("skillAgentSettingsAddConfigButton")
        self._add_btn.clicked.connect(self._on_add_config)
        row1.addWidget(self._add_btn)

        self._delete_btn = QPushButton("删除配置组")
        self._delete_btn.setObjectName("skillAgentSettingsDeleteConfigButton")
        self._delete_btn.clicked.connect(self._on_delete_config)
        row1.addWidget(self._delete_btn)
        btn_layout.addLayout(row1)

        row3 = QHBoxLayout()
        self._move_up_btn = QPushButton("↑ 上移")
        self._move_up_btn.setObjectName("skillAgentSettingsMoveUpButton")
        self._move_up_btn.clicked.connect(self._on_move_up)
        row3.addWidget(self._move_up_btn)

        self._move_down_btn = QPushButton("↓ 下移")
        self._move_down_btn.setObjectName("skillAgentSettingsMoveDownButton")
        self._move_down_btn.clicked.connect(self._on_move_down)
        row3.addWidget(self._move_down_btn)
        btn_layout.addLayout(row3)

        layout.addLayout(btn_layout)

        return panel

    def _create_right_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._config_edit_panel = ConfigEditPanel()
        self._config_edit_panel.config_saved.connect(self._on_config_saved)
        self._config_edit_panel.setEnabled(False)
        layout.addWidget(self._config_edit_panel)

        params_group = QGroupBox("当前 LLM 请求参数（只读）")
        params_layout = QVBoxLayout(params_group)
        self._params_edit = QTextEdit()
        self._params_edit.setReadOnly(True)
        self._params_edit.setFont(QFont("Consolas", 9))
        self._params_edit.setMinimumHeight(100)
        self._params_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        params_layout.addWidget(self._params_edit)
        layout.addWidget(params_group)

        return panel

    def _setup_bottom_buttons(self, layout: QVBoxLayout) -> None:
        btn_layout = QHBoxLayout()

        self._apply_all_btn = QPushButton("应用全部配置")
        self._apply_all_btn.setObjectName("skillAgentSettingsApplyButton")
        self._apply_all_btn.clicked.connect(self._on_apply_all)
        btn_layout.addWidget(self._apply_all_btn)

        self._reset_btn = QPushButton("恢复默认")
        self._reset_btn.setObjectName("skillAgentSettingsResetButton")
        self._reset_btn.clicked.connect(self._on_reset_config)
        btn_layout.addWidget(self._reset_btn)

        btn_layout.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_btn = buttons.button(QDialogButtonBox.StandardButton.Close)
        if close_btn is not None:
            close_btn.setText("关闭")
        buttons.rejected.connect(self.reject)
        btn_layout.addWidget(buttons)

        layout.addLayout(btn_layout)

    def _refresh_config_list(self) -> None:
        logger.debug("[SettingsDialog] _refresh_config_list called")
        # 清空现有配置列表
        while self._config_list_layout.count() > 1:
            item = self._config_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._config_widgets: dict[str, ConfigItemWidget] = {}
        configs = list_configs()
        active_config = get_active_config_item()
        active_id = active_config.id if active_config else None
        logger.debug(f"[SettingsDialog] Active config id from data: {active_id}")

        # 重新创建所有组件，自己管理互斥性
        for config_item in configs:
            is_active = (config_item.id == active_id)
            widget = ConfigItemWidget(config_item, is_active)
            widget.selected.connect(self._on_config_selected)
            widget.activated.connect(self._on_config_activate)
            self._config_list_layout.insertWidget(self._config_list_layout.count() - 1, widget)
            self._config_widgets[config_item.id] = widget
            logger.debug(f"[SettingsDialog] Created widget for {config_item.id}, is_active={is_active}")

        self._selected_config_id: str | None = active_id
        
        if active_id:
            self._load_config_to_editor(active_id)
            
        self._update_button_states()

    def _on_config_selected(self, config_id: str) -> None:
        """配置被选中用于查看/编辑"""
        self._selected_config_id = config_id
        self._load_config_to_editor(config_id)
        self._update_button_states()

    def _on_config_activate(self, config_id: str) -> None:
        """配置被激活"""
        logger.debug(f"[SettingsDialog] _on_config_activate called for {config_id}")
        if set_active_config(config_id):
            logger.debug(f"[SettingsDialog] set_active_config succeeded for {config_id}")
            self._selected_config_id = config_id
            
            # 完全自己管理互斥性：遍历所有配置项，设置正确的激活状态
            for cid, widget in self._config_widgets.items():
                is_active = (cid == config_id)
                logger.debug(f"[SettingsDialog] Setting {cid} active={is_active}")
                widget.set_active(is_active)
            
            self._load_config_to_editor(config_id)
            self._update_status_bar()
            self._refresh_params()
            if self._on_config_changed:
                self._on_config_changed()

    def _load_config_to_editor(self, config_id: str) -> None:
        configs = list_configs()
        for config_item in configs:
            if config_item.id == config_id:
                self._config_edit_panel.load_config(config_item)
                return
        self._config_edit_panel.load_config(None)

    def _update_button_states(self) -> None:
        configs = list_configs()
        has_selection = self._selected_config_id is not None
        can_delete = len(configs) > 1 and has_selection

        self._delete_btn.setEnabled(can_delete)

        if has_selection:
            config_ids = [c.id for c in configs]
            idx = config_ids.index(self._selected_config_id) if self._selected_config_id in config_ids else -1
            self._move_up_btn.setEnabled(idx > 0)
            self._move_down_btn.setEnabled(idx >= 0 and idx < len(config_ids) - 1)
        else:
            self._move_up_btn.setEnabled(False)
            self._move_down_btn.setEnabled(False)

    def _on_add_config(self) -> None:
        active_config = get_active_config_item()
        if active_config:
            new_config = LLMConfigItem(
                id=generate_config_id(),
                name="新配置",
                model_name=active_config.model_name,
                api_key=active_config.api_key,
                base_url=active_config.base_url,
                temperature=active_config.temperature,
                top_p=active_config.top_p,
                frequency_penalty=active_config.frequency_penalty,
                enable_thinking=active_config.enable_thinking,
            )
        else:
            current = get_current_config()
            new_config = LLMConfigItem.from_llm_config(current, "新配置")

        add_config(new_config)
        self._refresh_config_list()
        self._selected_config_id = new_config.id
        self._load_config_to_editor(new_config.id)
        self._update_status_bar()
        QMessageBox.information(self, "提示", f"已添加配置组「{new_config.name}」，请在右侧编辑参数")

    def _on_delete_config(self) -> None:
        if not self._selected_config_id:
            return

        configs = list_configs()
        if len(configs) <= 1:
            QMessageBox.warning(self, "警告", "至少需要保留一个配置组")
            return

        config_to_delete = None
        for c in configs:
            if c.id == self._selected_config_id:
                config_to_delete = c
                break

        if not config_to_delete:
            return

        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除配置组「{config_to_delete.name}」吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            active_config = get_active_config_item()
            was_active = active_config and active_config.id == self._selected_config_id

            if delete_config(self._selected_config_id):
                if was_active:
                    new_active = get_active_config_item()
                    if new_active:
                        self._selected_config_id = new_active.id
                else:
                    self._selected_config_id = None

                self._refresh_config_list()
                self._update_status_bar()
                if self._selected_config_id:
                    self._load_config_to_editor(self._selected_config_id)
                else:
                    self._config_edit_panel.load_config(None)
                QMessageBox.information(self, "提示", "配置组已删除")

    def _on_move_up(self) -> None:
        if self._selected_config_id and move_config_up(self._selected_config_id):
            self._refresh_config_list()
            self._update_status_bar()

    def _on_move_down(self) -> None:
        if self._selected_config_id and move_config_down(self._selected_config_id):
            self._refresh_config_list()
            self._update_status_bar()

    def _on_auto_switch_changed(self, state: int) -> None:
        multi_config = get_current_multi_config()
        multi_config.auto_switch_on_failure = state == Qt.CheckState.Checked.value
        set_multi_config(multi_config)

    def _on_config_saved(self) -> None:
        self._refresh_config_list()
        self._update_status_bar()
        if self._on_config_changed:
            self._on_config_changed()

    def _on_apply_all(self) -> None:
        self._refresh_params()
        QMessageBox.information(self, "提示", "配置已应用")
        if self._on_config_changed:
            self._on_config_changed()

    def _on_reset_config(self) -> None:
        reply = QMessageBox.question(
            self,
            "确认",
            "确定要恢复默认配置吗？这将使用 .env 文件中的设置。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            reset_to_default()
            self._refresh_config_list()
            self._update_status_bar()
            self._refresh_params()
            self._auto_switch_check.setChecked(is_auto_switch_enabled())
            QMessageBox.information(self, "提示", "已恢复默认配置")
            if self._on_config_changed:
                self._on_config_changed()

    def _update_status_bar(self) -> None:
        active_config = get_active_config_item()
        if active_config:
            status_text = f"当前激活：「{active_config.name}」({active_config.model_name})"
        else:
            status_text = "无激活配置"

        switch_events = get_switch_events()
        if switch_events:
            last_event = switch_events[-1]
            status_text += f" | 最近切换: {last_event.get('reason', '未知')}"

        self._status_bar.showMessage(status_text)

    def _refresh_params(self) -> None:
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
            
            skill_type = getattr(s, 'skill_type', 'user')
            type_indicator = ""
            if skill_type == "builtin":
                type_indicator = " [内置]"
            
            name_lab = QLabel(f"{sid} · {s.name or ''}{type_indicator}")
            name_lab.setWordWrap(True)
            row.addWidget(name_lab, stretch=1)
            
            if skill_type != "builtin":
                delete_btn = QPushButton("删除")
                delete_btn.setFixedSize(50, 24)
                delete_btn.clicked.connect(lambda _, _sid=sid, _s=s: self._on_delete_skill(_sid, _s))
                row.addWidget(delete_btn)
            
            self._skills_layout.addLayout(row)
            self._skill_checks.append((sid, cb))
        self._skills_layout.addStretch(1)

    def _on_delete_skill(self, skill_id: str, skill: Any) -> None:
        skill_type = getattr(skill, 'skill_type', 'user')
        if skill_type == "builtin":
            QMessageBox.warning(self, "警告", "系统内置 Skill 不可移除")
            return
        
        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除 Skill「{skill_id}」吗？\n\n这将删除该 Skill 的文件夹及其所有内容。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                success = self._skill_agent.registry.delete_skill(skill_id)
                if success:
                    self._disabled.discard(skill_id)
                    save_disabled_skill_ids(self._disabled)
                    self._repopulate_skill_rows()
                    QMessageBox.information(self, "提示", f"Skill「{skill_id}」已删除")
                else:
                    QMessageBox.warning(self, "警告", f"删除 Skill「{skill_id}」失败")
            except Exception as e:
                QMessageBox.warning(self, "警告", f"删除 Skill 时发生错误: {e}")

    def _on_skill_toggled(self, skill_id: str, cb: QCheckBox) -> None:
        if cb.isChecked():
            self._disabled.discard(skill_id)
        else:
            self._disabled.add(skill_id)
        save_disabled_skill_ids(self._disabled)

    def _refresh_task_list(self) -> None:
        filter_data = self._task_status_filter.currentData()
        status: TaskStatus | None = None if filter_data == "all" else filter_data
        tasks = scheduled_tasks.list_tasks(status=status)
        self._task_table.setRowCount(len(tasks))
        self._tasks_data: list[ScheduledTask] = tasks

        repeat_map = {"none": "单次", "daily": "每日", "weekly": "每周", "monthly": "每月"}
        notify_map = {"system": "系统通知", "toast": "浮动窗口"}
        exec_map = {"notification": "通知弹窗", "agent_conversation": "智能体会话"}
        status_map = {"pending": "待触发", "triggered": "已触发", "cancelled": "已取消"}

        for row, task in enumerate(tasks):
            self._task_table.setItem(row, 0, QTableWidgetItem(task.title))
            content_item = QTableWidgetItem(task.content[:50] + "..." if len(task.content) > 50 else task.content)
            self._task_table.setItem(row, 1, content_item)
            if task.repeat_type == "none":
                time_str = task.trigger_time.strftime("%Y-%m-%d %H:%M")
            else:
                time_str = task.trigger_time.strftime("%H:%M")
            self._task_table.setItem(row, 2, QTableWidgetItem(time_str))
            self._task_table.setItem(row, 3, QTableWidgetItem(repeat_map.get(task.repeat_type, task.repeat_type)))
            self._task_table.setItem(row, 4, QTableWidgetItem(exec_map.get(task.execution_type, task.execution_type)))
            self._task_table.setItem(row, 5, QTableWidgetItem(notify_map.get(task.notification_type, task.notification_type)))
            self._task_table.setItem(row, 6, QTableWidgetItem(status_map.get(task.status, task.status)))

            action_widget = QWidget()
            action_layout = QHBoxLayout(action_widget)
            action_layout.setContentsMargins(4, 2, 4, 2)
            action_layout.setSpacing(4)

            edit_btn = QPushButton("编辑")
            edit_btn.setFixedSize(50, 24)
            edit_btn.clicked.connect(lambda _, t=task: self._edit_task_direct(t))
            action_layout.addWidget(edit_btn)

            cancel_btn = QPushButton("取消")
            cancel_btn.setFixedSize(50, 24)
            cancel_btn.clicked.connect(lambda _, t=task: self._cancel_task_direct(t))
            if task.status != "pending":
                cancel_btn.setEnabled(False)
            action_layout.addWidget(cancel_btn)

            self._task_table.setCellWidget(row, 7, action_widget)

        self._task_table.resizeColumnsToContents()
        self._update_task_button_states()

    def _on_task_filter_changed(self) -> None:
        self._refresh_task_list()

    def _update_task_button_states(self) -> None:
        selected_rows = self._task_table.selectedItems()
        has_selection = len(selected_rows) > 0
        self._edit_task_btn.setEnabled(has_selection)
        self._delete_task_btn.setEnabled(has_selection)

    def _on_add_task(self) -> None:
        dialog = TaskEditDialog(self, user_id="default")
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._refresh_task_list()
            QMessageBox.information(self, "提示", "任务已添加")

    def _on_edit_task(self) -> None:
        selected_rows = self._task_table.selectedItems()
        if not selected_rows:
            return
        row = selected_rows[0].row()
        if row < len(self._tasks_data):
            self._edit_task_direct(self._tasks_data[row])

    def _edit_task_direct(self, task: ScheduledTask) -> None:
        dialog = TaskEditDialog(self, task=task, user_id="default")
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._refresh_task_list()
            QMessageBox.information(self, "提示", "任务已更新")

    def _on_delete_task(self) -> None:
        selected_rows = self._task_table.selectedItems()
        if not selected_rows:
            return
        row = selected_rows[0].row()
        if row >= len(self._tasks_data):
            return
        task = self._tasks_data[row]
        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除任务「{task.title}」吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            if scheduled_tasks.delete_task(task.task_id):
                self._refresh_task_list()
                QMessageBox.information(self, "提示", "任务已删除")

    def _cancel_task_direct(self, task: ScheduledTask) -> None:
        if task.status != "pending":
            return
        reply = QMessageBox.question(
            self,
            "确认取消",
            f"确定要取消任务「{task.title}」吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            scheduled_tasks.update_task_status(task.task_id, "cancelled")
            self._refresh_task_list()
            QMessageBox.information(self, "提示", "任务已取消")

    def _on_autostart_changed(self, state: int) -> None:
        enabled = state == Qt.CheckState.Checked.value
        if enabled:
            success = autostart.enable_autostart()
            if success:
                QMessageBox.information(self, "提示", "开机自启动已启用")
            else:
                QMessageBox.warning(self, "警告", "启用开机自启动失败")
                self._autostart_check.setChecked(False)
        else:
            success = autostart.disable_autostart()
            if success:
                QMessageBox.information(self, "提示", "开机自启动已禁用")
            else:
                QMessageBox.warning(self, "警告", "禁用开机自启动失败")
                self._autostart_check.setChecked(True)
        self._update_autostart_status()

    def _update_autostart_status(self) -> None:
        status = autostart.get_autostart_status()
        if status["enabled"]:
            self._autostart_check.setChecked(True)
            self._autostart_status_label.setText("状态：已启用开机自启动")
        else:
            self._autostart_check.setChecked(False)
            self._autostart_status_label.setText("状态：未启用开机自启动")

    def _on_scheduled_task_show_window_changed(self, state: int) -> None:
        """处理定时任务弹出窗口选项变更"""
        enabled = state == Qt.CheckState.Checked.value
        try:
            success = config.set_config("SCHEDULED_TASK_SHOW_WINDOW", "true" if enabled else "false")
            if success:
                # 更新内存中的配置值
                config.SCHEDULED_TASK_SHOW_WINDOW = enabled
            else:
                QMessageBox.warning(self, "警告", "保存设置失败")
                # 恢复原值
                self._scheduled_task_show_window_check.blockSignals(True)
                self._scheduled_task_show_window_check.setChecked(not enabled)
                self._scheduled_task_show_window_check.blockSignals(False)
        except Exception as e:
            logger.exception(f"保存定时任务设置失败: {e}")
            QMessageBox.warning(self, "警告", f"保存设置失败: {e}")

    def _update_scheduled_task_show_window_status(self) -> None:
        """更新定时任务弹出窗口选项的状态"""
        try:
            # 使用 config 模块的函数重新读取配置值
            _stsw = config.get_config("SCHEDULED_TASK_SHOW_WINDOW")
            current_value = config._env_bool(_stsw, False)
            self._scheduled_task_show_window_check.setChecked(current_value)
        except Exception as e:
            logger.exception(f"读取定时任务设置失败: {e}")

    def showEvent(self, event: Any) -> None:
        super().showEvent(event)
        self._skill_agent.reload_skills()
        self._disabled = set(load_disabled_skill_ids())
        self._repopulate_skill_rows()
        self._refresh_config_list()
        self._refresh_params()
        self._update_status_bar()
        self._auto_switch_check.setChecked(is_auto_switch_enabled())
        self._refresh_task_list()
        self._update_autostart_status()
        self._update_scheduled_task_show_window_status()