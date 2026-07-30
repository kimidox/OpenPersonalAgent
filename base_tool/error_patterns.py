"""
基础错误模式库模块

提供统一的错误模式定义、匹配和检索功能。
用于检测和诊断命令执行中的常见错误模式，支持自动修复策略判断。
"""

import re
from typing import Dict, Optional, TypedDict


class ErrorPatternDict(TypedDict):
    """
    错误模式数据结构定义
    
    Attributes:
        detection: 正则表达式模式用于检测错误
        auto_fix: 是否可以自动修复
        fix_strategy: 修复策略名称
        template: 错误描述模板
    """
    detection: str
    auto_fix: bool
    fix_strategy: str
    template: str


# =============================================================================
# 错误模式定义
# =============================================================================

ERROR_PATTERNS: Dict[str, ErrorPatternDict] = {
    # -------------------------------------------------------------------------
    # 引号匹配错误模式
    # -------------------------------------------------------------------------
    "QUOTE_MISMATCH": {
        "detection": r'(["\'])((?!\1).)*?\1(?!\1)|(["\'])(?=(?:(?!\3).)*$)',
        "auto_fix": True,
        "fix_strategy": "pair_quotes",
        "template": (
            "引号不匹配: 在位置 {position} 检测到 {quote_type} 引号未正确配对。"
            "请确保每个开引号都有对应的闭引号。"
        )
    },
    
    # -------------------------------------------------------------------------
    # 未闭合引号模式
    # -------------------------------------------------------------------------
    "UNCLOSED_QUOTE": {
        "detection": r'(["\'])(?=(?:(?!\1).)*$)',
        "auto_fix": True,
        "fix_strategy": "pair_quotes",
        "template": (
            "未闭合引号: 检测到 {quote_type} 引号在命令末尾未闭合。"
            "请检查命令参数是否完整,确保引号成对出现。"
        )
    },
    
    # -------------------------------------------------------------------------
    # 参数截断模式
    # -------------------------------------------------------------------------
    "PARAMETER_TRUNCATION": {
        "detection": r'--\w+$|--\w+(?=\s*$)|--\w+\s*(?=[|>&]|$)',
        "auto_fix": True,
        "fix_strategy": "complete_parameter",
        "template": (
            "参数截断: 参数标志 '{param_flag}' 后缺少值。"
            "请检查命令参数是否完整,确保所有参数都有正确的值。"
        )
    },
    
    # -------------------------------------------------------------------------
    # 参数不完整模式
    # -------------------------------------------------------------------------
    "INCOMPLETE_ARGUMENT": {
        "detection": r'(["\']).*?(?=\s+--|\s*$)|\b\w+\s+(?=\s+--|\s*$)',
        "auto_fix": False,
        "fix_strategy": "suggest_alternative",
        "template": (
            "参数不完整: 命令参数 '{argument}' 可能被截断或缺少必要值。"
            "请检查命令的完整性。"
        )
    },
    
    # -------------------------------------------------------------------------
    # 禁止语法模式
    # -------------------------------------------------------------------------
    "FORBIDDEN_SYNTAX": {
        "detection": (
            r'%%[a-zA-Z]|'  # 批处理变量语法 %%a
            r'findstr\s+/C:|'  # findstr /C: 语法
            r'\bwmic\b|'  # WMIC 命令
            r'\bfor\s+%\w+\s+in\s*\(|'  # 批处理 FOR 循环
            r'\bif\s+%|'  # 批处理 IF 语句
            r'\bset\s+%\w+%'  # 批处理 SET 命令
        ),
        "auto_fix": False,
        "fix_strategy": "suggest_alternative",
        "template": (
            "禁止语法: 检测到 {syntax_type} 语法模式。"
            "在当前环境中不应使用此语法。替代方案: {alternative}"
        )
    },
    
    # -------------------------------------------------------------------------
    # CMD批处理语法模式
    # -------------------------------------------------------------------------
    "CMD_BATCH_SYNTAX": {
        "detection": (
            r'\bfor\s+/[FLR]|'  # CMD FOR 命令
            r'\bif\s+(not\s+)?(exist|defined)|'  # CMD IF 命令
            r'\bcall\s*:|'  # CMD CALL 标签调用
            r'\bgoto\s+:|'  # CMD GOTO 标签跳转
            r'\bsetlocal|\bendlocal|'  # CMD 环境作用域
            r'%[a-zA-Z0-9]+%|'  # CMD 环境变量引用
            r'%~[fdpnxsatz]*\d'  # CMD 参数修饰符
        ),
        "auto_fix": False,
        "fix_strategy": "suggest_alternative",
        "template": (
            "CMD批处理语法: 检测到 CMD 批处理语法 '{matched_syntax}'。"
            "建议使用 PowerShell 或 Python 替代。"
        )
    },
    
    # -------------------------------------------------------------------------
    # 环境变量截断模式
    # -------------------------------------------------------------------------
    "ENV_VAR_TRUNCATION": {
        "detection": (
            r'\$env(?![a-zA-Z_:])|'  # $env 后面没有冒号或变量名
            r'\$env:\s*(?=[^\w]|$)|'  # $env: 后面没有变量名
            r'\$env(["\'])'  # $env 后面直接跟引号
        ),
        "auto_fix": False,
        "fix_strategy": "suggest_alternative",
        "template": (
            "环境变量截断: PowerShell 环境变量引用不完整。"
            "正确格式应为 $env:VARIABLE_NAME (如 $env:TEMP, $env:PATH)。"
        )
    }
}


# =============================================================================
# 模式匹配和检索功能
# =============================================================================

def match_error_pattern(error_message: str) -> Optional[str]:
    """
    根据错误消息匹配错误模式
    
    遍历所有错误模式,尝试匹配错误消息,返回第一个匹配的模式名称。
    
    Args:
        error_message: 错误消息字符串
        
    Returns:
        Optional[str]: 匹配的错误模式名称,如果没有匹配则返回 None
        
    Example:
        >>> pattern_name = match_error_pattern("引号不匹配: 在位置 10 检测到双引号未正确配对")
        >>> print(pattern_name)
        'QUOTE_MISMATCH'
    """
    if not error_message:
        return None
    
    # 按优先级遍历错误模式
    priority_order = [
        "QUOTE_MISMATCH",
        "UNCLOSED_QUOTE",
        "PARAMETER_TRUNCATION",
        "INCOMPLETE_ARGUMENT",
        "FORBIDDEN_SYNTAX",
        "CMD_BATCH_SYNTAX",
        "ENV_VAR_TRUNCATION"
    ]
    
    for pattern_name in priority_order:
        pattern_info = ERROR_PATTERNS.get(pattern_name)
        if not pattern_info:
            continue
        
        detection_pattern = pattern_info["detection"]
        
        try:
            # 尝试匹配错误消息
            if re.search(detection_pattern, error_message, re.IGNORECASE | re.MULTILINE):
                return pattern_name
        except re.error:
            # 如果正则表达式编译失败,跳过该模式
            continue
    
    return None


def get_error_pattern(pattern_name: str) -> Optional[Dict]:
    """
    获取指定错误模式的详情
    
    Args:
        pattern_name: 错误模式名称
        
    Returns:
        Optional[Dict]: 错误模式的详情字典,如果不存在则返回 None
        
    Example:
        >>> pattern_info = get_error_pattern("QUOTE_MISMATCH")
        >>> print(pattern_info)
        {
            'detection': r'(["\'])((?!\1).)*?\1(?!\1)|(["\'])(?=(?:(?!\3).)*$)',
            'auto_fix': True,
            'fix_strategy': 'pair_quotes',
            'template': '引号不匹配: 在位置 {position} 检测到 {quote_type} 引号未正确配对...'
        }
    """
    return ERROR_PATTERNS.get(pattern_name)


def can_auto_fix(pattern_name: str) -> bool:
    """
    判断指定错误模式是否可以自动修复
    
    Args:
        pattern_name: 错误模式名称
        
    Returns:
        bool: 如果可以自动修复返回 True,否则返回 False
        
    Example:
        >>> can_fix = can_auto_fix("QUOTE_MISMATCH")
        >>> print(can_fix)
        True
        >>> can_fix = can_auto_fix("FORBIDDEN_SYNTAX")
        >>> print(can_fix)
        False
    """
    pattern_info = ERROR_PATTERNS.get(pattern_name)
    
    if not pattern_info:
        return False
    
    return pattern_info.get("auto_fix", False)


def get_fix_strategy(pattern_name: str) -> str:
    """
    获取指定错误模式的修复策略名称
    
    Args:
        pattern_name: 错误模式名称
        
    Returns:
        str: 修复策略名称,如果模式不存在返回空字符串
        
    Example:
        >>> strategy = get_fix_strategy("QUOTE_MISMATCH")
        >>> print(strategy)
        'pair_quotes'
        >>> strategy = get_fix_strategy("FORBIDDEN_SYNTAX")
        >>> print(strategy)
        'suggest_alternative'
    """
    pattern_info = ERROR_PATTERNS.get(pattern_name)
    
    if not pattern_info:
        return ""
    
    return pattern_info.get("fix_strategy", "")


def get_error_template(pattern_name: str) -> str:
    """
    获取指定错误模式的错误描述模板
    
    Args:
        pattern_name: 错误模式名称
        
    Returns:
        str: 错误描述模板,如果模式不存在返回空字符串
        
    Example:
        >>> template = get_error_template("QUOTE_MISMATCH")
        >>> print(template)
        '引号不匹配: 在位置 {position} 检测到 {quote_type} 引号未正确配对...'
    """
    pattern_info = ERROR_PATTERNS.get(pattern_name)
    
    if not pattern_info:
        return ""
    
    return pattern_info.get("template", "")


def format_error_message(pattern_name: str, **kwargs) -> str:
    """
    使用错误模式模板格式化错误消息
    
    Args:
        pattern_name: 错误模式名称
        **kwargs: 模板变量
        
    Returns:
        str: 格式化后的错误消息
        
    Example:
        >>> msg = format_error_message("QUOTE_MISMATCH", position=10, quote_type="双引号")
        >>> print(msg)
        '引号不匹配: 在位置 10 检测到 双引号 引号未正确配对...'
    """
    template = get_error_template(pattern_name)
    
    if not template:
        return f"未知错误模式: {pattern_name}"
    
    try:
        return template.format(**kwargs)
    except KeyError as e:
        return f"模板格式化失败: 缺少参数 {e}"


def get_all_pattern_names() -> list:
    """
    获取所有错误模式名称列表
    
    Returns:
        list: 错误模式名称列表
        
    Example:
        >>> names = get_all_pattern_names()
        >>> print(names)
        ['QUOTE_MISMATCH', 'UNCLOSED_QUOTE', 'PARAMETER_TRUNCATION', ...]
    """
    return list(ERROR_PATTERNS.keys())


def get_patterns_by_fix_strategy(strategy: str) -> list:
    """
    根据修复策略获取所有匹配的错误模式名称
    
    Args:
        strategy: 修复策略名称
        
    Returns:
        list: 匹配的错误模式名称列表
        
    Example:
        >>> patterns = get_patterns_by_fix_strategy("pair_quotes")
        >>> print(patterns)
        ['QUOTE_MISMATCH', 'UNCLOSED_QUOTE']
    """
    return [
        name for name, info in ERROR_PATTERNS.items()
        if info.get("fix_strategy") == strategy
    ]


def get_auto_fixable_patterns() -> list:
    """
    获取所有可以自动修复的错误模式名称列表
    
    Returns:
        list: 可以自动修复的错误模式名称列表
        
    Example:
        >>> patterns = get_auto_fixable_patterns()
        >>> print(patterns)
        ['QUOTE_MISMATCH', 'UNCLOSED_QUOTE', 'PARAMETER_TRUNCATION']
    """
    return [
        name for name, info in ERROR_PATTERNS.items()
        if info.get("auto_fix", False)
    ]


# =============================================================================
# 测试和示例代码
# =============================================================================

if __name__ == "__main__":
    from logger import get_module_logger
    _logger = get_module_logger("error_patterns_test")

    _logger.info("=" * 80)
    _logger.info("基础错误模式库测试")
    _logger.info("=" * 80)
    
    # 测试 1: 获取所有模式名称
    _logger.info("所有错误模式名称:")
    for name in get_all_pattern_names():
        _logger.info("  - %s", name)
    
    # 测试 2: 获取自动可修复模式
    _logger.info("自动可修复的错误模式:")
    for name in get_auto_fixable_patterns():
        _logger.info("  - %s (策略: %s)", name, get_fix_strategy(name))
    
    # 测试 3: 按修复策略查询
    _logger.info("按修复策略查询:")
    for strategy in ["pair_quotes", "complete_parameter", "suggest_alternative"]:
        patterns = get_patterns_by_fix_strategy(strategy)
        _logger.info("  %s: %s", strategy, patterns)
    
    # 测试 4: 模式匹配
    _logger.info("模式匹配测试:")
    test_messages = [
        '引号不匹配: 在位置 10 检测到双引号未正确配对',
        '参数截断: 参数标志 "--input" 后缺少值',
        '禁止语法: 检测到批处理变量语法 %%a',
        '环境变量截断: PowerShell 环境变量引用不完整',
    ]
    
    for msg in test_messages:
        pattern_name = match_error_pattern(msg)
        if pattern_name:
            can_fix = can_auto_fix(pattern_name)
            strategy = get_fix_strategy(pattern_name)
            _logger.info("  消息: %s...", msg[:30])
            _logger.info("    -> 模式: %s, 可自动修复: %s, 策略: %s", pattern_name, can_fix, strategy)
        else:
            _logger.info("  消息: %s... -> 未匹配到模式", msg[:30])
    
    # 测试 5: 格式化错误消息
    _logger.info("格式化错误消息测试:")
    formatted_msg = format_error_message(
        "QUOTE_MISMATCH",
        position=15,
        quote_type="双引号"
    )
    _logger.info("  %s", formatted_msg)
    
    _logger.info("=" * 80)
    _logger.info("测试完成")
    _logger.info("=" * 80)