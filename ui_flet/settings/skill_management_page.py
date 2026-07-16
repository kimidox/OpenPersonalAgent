"""
Flet 技能管理页面

提供用户自定义Skill的创建、编辑、删除、导入、导出功能。
采用Markdown格式存储Skill文件。
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

import flet as ft

from logger import get_logger
from ui_flet.theme import ThemeManager, get_color
from ui_flet.settings.skill_editor_page import SkillEditorPage

if TYPE_CHECKING:
    from skill.skill_manager import SkillManager, SkillMetadata, SkillData


class SkillManagementPage:
    """
    技能管理页面

    提供技能的列表展示、编辑、删除、导入、导出等功能。
    """

    def __init__(self, page: ft.Page) -> None:
        """
        初始化技能管理页面

        Args:
            page: Flet Page 对象
        """
        self._page = page
        self._logger = get_logger()
        self._theme_manager = ThemeManager()

        # 技能管理器
        self._skill_manager: Optional["SkillManager"] = None

        # 当前选中的技能ID
        self._selected_skill_id: Optional[str] = None

        # 技能列表数据
        self._skill_data: list[dict[str, Any]] = []

        # UI组件引用
        self._search_input: Optional[ft.TextField] = None
        self._filter_dropdown: Optional[ft.Dropdown] = None
        self._skill_list: Optional[ft.Column] = None
        self._status_text: Optional[ft.Text] = None

        # 创建主容器
        self._container: Optional[ft.Container] = None

        # 文件选择器
        self._file_picker: Optional[ft.FilePicker] = None

    def _get_skill_manager(self) -> "SkillManager":
        """获取技能管理器"""
        if self._skill_manager is None:
            from skill.skill_manager import get_manager
            self._skill_manager = get_manager()
        return self._skill_manager

    def build(self) -> ft.Container:
        """
        构建页面UI

        Returns:
            页面容器
        """
        self._logger.info("SkillManagementPage: 开始构建页面")
        colors = self._theme_manager.get_color_scheme()

        # 创建文件选择器（Service 控件，需注册到 page.services）
        self._file_picker = ft.FilePicker()
        self._page.services.append(self._file_picker)

        # 标题
        title = ft.Text(
            "用户自定义Skill管理",
            size=14,
            weight=ft.FontWeight.BOLD,
            color=colors.text,
        )

        # 说明
        info = ft.Text(
            "创建和管理自动化Skill，采用Markdown格式存储。\n"
            '支持通过"/"触发内置工具列表，大模型理解Markdown执行自动化操作。',
            size=11,
            color=colors.text_muted,
        )

        # 操作按钮行
        create_btn = ft.ElevatedButton(
            "新建Skill",
            icon=ft.Icons.ADD,
            on_click=self._on_create_click,
            bgcolor=colors.primary,
            color=colors.text_on_primary,
        )

        import_btn = ft.OutlinedButton(
            "导入Skill",
            icon=ft.Icons.FILE_UPLOAD,
            on_click=self._on_import_click,
        )

        buttons_row = ft.Row(
            [create_btn, import_btn],
            spacing=10,
        )

        # 筛选行
        filter_label = ft.Text("筛选：", size=11, weight=ft.FontWeight.BOLD, color=colors.text)

        self._filter_dropdown = ft.Dropdown(
            options=[
                ft.dropdown.Option("all", "全部"),
                ft.dropdown.Option("automation", "自动化"),
                ft.dropdown.Option("browser", "浏览器"),
                ft.dropdown.Option("template", "模板"),
            ],
            value="all",
            width=225,
            on_select=self._on_filter_change,
        )

        self._search_input = ft.TextField(
            hint_text="搜索Skill名称...",
            prefix_icon=ft.Icons.SEARCH,
            on_change=self._on_search_change,
            expand=True,
        )

        filter_row = ft.Row(
            [filter_label, self._filter_dropdown, self._search_input],
            spacing=10,
        )

        # 技能列表区域
        self._skill_list = ft.Column(
            [],
            spacing=6,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

        list_container = ft.Container(
            content=ft.Column(
                [
                    ft.Text("Skill列表", size=12, weight=ft.FontWeight.BOLD, color=colors.text),
                    ft.Container(height=8),
                    self._skill_list,
                ],
                spacing=0,
                expand=True,
            ),
            bgcolor=colors.surface,
            padding=16,
            border_radius=8,
            border=ft.Border(
                left=ft.BorderSide(1, colors.border),
                top=ft.BorderSide(1, colors.border),
                right=ft.BorderSide(1, colors.border),
                bottom=ft.BorderSide(1, colors.border),
            ),
            expand=True,
        )

        # 状态栏
        self._status_text = ft.Text(
            "",
            size=11,
            color=colors.text_muted,
        )

        # 主容器
        self._container = ft.Container(
            content=ft.Column(
                [
                    title,
                    ft.Container(height=6),
                    info,
                    ft.Container(height=16),
                    buttons_row,
                    ft.Container(height=10),
                    filter_row,
                    ft.Container(height=10),
                    list_container,
                    ft.Container(height=10),
                    self._status_text,
                ],
                spacing=0,
                expand=True,
            ),
            padding=20,
            expand=True,
        )

        # 延迟加载技能列表（在页面更新后）
        self._page.on_view_pop = self._on_page_ready

        self._logger.info("SkillManagementPage: 页面构建完成")
        return self._container

    def _on_page_ready(self, e) -> None:
        """页面准备就绪时加载技能"""
        self._load_skills()

    def _load_skills(self) -> None:
        """加载技能列表"""
        if not self._skill_list:
            return

        # 清空列表
        self._skill_list.controls.clear()

        # 获取技能管理器
        manager = self._get_skill_manager()
        skills = manager.list_skills()

        # 应用筛选
        filter_type = self._filter_dropdown.value if self._filter_dropdown else "all"
        search_text = self._search_input.value.strip().lower() if self._search_input else ""

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

        # 填充列表
        colors = self._theme_manager.get_color_scheme()
        self._skill_data = []

        for skill in filtered_skills:
            # 创建技能项
            skill_item = self._create_skill_item(skill)
            self._skill_list.controls.append(skill_item)
            self._skill_data.append({
                "id": skill.id,
                "name": skill.name,
                "description": skill.description,
                "tags": skill.tags,
                "created_at": skill.created_at,
            })

        # 更新状态
        if self._status_text:
            self._status_text.value = f"共 {len(skills)} 个Skill，显示 {len(filtered_skills)} 个"

        # 更新页面
        try:
            if self._page:
                self._page.update()
        except Exception:
            pass  # 忽略更新错误

    def _create_skill_item(self, skill: "SkillMetadata") -> ft.Container:
        """
        创建单个技能项

        Args:
            skill: 技能元数据

        Returns:
            技能项容器
        """
        colors = self._theme_manager.get_color_scheme()

        # 名称
        name_text = ft.Text(
            skill.name,
            size=11,
            weight=ft.FontWeight.BOLD,
            color=colors.text,
        )

        # 描述
        desc_text = ft.Text(
            skill.description or "无描述",
            size=11,
            color=colors.text_muted,
        )

        # 标签
        tags_str = ", ".join(skill.tags[:3]) if skill.tags else "无标签"
        tags_text = ft.Text(
            f"标签: {tags_str}",
            size=10,
            color=colors.text_muted,
        )

        # 创建时间
        if skill.created_at:
            if isinstance(skill.created_at, datetime):
                time_str = skill.created_at.strftime("%Y-%m-%d")
            else:
                time_str = str(skill.created_at)[:10]
        else:
            time_str = "未知"
        time_text = ft.Text(
            f"创建时间: {time_str}",
            size=10,
            color=colors.text_muted,
        )

        # 操作按钮
        edit_btn = ft.IconButton(
            icon=ft.Icons.EDIT,
            icon_color=colors.primary,
            icon_size=16,
            tooltip="编辑",
            on_click=lambda e, sid=skill.id: self._on_edit_click(sid),
        )

        export_btn = ft.IconButton(
            icon=ft.Icons.FILE_DOWNLOAD,
            icon_color=colors.text_muted,
            icon_size=16,
            tooltip="导出",
            on_click=lambda e, sid=skill.id: self._on_export_click(sid),
        )

        publish_btn = ft.IconButton(
            icon=ft.Icons.PUBLISH,
            icon_color=colors.success,
            icon_size=16,
            tooltip="发布",
            on_click=lambda e, sid=skill.id: self._on_publish_click(sid),
        )

        delete_btn = ft.IconButton(
            icon=ft.Icons.DELETE,
            icon_color=colors.error,
            icon_size=16,
            tooltip="删除",
            on_click=lambda e, sid=skill.id: self._on_delete_click(sid),
        )

        buttons_row = ft.Row(
            [edit_btn, export_btn, publish_btn, delete_btn],
            spacing=6,
        )

        # 左侧信息
        left_info = ft.Column(
            [
                name_text,
                desc_text,
                ft.Row([tags_text, time_text], spacing=24),
            ],
            spacing=6,
            expand=True,
        )

        # 整行布局
        row = ft.Row(
            [
                left_info,
                buttons_row,
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        # 容器
        container = ft.Container(
            content=row,
            bgcolor=colors.bg_page,
            padding=10,
            border_radius=8,
            border=ft.Border(
                left=ft.BorderSide(1, colors.border),
                top=ft.BorderSide(1, colors.border),
                right=ft.BorderSide(1, colors.border),
                bottom=ft.BorderSide(1, colors.border),
            ),
            on_hover=lambda e, sid=skill.id: self._on_item_hover(e, sid),
            on_click=lambda e, sid=skill.id: self._on_item_click(sid),
        )

        return container

    def _on_filter_change(self, e) -> None:
        """筛选变化事件"""
        self._load_skills()

    def _on_search_change(self, e) -> None:
        """搜索变化事件"""
        self._load_skills()

    def _on_item_hover(self, e, skill_id: str) -> None:
        """技能项悬停事件"""
        pass

    def _on_item_click(self, skill_id: str) -> None:
        """技能项点击事件"""
        self._selected_skill_id = skill_id

    def _on_create_click(self, e) -> None:
        """创建按钮点击事件"""
        self._show_create_dialog()

    def _on_edit_click(self, skill_id: str) -> None:
        """编辑按钮点击事件"""
        self._show_edit_dialog(skill_id)

    def _on_delete_click(self, skill_id: str) -> None:
        """删除按钮点击事件"""
        self._confirm_delete(skill_id)

    def _on_import_click(self, e) -> None:
        """导入按钮点击事件"""
        if self._file_picker:
            self._file_picker.on_result = self._on_import_result
            self._file_picker.pick_files(
                allowed_extensions=["md"],
                allow_multiple=False,
            )

    def _on_import_result(self, e: ft.ControlEvent) -> None:
        """导入文件选择结果"""
        if e.files and len(e.files) > 0:
            file_path = e.files[0].path
            try:
                manager = self._get_skill_manager()
                skill_id = manager.import_skill(file_path)
                self._load_skills()
                self._show_snackbar("Skill已导入", success=True)
            except Exception as ex:
                self._logger.exception("导入Skill失败")
                self._show_snackbar(f"导入失败: {ex}", success=False)

    def _on_export_click(self, skill_id: str) -> None:
        """导出按钮点击事件"""
        manager = self._get_skill_manager()
        skill = manager.get_skill_metadata(skill_id)
        if skill is None:
            return

        if self._file_picker:
            self._file_picker.on_result = lambda e: self._on_export_result(e, skill_id)
            self._file_picker.save_file(
                file_name=f"{skill.name}.md",
                allowed_extensions=["md"],
            )

    def _on_export_result(self, e: ft.ControlEvent, skill_id: str) -> None:
        """导出文件选择结果"""
        if e.path:
            try:
                manager = self._get_skill_manager()
                manager.export_skill(skill_id, e.path)
                self._show_snackbar(f"Skill已导出到 {e.path}", success=True)
            except Exception as ex:
                self._logger.exception("导出Skill失败")
                self._show_snackbar(f"导出失败: {ex}", success=False)

    def _on_publish_click(self, skill_id: str) -> None:
        """发布按钮点击事件"""
        manager = self._get_skill_manager()
        skill = manager.get_skill_metadata(skill_id)
        if skill is None:
            return

        # 检查是否已发布
        if manager.is_skill_published(skill_id):
            # 已发布，询问是否取消发布
            self._show_confirm_dialog(
                "取消发布",
                f"Skill '{skill.name}' 已发布。\n是否要取消发布？\n\n取消发布后，Skill将不再被SkillAgent加载。",
                lambda: self._unpublish_skill(skill_id),
            )
        else:
            # 未发布，询问是否发布
            self._show_confirm_dialog(
                "发布Skill",
                f"是否要发布Skill '{skill.name}'？\n\n发布后，Skill将被复制到Skills根目录，可以被SkillAgent正常加载。",
                lambda: self._publish_skill(skill_id),
            )

    def _publish_skill(self, skill_id: str) -> None:
        """发布技能"""
        try:
            manager = self._get_skill_manager()
            if manager.publish_skill(skill_id):
                self._show_snackbar("Skill已发布，现在可以在聊天中使用", success=True)
            else:
                self._show_snackbar("发布失败", success=False)
        except Exception as ex:
            self._logger.exception("发布Skill失败")
            self._show_snackbar(f"发布失败: {ex}", success=False)

    def _unpublish_skill(self, skill_id: str) -> None:
        """取消发布技能"""
        try:
            manager = self._get_skill_manager()
            if manager.unpublish_skill(skill_id):
                self._show_snackbar("Skill已取消发布", success=True)
            else:
                self._show_snackbar("取消发布失败", success=False)
        except Exception as ex:
            self._logger.exception("取消发布Skill失败")
            self._show_snackbar(f"取消发布失败: {ex}", success=False)

    def _show_create_dialog(self) -> None:
        """显示创建对话框"""
        colors = self._theme_manager.get_color_scheme()

        # 名称输入
        name_input = ft.TextField(
            label="Skill名称",
            hint_text="输入Skill名称",
            autofocus=True,
        )

        # 描述输入
        desc_input = ft.TextField(
            label="Skill描述",
            hint_text="描述Skill的功能和用途",
        )

        # 标签输入
        tags_input = ft.TextField(
            label="Skill标签",
            hint_text="例如: automation, browser, search",
        )

        # 对话框内容
        content = ft.Column(
            [
                ft.Text("创建新Skill", size=14, weight=ft.FontWeight.BOLD, color=colors.text),
                ft.Container(height=16),
                name_input,
                desc_input,
                tags_input,
            ],
            spacing=10,
            tight=True,
        )

        def on_create(e):
            name = name_input.value.strip()
            description = desc_input.value.strip()
            tags_str = tags_input.value.strip()

            if not name:
                self._show_snackbar("请输入Skill名称", success=False)
                return

            tags = [t.strip() for t in tags_str.split(",") if t.strip()]

            try:
                manager = self._get_skill_manager()
                skill_id = manager.create_skill(
                    name=name,
                    description=description,
                    tags=tags,
                )
                self._load_skills()
                self._show_snackbar(f"Skill '{name}' 已创建", success=True)
                # 关闭对话框
                dialog.open = False
                self._page.update()
                # 打开编辑器
                self._show_edit_dialog(skill_id)
            except Exception as ex:
                self._logger.exception("创建Skill失败")
                self._show_snackbar(f"创建失败: {ex}", success=False)

        # 按钮
        cancel_btn = ft.TextButton("取消", on_click=lambda e: self._close_dialog(dialog))
        create_btn = ft.ElevatedButton(
            "创建",
            on_click=on_create,
            bgcolor=colors.primary,
            color=colors.text_on_primary,
        )

        # 创建对话框
        dialog = ft.AlertDialog(
            modal=True,
            title=None,
            content=content,
            actions=[cancel_btn, create_btn],
            actions_alignment=ft.MainAxisAlignment.END,
            on_dismiss=lambda e: None,
        )

        # 显示对话框
        self._page.overlay.append(dialog)
        dialog.open = True
        self._page.update()

    def _show_edit_dialog(self, skill_id: str) -> None:
        """显示 Skill 编辑器对话框"""
        # 获取技能数据
        manager = self._get_skill_manager()
        skill = manager.get_skill(skill_id)
        if skill is None:
            self._show_snackbar(f"Skill '{skill_id}' 不存在", success=False)
            return

        def on_save(content: str) -> None:
            """编辑器保存回调"""
            try:
                manager.edit_skill(skill_id, content)
                self._load_skills()
                self._show_snackbar("Skill已更新", success=True)
            except Exception as ex:
                self._logger.exception("更新Skill失败")
                self._show_snackbar(f"更新失败: {ex}", success=False)

        # 打开 Markdown 编辑器
        editor = SkillEditorPage(self._page, skill, on_save=on_save)
        editor.open()

    def _confirm_delete(self, skill_id: str) -> None:
        """确认删除对话框"""
        manager = self._get_skill_manager()
        skill = manager.get_skill_metadata(skill_id)
        if skill is None:
            return

        self._show_confirm_dialog(
            "确认删除",
            f"确定要删除Skill '{skill.name}' 吗？\n此操作不可撤销。",
            lambda: self._delete_skill(skill_id),
        )

    def _delete_skill(self, skill_id: str) -> None:
        """删除技能"""
        try:
            manager = self._get_skill_manager()
            manager.delete_skill(skill_id)
            self._load_skills()
            self._show_snackbar("Skill已删除", success=True)
        except Exception as ex:
            self._logger.exception("删除Skill失败")
            self._show_snackbar(f"删除失败: {ex}", success=False)

    def _show_confirm_dialog(
        self,
        title: str,
        message: str,
        on_confirm: callable,
    ) -> None:
        """显示确认对话框"""
        colors = self._theme_manager.get_color_scheme()

        content = ft.Column(
            [
                ft.Text(title, size=14, weight=ft.FontWeight.BOLD, color=colors.text),
                ft.Container(height=10),
                ft.Text(message, size=11, weight=ft.FontWeight.BOLD, color=colors.text_muted),
            ],
            spacing=0,
            tight=True,
        )

        def on_confirm_click(e):
            dialog.open = False
            self._page.update()
            on_confirm()

        cancel_btn = ft.TextButton("取消", on_click=lambda e: self._close_dialog(dialog))
        confirm_btn = ft.ElevatedButton(
            "确定",
            on_click=on_confirm_click,
            bgcolor=colors.primary,
            color=colors.text_on_primary,
        )

        dialog = ft.AlertDialog(
            modal=True,
            title=None,
            content=content,
            actions=[cancel_btn, confirm_btn],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        self._page.overlay.append(dialog)
        dialog.open = True
        self._page.update()

    def _show_snackbar(self, message: str, success: bool = True) -> None:
        """显示提示消息"""
        colors = self._theme_manager.get_color_scheme()
        self._page.snack_bar = ft.SnackBar(
            content=ft.Text(message, color=colors.text_on_primary),
            bgcolor=colors.success if success else colors.error,
        )
        self._page.snack_bar.open = True
        self._page.update()

    def _show_help(self) -> None:
        """显示帮助信息"""
        help_text = """Skill Markdown 编辑帮助

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
   使用工具{tool_name}格式引用工具
   参数：param1="value1", param2="value2"

4. 参数引用
   使用 {{user_input.xxx}} 引用用户输入参数
   使用 {{step_n_result}} 引用前一步骤的结果

5. 执行流程
   在"执行流程"部分按顺序描述操作步骤，
   大模型将理解并执行这些操作。"""

        self._show_message_dialog("编辑帮助", help_text)

    def _show_message_dialog(self, title: str, message: str) -> None:
        """显示消息对话框"""
        colors = self._theme_manager.get_color_scheme()

        content = ft.Column(
            [
                ft.Text(title, size=11, weight=ft.FontWeight.BOLD, color=colors.text),
                ft.Container(height=10),
                ft.Text(message, size=11, color=colors.text_muted, selectable=True),
            ],
            spacing=0,
            tight=True,
            scroll=ft.ScrollMode.AUTO,
        )

        close_btn = ft.TextButton("关闭", on_click=lambda e: self._close_dialog(dialog))

        dialog = ft.AlertDialog(
            modal=True,
            title=None,
            content=content,
            actions=[close_btn],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        self._page.overlay.append(dialog)
        dialog.open = True
        self._page.update()

    def _close_dialog(self, dialog: ft.AlertDialog) -> None:
        """关闭对话框"""
        dialog.open = False
        self._page.update()

    def refresh(self) -> None:
        """刷新页面"""
        self._load_skills()