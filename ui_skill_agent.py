from __future__ import annotations

import warnings

import sys

from PySide6.QtWidgets import QApplication, QStyleFactory
from PySide6.QtGui import QIcon

from ui.views.main_window import SkillAgentMainWindow
from ui.views.floating_ball import FloatingBall
from ui.views.worker_thread import SkillAgentWorkerThread
from ui.styles import initialize_styles
from resource_path import paths


def main(background: bool = False) -> None:
    app = QApplication(sys.argv)
    fusion = QStyleFactory.create("Fusion")
    if fusion is not None:
        app.setStyle(fusion)
    
    icon_path = paths.get_bundled_resource("application.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    
    initialize_styles()
    window = SkillAgentMainWindow(background=background)
    
    floating_ball = FloatingBall()
    floating_ball.show_main_window.connect(window._show_window)
    floating_ball.quit_application.connect(window._quit_application)
    floating_ball.create_recording_conversation.connect(window._process_recording_for_conversation)
    window.set_floating_ball(floating_ball)
    
    if not background:
        window.show()
    else:
        floating_ball.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()