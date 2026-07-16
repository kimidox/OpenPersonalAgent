"""
通知模块 - 使用系统原生通知

使用 plyer 库实现跨平台系统通知。
如果 plyer 未安装，则优雅降级为日志输出。
"""
from __future__ import annotations

try:
    from plyer import notification as plyer_notification
    HAS_PLYER = True
except ImportError:
    HAS_PLYER = False

from logger import get_module_logger

logger = get_module_logger("notification")


def show_system_notification(tray_icon, title: str, message: str, duration_ms: int = 5000) -> None:
    """
    显示系统通知
    
    Args:
        tray_icon: 托盘图标（保留参数，用于向后兼容）
        title: 通知标题
        message: 通知内容
        duration_ms: 通知显示时长（毫秒）
    """
    if HAS_PLYER:
        try:
            plyer_notification.notify(
                title=title,
                message=message,
                app_name="PersonalWindowGLM",
                timeout=duration_ms // 1000  # plyer 使用秒为单位
            )
            logger.debug(f"系统通知已发送: {title}")
        except Exception as e:
            logger.error(f"发送系统通知失败: {e}")
            # 降级：打印日志
            logger.info(f"通知: {title} - {message}")
    else:
        # 降级：打印日志
        logger.info(f"通知: {title} - {message}")


def send_notification(notification_type: str, title: str, message: str, tray_icon=None) -> None:
    """
    发送通知
    
    Args:
        notification_type: 通知类型（保留参数，用于向后兼容，但不再区分 'system' 和 'toast'）
        title: 通知标题
        message: 通知内容
        tray_icon: 托盘图标（保留参数，用于向后兼容）
    
    Note:
        重构后只支持系统通知，不再支持 Qt Toast 窗口。
        notification_type 参数保留用于向后兼容，但不再区分类型。
    """
    show_system_notification(tray_icon, title, message)
    logger.debug(f"已发送通知: {title}")