"""
日志模块 - 统一管理日志输出

日志文件位置:
- 开发环境: PersonalData/logs/app.log
- 打包环境: %APPDATA%/OpenPersonalAgent/logs/app.log

性能优化：
- 生产环境默认使用INFO级别，降低I/O开销
- 支持DEBUG_MODE环境变量切换DEBUG级别
- 区分控制台和文件日志级别
- 使用延迟字符串格式化（%）避免无效字符串操作

结构化日志支持（阶段5新增）：
- trace_id：请求/任务唯一标识，用于关联一次完整操作的所有日志
- operation_type：操作类型（如：model_load、audio_transcribe）
- phase：操作阶段（如：init、download、load、complete、error）
- error_code：错误码（成功为空，失败时为具体错误码）
"""
import logging
import os
import random
import re
import string
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from resource_path import paths


class SensitiveDataFilter(logging.Filter):
    """敏感数据日志过滤器

    检测并脱敏日志消息中的敏感信息：
    - API key: sk-xxx... → sk-***
    - Bearer token: Bearer xxx... → Bearer ***
    - 密码字段: password=xxx → password=***
    - 长对话内容: 超过200字符的消息截断为前100字符+...[truncated]
    """

    # API key 模式：sk- 后跟任意非空白字符
    _API_KEY_PATTERN = re.compile(r'(sk-)\S+')
    # Bearer token 模式
    _BEARER_PATTERN = re.compile(r'(Bearer\s+)\S+', re.IGNORECASE)
    # 密码字段模式：password=xxx 或 password: xxx
    _PASSWORD_PATTERN = re.compile(r'(password\s*[=:]\s*)\S+', re.IGNORECASE)
    # 长消息截断阈值
    _MAX_MESSAGE_LENGTH = 200
    _TRUNCATE_PREFIX_LENGTH = 100

    def filter(self, record: logging.LogRecord) -> bool:
        """过滤日志记录，脱敏敏感数据"""
        msg = record.getMessage()
        sanitized = self._sanitize(msg)
        # 截断过长消息
        sanitized = self._truncate(sanitized)
        # 用脱敏后的消息替换原消息
        # 使用 args=() 防止后续格式化再次替换
        record.msg = sanitized
        record.args = ()
        return True

    def _sanitize(self, msg: str) -> str:
        """脱敏敏感数据"""
        msg = self._API_KEY_PATTERN.sub(r'\1***', msg)
        msg = self._BEARER_PATTERN.sub(r'\1***', msg)
        msg = self._PASSWORD_PATTERN.sub(r'\1***', msg)
        return msg

    def _truncate(self, msg: str) -> str:
        """截断过长消息"""
        if len(msg) > self._MAX_MESSAGE_LENGTH:
            return msg[:self._TRUNCATE_PREFIX_LENGTH] + '...[truncated]'
        return msg


_logger: Optional[logging.Logger] = None


def _get_log_levels() -> tuple[int, int]:
    """
    获取日志级别配置（生产环境优化）
    
    Returns:
        (console_level, file_level) 元组
        - 生产环境：控制台INFO，文件INFO
        - DEBUG模式：控制台DEBUG，文件DEBUG
    """
    # 检查环境变量或配置文件中的DEBUG_MODE
    debug_mode = os.getenv("DEBUG_MODE", "").lower() in ("true", "1", "yes", "on")
    
    if debug_mode:
        # 开发/调试模式：使用DEBUG级别
        return logging.DEBUG, logging.DEBUG
    else:
        # 生产环境：使用INFO级别，降低I/O开销
        return logging.INFO, logging.INFO


def setup_logger(name: str = "OpenPersonalAgent", level: int = None) -> logging.Logger:
    """
    配置并返回日志记录器
    
    Args:
        name: 日志记录器名称
        level: 日志级别（可选，未提供时自动检测DEBUG_MODE）
        
    Returns:
        配置好的日志记录器
    """
    global _logger
    
    if _logger is not None:
        return _logger
    
    # 自动获取日志级别配置
    if level is None:
        console_level, file_level = _get_log_levels()
    else:
        # 显式指定级别时，统一使用该级别
        console_level = level
        file_level = level
    
    logger = logging.getLogger(name)
    # Logger的级别设为最低，由各个Handler控制输出
    logger.setLevel(logging.DEBUG)
    
    # 避免重复添加 handler
    if logger.handlers:
        _logger = logger
        return logger
    
    # 日志格式
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # 控制台处理器 - 区分日志级别
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(console_level)  # 生产环境INFO，调试模式DEBUG
    console_handler.setFormatter(formatter)
    console_handler.addFilter(SensitiveDataFilter())
    logger.addHandler(console_handler)
    
    # 文件处理器（delay=True：首次写入才打开文件，避免启动时I/O）
    try:
        log_dir = paths.get_log_dir()
        log_file = log_dir / f"app_{datetime.now().strftime('%Y%m%d')}.log"

        file_handler = logging.FileHandler(
            log_file,
            encoding='utf-8',
            mode='a',
            delay=True  # 延迟打开文件，优化启动性能
        )
        file_handler.setLevel(file_level)  # 生产环境INFO，调试模式DEBUG
        file_handler.setFormatter(formatter)
        file_handler.addFilter(SensitiveDataFilter())
        logger.addHandler(file_handler)

        # 使用延迟格式化（%），避免无效字符串操作
        logger.info("日志文件: %s", log_file)
    except Exception as e:
        # 使用延迟格式化（%），避免无效字符串操作
        logger.warning("无法创建日志文件: %s", e)
    
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


def generate_trace_id(module_name: str = "") -> str:
    """
    生成trace_id用于关联一次完整操作的所有日志
    
    Args:
        module_name: 模块名称前缀（如：asr, llm）
        
    Returns:
        格式为 {module_name}_{timestamp}_{random_4hex} 的trace_id
        示例：asr_20260731_143025_a3f2
    """
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    random_hex = ''.join(random.choices(string.hexdigits[:16], k=4))
    
    if module_name:
        return f"{module_name}_{timestamp}_{random_hex}"
    else:
        return f"{timestamp}_{random_hex}"


class LoggerAdapter:
    """日志适配器，提供便捷的日志方法
    
    性能优化：
    - 使用延迟字符串格式化（%），避免无效字符串操作
    - 使用 isEnabledFor() 检查，避免无效格式化
    """
    
    def __init__(self, module_name: str = ""):
        self._module_name = module_name
        self._logger: Optional[logging.Logger] = None
    
    @property
    def logger(self) -> logging.Logger:
        if self._logger is None:
            self._logger = get_logger()
        return self._logger
    
    def debug(self, msg: str, *args, **kwargs):
        """使用延迟格式化的debug方法"""
        if self.logger.isEnabledFor(logging.DEBUG):
            if self._module_name:
                self.logger.debug("[%s] " + msg, self._module_name, *args, **kwargs)
            else:
                self.logger.debug(msg, *args, **kwargs)

    def info(self, msg: str, *args, **kwargs):
        """使用延迟格式化的info方法"""
        if self.logger.isEnabledFor(logging.INFO):
            if self._module_name:
                self.logger.info("[%s] " + msg, self._module_name, *args, **kwargs)
            else:
                self.logger.info(msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs):
        """使用延迟格式化的warning方法"""
        if self.logger.isEnabledFor(logging.WARNING):
            if self._module_name:
                self.logger.warning("[%s] " + msg, self._module_name, *args, **kwargs)
            else:
                self.logger.warning(msg, *args, **kwargs)

    def error(self, msg: str, *args, **kwargs):
        """使用延迟格式化的error方法"""
        if self.logger.isEnabledFor(logging.ERROR):
            if self._module_name:
                self.logger.error("[%s] " + msg, self._module_name, *args, **kwargs)
            else:
                self.logger.error(msg, *args, **kwargs)

    def exception(self, msg: str, *args, **kwargs):
        """使用延迟格式化的exception方法"""
        if self.logger.isEnabledFor(logging.ERROR):
            if self._module_name:
                self.logger.exception("[%s] " + msg, self._module_name, *args, **kwargs)
            else:
                self.logger.exception(msg, *args, **kwargs)

    def _format_structured_msg(
        self,
        msg: str,
        trace_id: str = None,
        operation_type: str = None,
        phase: str = None,
        error_code: str = None
    ) -> str:
        """
        格式化结构化日志消息
        
        Args:
            msg: 原始日志消息
            trace_id: 请求/任务唯一标识
            operation_type: 操作类型
            phase: 操作阶段
            error_code: 错误码
            
        Returns:
            格式化后的结构化日志消息
            示例：[trace_id=asr_20260731_143025_a3f2 | op=model_load | phase=init] 开始加载模型
        """
        context_parts = []
        
        if trace_id:
            context_parts.append(f"trace_id={trace_id}")
        if operation_type:
            context_parts.append(f"op={operation_type}")
        if phase:
            context_parts.append(f"phase={phase}")
        if error_code:
            context_parts.append(f"error_code={error_code}")
        
        if context_parts:
            structured_msg = "[" + " | ".join(context_parts) + "] " + msg
        else:
            structured_msg = msg
        
        return structured_msg

    def debug_with_context(
        self,
        msg: str,
        *args,
        trace_id: str = None,
        operation_type: str = None,
        phase: str = None,
        error_code: str = None,
        **kwargs
    ):
        """带上下文的结构化debug日志"""
        if self.logger.isEnabledFor(logging.DEBUG):
            structured_msg = self._format_structured_msg(
                msg, trace_id, operation_type, phase, error_code
            )
            if self._module_name:
                self.logger.debug("[%s] " + structured_msg, self._module_name, *args, **kwargs)
            else:
                self.logger.debug(structured_msg, *args, **kwargs)

    def info_with_context(
        self,
        msg: str,
        *args,
        trace_id: str = None,
        operation_type: str = None,
        phase: str = None,
        error_code: str = None,
        **kwargs
    ):
        """带上下文的结构化info日志"""
        if self.logger.isEnabledFor(logging.INFO):
            structured_msg = self._format_structured_msg(
                msg, trace_id, operation_type, phase, error_code
            )
            if self._module_name:
                self.logger.info("[%s] " + structured_msg, self._module_name, *args, **kwargs)
            else:
                self.logger.info(structured_msg, *args, **kwargs)

    def warning_with_context(
        self,
        msg: str,
        *args,
        trace_id: str = None,
        operation_type: str = None,
        phase: str = None,
        error_code: str = None,
        **kwargs
    ):
        """带上下文的结构化warning日志"""
        if self.logger.isEnabledFor(logging.WARNING):
            structured_msg = self._format_structured_msg(
                msg, trace_id, operation_type, phase, error_code
            )
            if self._module_name:
                self.logger.warning("[%s] " + structured_msg, self._module_name, *args, **kwargs)
            else:
                self.logger.warning(structured_msg, *args, **kwargs)

    def error_with_context(
        self,
        msg: str,
        *args,
        trace_id: str = None,
        operation_type: str = None,
        phase: str = None,
        error_code: str = None,
        **kwargs
    ):
        """带上下文的结构化error日志"""
        if self.logger.isEnabledFor(logging.ERROR):
            structured_msg = self._format_structured_msg(
                msg, trace_id, operation_type, phase, error_code
            )
            if self._module_name:
                self.logger.error("[%s] " + structured_msg, self._module_name, *args, **kwargs)
            else:
                self.logger.error(structured_msg, *args, **kwargs)

    def exception_with_context(
        self,
        msg: str,
        *args,
        trace_id: str = None,
        operation_type: str = None,
        phase: str = None,
        error_code: str = None,
        **kwargs
    ):
        """带上下文的结构化exception日志（自动包含异常堆栈）"""
        if self.logger.isEnabledFor(logging.ERROR):
            structured_msg = self._format_structured_msg(
                msg, trace_id, operation_type, phase, error_code
            )
            if self._module_name:
                self.logger.exception("[%s] " + structured_msg, self._module_name, *args, **kwargs)
            else:
                self.logger.exception(structured_msg, *args, **kwargs)


def get_module_logger(module_name: str) -> LoggerAdapter:
    """获取模块专用日志适配器"""
    return LoggerAdapter(module_name)
