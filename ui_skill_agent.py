"""
DEPRECATED: 此模块已废弃，请迁移到新的模块化结构。

新入口文件: ui/main.py
主窗口类: ui.views.main_window.SkillAgentMainWindow
工作线程: ui.views.worker_thread.SkillAgentWorkerThread
组件: ui.components.*
样式: ui.styles.*

此文件仅作为兼容层保留，将在未来版本中移除。
"""

from __future__ import annotations

import warnings

import sys

from PySide6.QtWidgets import QApplication, QStyleFactory

from ui.views.main_window import SkillAgentMainWindow
from ui.views.worker_thread import SkillAgentWorkerThread
from ui.styles import initialize_styles

# warnings.warn(
#     "ui_skill_agent 模块已废弃，请使用 ui.main 模块。"
#     "新入口: from ui.main import main; main()",
#     DeprecationWarning,
#     stacklevel=2,
# )


def main() -> None:
    app = QApplication(sys.argv)
    fusion = QStyleFactory.create("Fusion")
    if fusion is not None:
        app.setStyle(fusion)
    initialize_styles()
    window = SkillAgentMainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
