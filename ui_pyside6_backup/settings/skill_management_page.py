"""
Skill管理页面

提供用户自定义Skill的创建、编辑、删除、导入、导出功能。
采用Markdown格式存储Skill文件。
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from logger import get_module_logger
from ui.styles.style_manager import StyleManager

if TYPE_CHECKING:
    from skill.skill_manager import SkillManager, SkillMetadata, SkillData

logger = get_module_logger("skill_management_page")


class SkillCreateDialog(QDialog):
    """创建Skill对话框"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._result_data: dict[str, Any] | None = None
        self._setup_ui()
        self._apply_style()

    def _apply_style(self) -> None:
        style = StyleManager.get_style("settings_dialog_stylesheet")
        if style:
            self.setStyleSheet(style)

    def _setup_ui(self) -> None:
        self.setWindowTitle("创建新Skill")
        self.setModal(True)
        self.resize(500, 400)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Skill名称
        name_label = QLabel("Skill名称：")
        layout.addWidget(name_label)
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("输入Skill名称")
        layout.addWidget(self._name_edit)

        # Skill描述
        desc_label = QLabel("Skill描述：")
        layout.addWidget(desc_label)
        self._desc_edit = QLineEdit()
        self._desc_edit.setPlaceholderText("描述Skill的功能和用途")
        layout.addWidget(self._desc_edit)

        # Skill标签
        tags_label = QLabel("Skill标签（逗号分隔）：")
        layout.addWidget(tags_label)
        self._tags_edit = QLineEdit()
        self._tags_edit.setPlaceholderText("例如: automation, browser, search")
        layout.addWidget(self._tags_edit)

        layout.addStretch()

        # 按钮
        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        save_btn = btn_box.button(QDialogButtonBox.StandardButton.Save)
        if save_btn:
            save_btn.setText("创建")
        cancel_btn = btn_box.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_btn:
            cancel_btn.setText("取消")
        btn_box.accepted.connect(self._on_create)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _on_create(self) -> None:
        name = self._name_edit.text().strip()
        description = self._desc_edit.text().strip()
        tags_str = self._tags_edit.text().strip()

        if not name:
            QMessageBox.warning(self, "警告", "请输入Skill名称")
            return

        tags = [t.strip() for t in tags_str.split(",") if t.strip()]

        self._result_data = {
            "name": name,
            "description": description,
            "tags": tags,
        }
        self.accept()

    def get_result(self) -> dict[str, Any] | None:
        return self._result_data


class SkillManagementPage(QWidget):
    """Skill管理页面"""

    skill_created = Signal(str)  # Skill创建完成信号
    skill_updated = Signal(str)  # Skill更新完成信号
    skill_deleted = Signal(str)  # Skill删除完成信号

    def __init__(
        self,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._skill_manager: Optional["SkillManager"] = None
        self._skill_ids: list[str] = []
        self._selected_skill_id: Optional[str] = None
        self._setup_ui()
        self._apply_style()
        self._load_skills()

    def _apply_style(self) -> None:
        style = StyleManager.get_style("settings_dialog_stylesheet")
        if style:
            self.setStyleSheet(style)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)

        # 标题
        title = QLabel("用户自定义Skill管理")
        title.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        layout.addWidget(title)

        # 说明
        info_label = QLabel(
            "创建和管理自动化Skill，采用Markdown格式存储。\n"
            "支持通过\"/\"触发内置工具列表，大模型理解Markdown执行自动化操作。"
        )
        info_label.setStyleSheet("color: #6b7280; font-size: 9pt;")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        # 操作按钮行
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._create_btn = QPushButton("新建Skill")
        self._create_btn.setObjectName("skillManagementCreateButton")
        self._create_btn.clicked.connect(self._on_create_skill)
        btn_row.addWidget(self._create_btn)

        self._import_btn = QPushButton("导入Skill")
        self._import_btn.setObjectName("skillManagementImportButton")
        self._import_btn.clicked.connect(self._on_import_skill)
        btn_row.addWidget(self._import_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        # 筛选行
        filter_row = QHBoxLayout()
        filter_label = QLabel("筛选：")
        filter_row.addWidget(filter_label)

        self._filter_combo = QComboBox()
        self._filter_combo.addItem("全部", "all")
        self._filter_combo.addItem("自动化", "automation")
        self._filter_combo.addItem("浏览器", "browser")
        self._filter_combo.addItem("模板", "template")
        self._filter_combo.currentIndexChanged.connect(self._on_filter_changed)
        filter_row.addWidget(self._filter_combo)

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("搜索Skill名称...")
        self._search_edit.textChanged.connect(self._on_search_changed)
        filter_row.addWidget(self._search_edit, stretch=1)

        layout.addLayout(filter_row)

        # Skill列表区域
        list_group = QGroupBox("Skill列表")
        list_layout = QVBoxLayout(list_group)
        list_layout.setContentsMargins(8, 8, 8, 8)
        list_layout.setSpacing(8)

        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(["名称", "描述", "标签", "创建时间", "操作"])
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(48)
        self._table.horizontalHeader().setStretchLastSection(False)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(0, 110)
        self._table.setColumnWidth(2, 130)
        self._table.setColumnWidth(3, 110)
        self._table.setColumnWidth(4, 310)
        self._table.cellDoubleClicked.connect(self._on_table_double_clicked)
        list_layout.addWidget(self._table)

        layout.addWidget(list_group, stretch=1)

        # 状态栏
        self._status_label = QLabel()
        self._status_label.setStyleSheet("color: #6b7280; font-size: 9pt;")
        layout.addWidget(self._status_label)

    def _get_skill_manager(self) -> "SkillManager":
        """获取Skill管理器"""
        if self._skill_manager is None:
            from skill.skill_manager import get_manager
            self._skill_manager = get_manager()
        return self._skill_manager

    def _load_skills(self) -> None:
        """加载Skill列表"""
        # 清空表格
        self._table.clearContents()
        self._table.setRowCount(0)

        # 加载Skill
        manager = self._get_skill_manager()
        skills = manager.list_skills()

        # 应用筛选
        filter_type = self._filter_combo.currentData()
        search_text = self._search_edit.text().strip().lower()

        filtered_skills = []
        for skill in skills:
            # 类型筛选
            if filter_type != "all":
                if filter_type not in skill.tags and filter_type not in skill.name.lower():
                    continue

            # 搜索筛选
            if search_text:
                if search_text not in skill.name.lower() and search_text not in skill.description.lower():
                    continue

            filtered_skills.append(skill)

        # 填充表格
        self._skill_ids = [s.id for s in filtered_skills]
        self._table.setRowCount(len(filtered_skills))

        for row, skill in enumerate(filtered_skills):
            # 名称
            name_item = QTableWidgetItem(skill.name)
            name_item.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
            name_item.setToolTip(skill.name)
            name_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self._table.setItem(row, 0, name_item)

            # 描述
            desc_text = skill.description if skill.description else ""
            desc_item = QTableWidgetItem(desc_text)
            desc_item.setToolTip(desc_text)
            desc_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self._table.setItem(row, 1, desc_item)

            # 标签
            tags_str = ", ".join(skill.tags[:3]) if skill.tags else "无标签"
            tags_item = QTableWidgetItem(tags_str)
            tags_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self._table.setItem(row, 2, tags_item)

            # 创建时间
            if skill.created_at:
                if isinstance(skill.created_at, datetime):
                    time_str = skill.created_at.strftime("%Y-%m-%d")
                else:
                    time_str = str(skill.created_at)[:10]
            else:
                time_str = "未知"
            time_item = QTableWidgetItem(time_str)
            time_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self._table.setItem(row, 3, time_item)

            # 操作按钮
            btn_widget = QWidget()
            btn_widget.setStyleSheet("background-color: transparent;")
            btn_layout = QHBoxLayout(btn_widget)
            btn_layout.setContentsMargins(8, 6, 8, 6)
            btn_layout.setSpacing(8)

            for label, method in (
                ("编辑", self._on_edit_skill),
                ("导出", self._on_export_skill),
                ("发布", self._on_publish_skill),
                ("删除", self._on_delete_skill),
            ):
                btn = QPushButton(label)
                btn.setFixedWidth(64)
                btn.setFixedHeight(30)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.setStyleSheet(
                    "QPushButton { background-color: #f0f0f0; color: #333333; border: 1px solid #d0d0d0; border-radius: 4px; padding: 4px 8px; } "
                    "QPushButton:hover { background-color: #e0e0e0; border: 1px solid #c0c0c0; } "
                    "QPushButton:pressed { background-color: #d0d0d0; }"
                )
                btn.clicked.connect(lambda _=False, m=method, sid=skill.id: m(sid))
                btn_layout.addWidget(btn)

            btn_layout.addStretch()
            self._table.setCellWidget(row, 4, btn_widget)

        # 更新状态
        self._status_label.setText(f"共 {len(skills)} 个Skill，显示 {len(filtered_skills)} 个")

    def _on_filter_changed(self) -> None:
        self._load_skills()

    def _on_search_changed(self) -> None:
        self._load_skills()

    def _on_table_double_clicked(self, row: int, _col: int) -> None:
        if 0 <= row < len(self._skill_ids):
            self._on_edit_skill(self._skill_ids[row])

    def _on_create_skill(self) -> None:
        """创建新Skill"""
        dialog = SkillCreateDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            result = dialog.get_result()
            if result:
                manager = self._get_skill_manager()
                try:
                    skill_id = manager.create_skill(
                        name=result["name"],
                        description=result["description"],
                        tags=result["tags"],
                    )
                    self._load_skills()
                    self.skill_created.emit(skill_id)
                    QMessageBox.information(self, "提示", f"Skill '{result['name']}' 已创建")
                except Exception as e:
                    QMessageBox.warning(self, "警告", f"创建Skill失败: {e}")

    def _on_edit_skill(self, skill_id: str) -> None:
        """编辑Skill"""
        # 打开Skill编辑器
        from .skill_editor_page import SkillEditorDialog

        manager = self._get_skill_manager()
        skill = manager.get_skill(skill_id)
        if skill is None:
            QMessageBox.warning(self, "警告", f"Skill '{skill_id}' 不存在")
            return

        dialog = SkillEditorDialog(skill, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            updated_content = dialog.get_result()
            if updated_content:
                try:
                    manager.edit_skill(skill_id, updated_content)
                    self._load_skills()
                    self.skill_updated.emit(skill_id)
                    QMessageBox.information(self, "提示", "Skill已更新")
                except Exception as e:
                    QMessageBox.warning(self, "警告", f"更新Skill失败: {e}")

    def _on_delete_skill(self, skill_id: str) -> None:
        """删除Skill"""
        manager = self._get_skill_manager()
        skill = manager.get_skill_metadata(skill_id)
        if skill is None:
            return

        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除Skill '{skill.name}' 吗？\n此操作不可撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            try:
                manager.delete_skill(skill_id)
                self._load_skills()
                self.skill_deleted.emit(skill_id)
                QMessageBox.information(self, "提示", "Skill已删除")
            except Exception as e:
                QMessageBox.warning(self, "警告", f"删除Skill失败: {e}")

    def _on_import_skill(self) -> None:
        """导入Skill"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "导入Skill文件",
            "",
            "Markdown文件 (*.md);;所有文件 (*.*)",
        )

        if file_path:
            manager = self._get_skill_manager()
            try:
                skill_id = manager.import_skill(file_path)
                self._load_skills()
                self.skill_created.emit(skill_id)
                QMessageBox.information(self, "提示", f"Skill已导入，ID: {skill_id}")
            except Exception as e:
                QMessageBox.warning(self, "警告", f"导入Skill失败: {e}")

    def _on_export_skill(self, skill_id: str) -> None:
        """导出Skill"""
        manager = self._get_skill_manager()
        skill = manager.get_skill_metadata(skill_id)
        if skill is None:
            return

        default_name = f"{skill.name}.md"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "导出Skill文件",
            default_name,
            "Markdown文件 (*.md);;所有文件 (*.*)",
        )

        if file_path:
            try:
                manager.export_skill(skill_id, file_path)
                QMessageBox.information(self, "提示", f"Skill已导出到 '{file_path}'")
            except Exception as e:
                QMessageBox.warning(self, "警告", f"导出Skill失败: {e}")

    def _on_publish_skill(self, skill_id: str) -> None:
        """发布Skill"""
        manager = self._get_skill_manager()
        skill = manager.get_skill_metadata(skill_id)
        if skill is None:
            return

        # 检查是否已发布
        if manager.is_skill_published(skill_id):
            # 已发布，询问是否取消发布
            reply = QMessageBox.question(
                self,
                "取消发布",
                f"Skill '{skill.name}' 已发布。\n是否要取消发布？\n\n取消发布后，Skill将不再被SkillAgent加载，但源文件仍保留在user_defined目录中。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                try:
                    if manager.unpublish_skill(skill_id):
                        QMessageBox.information(self, "提示", f"Skill '{skill.name}' 已取消发布")
                    else:
                        QMessageBox.warning(self, "警告", "取消发布失败")
                except Exception as e:
                    QMessageBox.warning(self, "警告", f"取消发布失败: {e}")
        else:
            # 未发布，询问是否发布
            reply = QMessageBox.question(
                self,
                "发布Skill",
                f"是否要发布Skill '{skill.name}'？\n\n发布后，Skill将被复制到Skills根目录，可以被SkillAgent正常加载和使用。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                try:
                    if manager.publish_skill(skill_id):
                        QMessageBox.information(self, "提示", f"Skill '{skill.name}' 已发布，现在可以在聊天中使用")
                    else:
                        QMessageBox.warning(self, "警告", "发布失败")
                except Exception as e:
                    QMessageBox.warning(self, "警告", f"发布失败: {e}")

    def refresh(self) -> None:
        """刷新Skill列表"""
        self._load_skills()