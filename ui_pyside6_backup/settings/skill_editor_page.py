"""
Markdown富文本Skill编辑器页面

提供Markdown格式的Skill编辑功能，支持实时渲染和"/"触发工具列表。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Optional

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from logger import get_module_logger
from ui.styles.style_manager import StyleManager
from automation.builtin_tools import get_registry, ToolDefinition
from base_tool import TOOL_CATALOG, get_tool_registry

if TYPE_CHECKING:
    from skill.skill_manager import SkillData
    from base_tool.definitions import CONTROL_TOOL_DEFINITIONS

logger = get_module_logger("skill_editor_page")


def get_all_tools_for_display() -> list[dict[str, Any]]:
    """获取所有工具用于显示（从统一注册表获取所有工具）"""
    registry = get_tool_registry()
    tools = []

    # 从统一注册表获取所有工具（包括 atomic、control、automation 类别）
    for tool_info in registry.get_all_tools_flat():
        tool_name = tool_info.get("name", "")
        tool_desc = tool_info.get("description", "")
        tool_category = tool_info.get("category", "atomic")
        # 简化描述（只取第一行）
        simple_desc = tool_desc.split("\n")[0] if tool_desc else ""
        tools.append({
            "name": tool_name,
            "category": tool_category,
            "description": simple_desc,
            "full_description": tool_desc,
            "parameters": tool_info.get("parameters", {}),
        })

    return tools


class ToolListPopup(QWidget):
    """工具列表弹出窗口"""

    tool_selected = Signal(str)  # 工具选中信号

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Popup)
        self._filter_text = ""
        self._setup_ui()
        self._apply_style()

    def _apply_style(self) -> None:
        self.setStyleSheet("""
            ToolListPopup {
                background-color: #ffffff;
                border: 1px solid #e4e7ec;
                border-radius: 4px;
            }
            QListWidget {
                border: none;
                background-color: transparent;
            }
            QListWidget::item {
                padding: 8px 12px;
                border-bottom: 1px solid #f0f0f0;
            }
            QListWidget::item:selected {
                background-color: #e8f4fc;
                color: #1a73e8;
            }
            QListWidget::item:hover {
                background-color: #f5f5f5;
            }
        """)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(0)

        # 标题
        title_label = QLabel("内置工具列表")
        title_label.setStyleSheet("font-weight: bold; padding: 4px 8px; color: #333;")
        layout.addWidget(title_label)

        # 工具列表
        self._list_widget = QListWidget()
        self._list_widget.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._list_widget)

        self.setMaximumHeight(300)
        self.setMinimumWidth(280)

    def show_tools(self, tools: list[dict[str, Any]], position: tuple[int, int]) -> None:
        """显示工具列表"""
        self._filter_text = ""
        self._update_list(tools)
        self.move(position[0], position[1])
        self.show()
        self.setFocus()
        # 选中第一个非分类项
        for i in range(self._list_widget.count()):
            item = self._list_widget.item(i)
            if item.data(Qt.ItemDataRole.UserRole) is not None:
                self._list_widget.setCurrentItem(item)
                break

    def update_filter(self, filter_text: str) -> None:
        """更新过滤文本"""
        self._filter_text = filter_text
        tools_data = get_all_tools_for_display()
        self._update_list(tools_data)

    def _update_list(self, all_tools: list[dict[str, Any]]) -> None:
        """根据过滤文本更新列表"""
        self._list_widget.clear()

        # 按类别分组显示
        current_category = None
        filtered_count = 0

        for tool in all_tools:
            category = tool.get("category", "executor")
            if category != current_category:
                # 添加类别分隔
                category_names = {
                    "locators": "定位器",
                    "executors": "执行器",
                    "extractors": "提取器",
                    "conditions": "条件判断",
                    "atomic": "原子工具",
                    "control": "控制工具",
                }
                category_item = QListWidgetItem(f"── {category_names.get(category, category)} ──")
                category_item.setData(Qt.ItemDataRole.UserRole, None)
                category_item.setFlags(category_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                from PySide6.QtGui import QColor, QFont
                category_item.setForeground(QColor("#888888"))
                font = QFont()
                font.setPointSize(9)
                category_item.setFont(font)
                self._list_widget.addItem(category_item)
                current_category = category

            # 过滤：检查工具名是否包含过滤文本
            tool_name = tool["name"]
            if self._filter_text and self._filter_text.lower() not in tool_name.lower():
                continue

            filtered_count += 1
            # 添加工具项
            item = QListWidgetItem(f"/{tool_name}")
            item.setData(Qt.ItemDataRole.UserRole, tool_name)
            item.setToolTip(f"{tool.get('description', '')}\n类别: {category}")
            self._list_widget.addItem(item)

        # 如果没有匹配项，显示提示
        if filtered_count == 0:
            no_match_item = QListWidgetItem("无匹配工具")
            no_match_item.setData(Qt.ItemDataRole.UserRole, None)
            no_match_item.setFlags(no_match_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            no_match_item.setForeground(QColor("#999999"))
            self._list_widget.addItem(no_match_item)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        tool_name = item.data(Qt.ItemDataRole.UserRole)
        if tool_name:
            self.tool_selected.emit(tool_name)
            self.hide()

    def keyPressEvent(self, event) -> None:
        """键盘事件处理"""
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
        elif event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            current_item = self._list_widget.currentItem()
            if current_item:
                tool_name = current_item.data(Qt.ItemDataRole.UserRole)
                if tool_name:
                    self.tool_selected.emit(tool_name)
                    self.hide()
        elif event.key() == Qt.Key.Key_Up:
            # 向上导航，跳过分类项
            current_row = self._list_widget.currentRow()
            for i in range(current_row - 1, -1, -1):
                item = self._list_widget.item(i)
                if item.data(Qt.ItemDataRole.UserRole) is not None:
                    self._list_widget.setCurrentRow(i)
                    break
        elif event.key() == Qt.Key.Key_Down:
            # 向下导航，跳过分类项
            current_row = self._list_widget.currentRow()
            count = self._list_widget.count()
            for i in range(current_row + 1, count):
                item = self._list_widget.item(i)
                if item.data(Qt.ItemDataRole.UserRole) is not None:
                    self._list_widget.setCurrentRow(i)
                    break
        elif event.key() == Qt.Key.Key_Backspace:
            # 退格键：移除最后一个过滤字符
            if self._filter_text:
                self._filter_text = self._filter_text[:-1]
                tools_data = get_all_tools_for_display()
                self._update_list(tools_data)
        elif len(event.text()) > 0 and event.text().isprintable():
            # 可打印字符：添加到过滤文本
            self._filter_text += event.text()
            tools_data = get_all_tools_for_display()
            self._update_list(tools_data)
        else:
            super().keyPressEvent(event)

    def focusOutEvent(self, event) -> None:
        """失去焦点时隐藏"""
        self.hide()


class MarkdownEditor(QWidget):
    """Markdown编辑器组件"""

    content_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tool_popup: Optional[ToolListPopup] = None
        self._slash_pos: int = -1  # "/" 在编辑器中的位置
        self._popup_active: bool = False  # 弹出窗口是否活跃
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # 使用分割器
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 左侧：Markdown文本编辑区域
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        editor_title = QLabel("Markdown编辑")
        editor_title.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        left_layout.addWidget(editor_title)

        self._text_editor = QPlainTextEdit()
        self._text_editor.setPlaceholderText(
            "输入 Markdown 内容...\n"
            "输入 '/' 可触发内置工具列表\n"
            "例如: 使用 /click 执行点击操作"
        )
        self._text_editor.setFont(QFont("Microsoft YaHei", 10))
        self._text_editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        left_layout.addWidget(self._text_editor)

        splitter.addWidget(left_panel)

        # 右侧：Markdown实时渲染区域
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)

        render_title = QLabel("实时预览")
        render_title.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        right_layout.addWidget(render_title)

        self._render_area = QTextBrowser()
        self._render_area.setFont(QFont("Microsoft YaHei", 10))
        self._render_area.setOpenExternalLinks(True)
        right_layout.addWidget(self._render_area)

        splitter.addWidget(right_panel)
        splitter.setSizes([400, 400])

        layout.addWidget(splitter)

    def _connect_signals(self) -> None:
        """连接信号"""
        self._text_editor.textChanged.connect(self._on_text_changed)
        self._text_editor.textChanged.connect(self.content_changed.emit)

        # 使用定时器延迟渲染，避免频繁更新
        self._render_timer = QTimer()
        self._render_timer.setSingleShot(True)
        self._render_timer.timeout.connect(self._render_markdown)

    def _on_text_changed(self) -> None:
        """文本变化时检查是否触发工具列表或更新过滤"""
        text = self._text_editor.toPlainText()
        cursor = self._text_editor.textCursor()
        cursor_pos = cursor.position()

        if self._popup_active:
            # 弹出窗口活跃时，检查是否有过滤关键词
            # 查找从 slash_pos 到当前光标之间的文本
            if self._slash_pos >= 0 and self._slash_pos < cursor_pos:
                filter_text = text[self._slash_pos + 1:cursor_pos]
                # 如果过滤文本包含非字母数字字符（如空格、换行），关闭弹出窗口
                if filter_text and not all(c.isalnum() or c == '_' for c in filter_text):
                    self._close_tool_popup()
                else:
                    # 更新过滤
                    if self._tool_popup:
                        self._tool_popup.update_filter(filter_text)
            else:
                self._close_tool_popup()
        else:
            # 弹出窗口未活跃，检查是否输入了 "/"
            if cursor_pos > 0 and text[cursor_pos - 1] == "/":
                # 检查是否是行首或前面是空格/换行
                if cursor_pos == 1 or text[cursor_pos - 2] in (" ", "\n", "\t"):
                    self._slash_pos = cursor_pos - 1
                    self._show_tool_popup()

        # 延迟渲染Markdown
        self._render_timer.start(300)

    def _close_tool_popup(self) -> None:
        """关闭工具弹出窗口"""
        self._popup_active = False
        self._slash_pos = -1
        if self._tool_popup:
            self._tool_popup.hide()

    def _show_tool_popup(self) -> None:
        """显示工具列表弹出窗口"""
        if self._tool_popup is None:
            self._tool_popup = ToolListPopup(self)
            self._tool_popup.tool_selected.connect(self._insert_tool_reference)

        # 获取光标位置
        cursor = self._text_editor.textCursor()
        cursor_rect = self._text_editor.cursorRect(cursor)
        global_pos = self._text_editor.mapToGlobal(cursor_rect.bottomLeft())

        # 获取工具列表
        tools_data = get_all_tools_for_display()

        if tools_data:
            self._popup_active = True
            self._tool_popup.show_tools(tools_data, (global_pos.x(), global_pos.y() + 20))

    def _insert_tool_reference(self, tool_name: str) -> None:
        """插入工具引用（自然语言格式：使用工具{tool_name(param1="value1")}）"""
        if not self._popup_active:
            return

        cursor = self._text_editor.textCursor()
        cursor_pos = cursor.position()

        # 删除从 slash_pos 到当前光标的所有文本（包括 "/" 和过滤关键词）
        if self._slash_pos >= 0 and self._slash_pos < cursor_pos:
            cursor.setPosition(self._slash_pos, QTextCursor.MoveMode.MoveAnchor)
            cursor.setPosition(cursor_pos, QTextCursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()

        # 从统一注册表查找工具定义
        registry = get_tool_registry()
        tool_info = registry.get_tool_by_name(tool_name)

        if tool_info:
            definition = tool_info.get("definition", {})
            expr = self._generate_inline_expression(definition)
        else:
            expr = f"{{{tool_name}}}"

        cursor.insertText(f"使用工具{expr}")
        self._close_tool_popup()

    def _generate_inline_expression(self, tool_dict: dict[str, Any]) -> str:
        """根据工具定义生成内联参数表达式。

        格式：
        - 无参数：{tool_name}
        - 有参数：{tool_name(param1="value1", param2="value2")}

        参数值规则：
        - 必填参数：使用 {{user_input.参数名}} 占位符
        - 可选参数有默认值：使用默认值
        - 可选参数无默认值：不显示该参数
        - 参数值用双引号包裹
        """
        tool_name = tool_dict.get("name", "")
        parameters = tool_dict.get("parameters", {})

        if not parameters:
            return f"{{{tool_name}}}"

        properties = parameters.get("properties", {})
        required = parameters.get("required", [])

        if not properties:
            return f"{{{tool_name}}}"

        param_parts = []
        for param_name, param_def in properties.items():
            is_required = param_name in required
            if is_required:
                # 必填参数：使用 user_input 占位符
                param_parts.append(f'{param_name}="{{{{user_input.{param_name}}}}}"')
            else:
                # 可选参数：有默认值才显示
                default_val = param_def.get("default")
                if default_val is not None:
                    if isinstance(default_val, bool):
                        default_val = str(default_val).lower()
                    else:
                        default_val = str(default_val)
                    param_parts.append(f'{param_name}="{default_val}"')
                # 可选参数无默认值：不显示

        if param_parts:
            return f"{{{tool_name}({', '.join(param_parts)})}}"
        else:
            return f"{{{tool_name}}}"

    def _generate_base_tool_reference_template(self, tool_dict: dict[str, Any]) -> str:
        """生成base_tool工具引用模板（内联参数表达式格式）"""
        return self._generate_inline_expression(tool_dict)

    def _generate_tool_reference_template(self, tool: ToolDefinition) -> str:
        """生成工具引用模板（内联参数表达式格式）"""
        tool_dict = {
            "name": tool.name,
            "parameters": {
                "properties": {
                    name: {
                        "default": info.get("default"),
                    }
                    for name, info in tool.parameters.items()
                },
                "required": [
                    name for name, info in tool.parameters.items()
                    if info.get("required", False)
                ],
            },
        }
        return self._generate_inline_expression(tool_dict)

    def _render_markdown(self) -> None:
        """实时渲染Markdown内容"""
        markdown_text = self._text_editor.toPlainText()

        # 使用简单的Markdown转HTML函数
        html_content = self._simple_markdown_to_html(markdown_text)

        # 添加样式
        styled_html = f"""
            <style>
                body {{ font-family: 'Microsoft YaHei', sans-serif; font-size: 10pt; }}
                h1 {{ color: #1a73e8; border-bottom: 2px solid #e4e7ec; }}
                h2 {{ color: #333; }}
                h3 {{ color: #555; }}
                code {{ background-color: #f5f5f5; padding: 2px 4px; border-radius: 2px; }}
                pre {{ background-color: #f5f5f5; padding: 8px; border-radius: 4px; }}
                ul, ol {{ margin-left: 20px; }}
                table {{ border-collapse: collapse; }}
                th, td {{ border: 1px solid #ddd; padding: 8px; }}
            </style>
            {html_content}
            """

        self._render_area.setHtml(styled_html)

    def _simple_markdown_to_html(self, markdown_text: str) -> str:
        """简单的Markdown转HTML函数"""
        # 处理标题
        lines = markdown_text.split('\n')
        html_lines = []

        for line in lines:
            # 处理标题
            if line.startswith('# '):
                html_lines.append(f'<h1>{line[2:]}</h1>')
            elif line.startswith('## '):
                html_lines.append(f'<h2>{line[3:]}</h2>')
            elif line.startswith('### '):
                html_lines.append(f'<h3>{line[4:]}</h3>')
            # 处理列表
            elif line.startswith('- ') or line.startswith('* '):
                html_lines.append(f'<li>{line[2:]}</li>')
            elif re.match(r'^\d+\.\s', line):
                match = re.match(r'^\d+\.\s(.+)', line)
                if match:
                    html_lines.append(f'<li>{match.group(1)}</li>')
            # 处理代码块
            elif line.startswith('```'):
                html_lines.append('<pre><code>')
            elif line.endswith('```'):
                html_lines.append('</code></pre>')
            # 处理行内代码
            elif '`' in line:
                line = re.sub(r'`([^`]+)`', r'<code>\1</code>', line)
                html_lines.append(line)
            # 处理链接
            elif '[' in line and ']' in line and '(' in line and ')' in line:
                line = re.sub(r'\[([^\]]+)\]\(([^\)]+)\)', r'<a href="\2">\1</a>', line)
                html_lines.append(line)
            # 处理普通文本
            else:
                html_lines.append(line if line else '<br>')

        # 将列表项包裹在<ul>或<ol>中
        result = '\n'.join(html_lines)
        result = re.sub(r'(<li>.*?</li>\n)+', lambda m: '<ul>\n' + m.group(0) + '</ul>\n', result)

        return result

    def get_text(self) -> str:
        """获取Markdown文本"""
        return self._text_editor.toPlainText()

    def set_text(self, text: str) -> None:
        """设置Markdown文本"""
        self._text_editor.setPlainText(text)
        self._render_markdown()

    def clear(self) -> None:
        """清空内容"""
        self._text_editor.clear()
        self._render_area.clear()


class SkillEditorDialog(QDialog):
    """Skill编辑器对话框"""

    def __init__(
        self,
        skill_data: "SkillData",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._skill_data = skill_data
        self._result: Optional[str] = None
        self._setup_ui()
        self._apply_style()
        self._load_skill_data()

    def _apply_style(self) -> None:
        style = StyleManager.get_style("settings_dialog_stylesheet")
        if style:
            self.setStyleSheet(style)

    def _setup_ui(self) -> None:
        self.setWindowTitle(f"编辑Skill - {self._skill_data.metadata.name}")
        self.setModal(True)
        self.resize(900, 700)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # 标题和说明
        title = QLabel(f"编辑 Skill: {self._skill_data.metadata.name}")
        title.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        layout.addWidget(title)

        info_label = QLabel(
            "Skill采用Markdown格式存储。输入 '/' 可触发内置工具列表。\n"
            "大模型将理解Markdown内容并执行自动化操作。"
        )
        info_label.setStyleSheet("color: #6b7280; font-size: 9pt;")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        # Markdown编辑器
        self._markdown_editor = MarkdownEditor()
        layout.addWidget(self._markdown_editor, stretch=1)

        # 工具栏
        toolbar_layout = QHBoxLayout()
        toolbar_layout.setSpacing(8)

        help_btn = QPushButton("帮助")
        help_btn.clicked.connect(self._show_help)
        toolbar_layout.addWidget(help_btn)

        insert_tool_btn = QPushButton("插入工具")
        insert_tool_btn.clicked.connect(self._show_tool_list)
        toolbar_layout.addWidget(insert_tool_btn)

        toolbar_layout.addStretch()
        layout.addLayout(toolbar_layout)

        # 按钮
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

    def _load_skill_data(self) -> None:
        """加载Skill数据"""
        # 显示完整的Markdown内容
        full_content = self._skill_data.to_markdown()
        self._markdown_editor.set_text(full_content)

    def _show_help(self) -> None:
        """显示帮助信息"""
        help_text = """
Skill Markdown 编辑帮助

1. YAML Front Matter（元数据）
   ---
   id: skill_001
   name: Skill名称
   description: Skill描述
   tags: [automation, browser]
   created_at: 2026-06-13T10:00:00
   ---
   这部分定义Skill的基本信息。

2. Markdown内容
   使用标准Markdown语法编写Skill内容。

3. 工具引用
   输入 '/' 可触发内置工具列表，选择工具后自动插入引用模板。

   工具引用格式：
   使用 /tool_name 执行操作
   - 参数：param1="value1", param2="value2"

4. 参数引用
   使用 {{user_input.xxx}} 引用用户输入参数
   使用 {{step_n_result}} 引用前一步骤的结果

5. 执行流程
   在"执行流程"部分按顺序描述操作步骤，
   大模型将理解并执行这些操作。
        """
        QMessageBox.information(self, "编辑帮助", help_text)

    def _show_tool_list(self) -> None:
        """显示工具列表"""
        # 获取所有工具（合并base_tool和automation的工具）
        tools_data = get_all_tools_for_display()

        # 创建工具列表对话框
        tool_dialog = QDialog(self)
        tool_dialog.setWindowTitle("内置工具列表")
        tool_dialog.resize(500, 600)

        layout = QVBoxLayout(tool_dialog)

        # 说明标签
        info_label = QLabel("以下是目前系统定义的所有工具，可在Skill中引用：")
        info_label.setStyleSheet("color: #6b7280; font-size: 9pt; margin-bottom: 8px;")
        layout.addWidget(info_label)

        # 工具列表
        tool_list = QListWidget()
        category_names = {
            "atomic": "原子工具",
            "control": "控制工具",
            "locators": "定位器",
            "executors": "执行器",
            "extractors": "提取器",
            "conditions": "条件判断",
        }
        for tool in tools_data:
            category = category_names.get(tool.get("category", "unknown"), tool.get("category", "unknown"))
            item_text = f"/{tool['name']} [{category}]"
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, tool['name'])
            # 使用完整描述作为tooltip
            full_desc = tool.get('full_description', tool.get('description', ''))
            # 只显示前200字符作为tooltip
            tooltip_text = full_desc[:200] + "..." if len(full_desc) > 200 else full_desc
            item.setToolTip(tooltip_text)
            tool_list.addItem(item)

        layout.addWidget(tool_list)

        # 按钮
        insert_btn = QPushButton("插入")
        insert_btn.clicked.connect(lambda: self._insert_selected_tool(tool_list, tool_dialog))
        layout.addWidget(insert_btn)

        tool_list.itemDoubleClicked.connect(lambda: self._insert_selected_tool(tool_list, tool_dialog))

        tool_dialog.exec()

    def _insert_selected_tool(self, tool_list: QListWidget, dialog: QDialog) -> None:
        """插入选中的工具（自然语言格式：使用工具{tool_name(param1="value1")}）"""
        current_item = tool_list.currentItem()
        if current_item:
            tool_name = current_item.data(Qt.ItemDataRole.UserRole)
            if tool_name:
                # 从统一注册表查找工具定义
                registry = get_tool_registry()
                tool_info = registry.get_tool_by_name(tool_name)

                if tool_info:
                    definition = tool_info.get("definition", {})
                    expr = self._generate_inline_expression(definition)
                else:
                    expr = f"{{{tool_name}}}"

                # 插入到编辑器
                current_text = self._markdown_editor.get_text()
                self._markdown_editor.set_text(current_text + "\n使用工具" + expr)
                dialog.accept()

    def _on_save(self) -> None:
        """保存Skill"""
        content = self._markdown_editor.get_text()

        if not content.strip():
            QMessageBox.warning(self, "警告", "Skill内容不能为空")
            return

        self._result = content
        self.accept()

    def get_result(self) -> Optional[str]:
        return self._result