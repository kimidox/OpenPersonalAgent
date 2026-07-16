"""
Flet 设置模块

提供设置相关的界面组件。
"""
from ui_flet.settings.model_config_page import ModelConfigPage
from ui_flet.settings.skill_management_page import SkillManagementPage
from ui_flet.settings.skill_toggle_page import SkillTogglePage
from ui_flet.settings.voice_settings_page import VoiceSettingsPage
from ui_flet.settings.hotkey_settings_page import HotkeySettingsPage
from ui_flet.settings.scheduled_tasks_page import ScheduledTasksPage
from ui_flet.settings.prompt_template_page import PromptTemplatePage
from ui_flet.settings.live2d_settings_page import Live2DSettingsPage

__all__ = [
    "ModelConfigPage",
    "SkillManagementPage",
    "SkillTogglePage",
    "VoiceSettingsPage",
    "HotkeySettingsPage",
    "ScheduledTasksPage",
    "PromptTemplatePage",
    "Live2DSettingsPage",
]
