from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QStyleFactory
from PySide6.QtGui import QIcon

from ui.styles import initialize_styles
from ui.views.main_window import SkillAgentMainWindow
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
    
    if not background:
        window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()