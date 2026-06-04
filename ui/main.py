from __future__ import annotations

import sys
import threading

from PySide6.QtWidgets import QApplication, QStyleFactory
from PySide6.QtGui import QIcon

from ui.styles import initialize_styles
from ui.views.main_window import SkillAgentMainWindow
from ui.views.floating_ball import FloatingBall
from resource_path import paths
from logger import get_logger


def _preload_asr_check():
    """后台检查 ASR 模型配置并自动加载"""
    try:
        import config
        from recorder import is_onnx_model_loaded, load_onnx_model
        
        logger = get_logger()
        
        # 检查是否配置了自动加载
        if getattr(config, 'ASR_AUTO_LOAD', False):
            logger.info("配置了自动加载 ASR 模型，正在加载...")
            if not is_onnx_model_loaded():
                success = load_onnx_model()
                if success:
                    logger.info("ASR 模型自动加载成功")
                else:
                    logger.warning("ASR 模型自动加载失败")
            else:
                logger.info("ASR 模型已加载")
        else:
            if not is_onnx_model_loaded():
                logger.info("ASR 模型未加载，录音功能需要先在设置中加载模型")
    except Exception as e:
        logger = get_logger()
        logger.exception(f"ASR 模型自动加载检查异常: {e}")


def _preload_tts_check():
    """后台检查 TTS 模型配置并自动加载"""
    try:
        import config
        from tts import is_tts_model_loaded, load_tts_model
        
        logger = get_logger()
        
        # 检查是否配置了自动加载
        if getattr(config, 'TTS_AUTO_LOAD', False):
            logger.info("配置了自动加载 TTS 模型，正在加载...")
            if not is_tts_model_loaded():
                # 使用配置的模型类型
                model_type = getattr(config, 'TTS_MODEL_TYPE', 'zh')
                model_path = getattr(config, 'TTS_MODEL_PATH', '')
                
                if model_path:
                    success = load_tts_model(model_path, auto_download=False)
                else:
                    success = load_tts_model(model_type=model_type, auto_download=True)
                
                if success:
                    logger.info("TTS 模型自动加载成功")
                else:
                    logger.warning("TTS 模型自动加载失败")
            else:
                logger.info("TTS 模型已加载")
    except Exception as e:
        logger = get_logger()
        logger.exception(f"TTS 模型自动加载检查异常: {e}")


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
    
    logger.info("ui.main: 创建悬浮球")
    floating_ball = FloatingBall()
    floating_ball.show_main_window.connect(window._show_window)
    floating_ball.quit_application.connect(window._quit_application)
    floating_ball.create_recording_conversation.connect(window._process_recording_for_conversation)
    logger.info("ui.main: 设置悬浮球引用")
    window.set_floating_ball(floating_ball)
    
    preload_thread = threading.Thread(
        target=_preload_asr_check,
        name="asr-preload",
        daemon=True
    )
    preload_thread.start()
    
    # TTS 自动加载线程
    tts_preload_thread = threading.Thread(
        target=_preload_tts_check,
        name="tts-preload",
        daemon=True
    )
    tts_preload_thread.start()
    
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