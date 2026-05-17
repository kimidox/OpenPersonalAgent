from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QStyleFactory

from ui.styles import initialize_styles
from ui.views.main_window import SkillAgentMainWindow


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
