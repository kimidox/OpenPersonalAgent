"""
日志模块 - 统一管理日志输出

日志文件位置:
- 开发环境: PersonalData/logs/app.log
- 打包环境: %APPDATA%/OpenPersonalAgent/logs/app.log
"""
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from resource_path import paths

_logger: Optional[logging.Logger] = None


def setup_logger(name: str = "OpenPersonalAgent", level: int = logging.DEBUG) -> logging.Logger:
    """
    配置并返回日志记录器
    
    Args:
        name: 日志记录器名称
        level: 日志级别
        
    Returns:
        配置好的日志记录器
    """
    global _logger
    
    if _logger is not None:
        return _logger
    
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # 避免重复添加 handler
    if logger.handlers:
        _logger = logger
        return logger
    
    # 日志格式
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # 控制台处理器 - 始终添加
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # 文件处理器
    try:
        log_dir = paths.get_log_dir()
        log_file = log_dir / f"app_{datetime.now().strftime('%Y%m%d')}.log"
        
        file_handler = logging.FileHandler(
            log_file,
            encoding='utf-8',
            mode='a'
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        
        logger.info(f"日志文件: {log_file}")
    except Exception as e:
        logger.warning(f"无法创建日志文件: {e}")
    
    _logger = logger
    return logger


def get_logger() -> logging.Logger:
    """获取已配置的日志记录器，如果未配置则自动配置"""
    global _logger
    
    if _logger is None:
        return setup_logger()
    return _logger


def log_exception(exc_type, exc_value, exc_tb):
    """全局异常处理器"""
    logger = get_logger()
    logger.error("未捕获的异常:", exc_info=(exc_type, exc_value, exc_tb))


def install_exception_hook():
    """安装全局异常钩子"""
    sys.excepthook = log_exception


class LoggerAdapter:
    """日志适配器，提供便捷的日志方法"""
    
    def __init__(self, module_name: str = ""):
        self._module_name = module_name
        self._logger: Optional[logging.Logger] = None
    
    @property
    def logger(self) -> logging.Logger:
        if self._logger is None:
            self._logger = get_logger()
        return self._logger
    
    def debug(self, msg: str, *args, **kwargs):
        if self._module_name:
            msg = f"[{self._module_name}] {msg}"
        self.logger.debug(msg, *args, **kwargs)
    
    def info(self, msg: str, *args, **kwargs):
        if self._module_name:
            msg = f"[{self._module_name}] {msg}"
        self.logger.info(msg, *args, **kwargs)
    
    def warning(self, msg: str, *args, **kwargs):
        if self._module_name:
            msg = f"[{self._module_name}] {msg}"
        self.logger.warning(msg, *args, **kwargs)
    
    def error(self, msg: str, *args, **kwargs):
        if self._module_name:
            msg = f"[{self._module_name}] {msg}"
        self.logger.error(msg, *args, **kwargs)
    
    def exception(self, msg: str, *args, **kwargs):
        if self._module_name:
            msg = f"[{self._module_name}] {msg}"
        self.logger.exception(msg, *args, **kwargs)


def get_module_logger(module_name: str) -> LoggerAdapter:
    """获取模块专用日志适配器"""
    return LoggerAdapter(module_name)
