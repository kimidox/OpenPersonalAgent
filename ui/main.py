from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QStyleFactory
from PySide6.QtGui import QIcon

from ui.styles import initialize_styles
from ui.views.main_window import SkillAgentMainWindow
from ui.views.floating_ball import FloatingBall
from resource_path import paths
from logger import get_logger


def main(background: bool = False) -> None:
    logger = get_logger()
    app = QApplication(sys.argv)
    fusion = QStyleFactory.create("Fusion")
    if fusion is not None:
        app.setStyle(fusion)
    
    icon_path = paths.get_bundled_resource("application.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    
    initialize_styles()
    logger.info("ui.main: 创建主窗口")
    window = SkillAgentMainWindow(background=background)
    
    # 创建悬浮球（默认隐藏）
    logger.info("ui.main: 创建悬浮球")
    floating_ball = FloatingBall()
    floating_ball.show_main_window.connect(window._show_window)
    floating_ball.quit_application.connect(window._quit_application)
    # 浮动聊天窗口现在独立处理消息
    logger.info("ui.main: 设置悬浮球引用")
    window.set_floating_ball(floating_ball)
    
    logger.info(f"ui.main: background = {background}")
    if not background:
        logger.info("ui.main: 非后台模式，显示主窗口")
        window.show()
    else:
        logger.info("ui.main: 后台模式，显示悬浮球")
        floating_ball.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()