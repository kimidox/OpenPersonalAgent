"""
命令执行参数完整性检查模块

用于在执行命令前检查参数的完整性，避免因参数截断导致的执行失败。
"""

import re
import sys
from typing import List, Tuple


def validate_command_params(command: str) -> Tuple[bool, List[str]]:
    """
    验证命令参数的完整性。

    Args:
        command: 要执行的命令字符串

    Returns:
        (is_valid, warnings): 元组，包含检查是否通过和警告信息列表
        - is_valid: True 表示检查通过，False 表示存在问题
        - warnings: 警告信息列表（即使检查通过也可能有警告）
    """
    if not command:
        return True, []

    warnings = []

    # 1. 检查 PowerShell 环境变量格式
    env_var_warnings = _check_powershell_env_vars(command)
    warnings.extend(env_var_warnings)

    # 2. 检查引号成对匹配
    quote_warnings = _check_quote_matching(command)
    warnings.extend(quote_warnings)

    # 3. 检查参数长度
    length_warnings = _check_command_length(command)
    warnings.extend(length_warnings)

    # 如果有任何警告，返回 False
    is_valid = len(warnings) == 0

    return is_valid, warnings


def _check_powershell_env_vars(command: str) -> List[str]:
    """
    检查 PowerShell 环境变量格式是否完整。

    检测以下问题模式：
    - $env 后面没有冒号（截断的环境变量引用）
    - $env: 后面没有变量名
    - $env" 或 $env'（环境变量名被引号截断）

    Args:
        command: 命令字符串

    Returns:
        警告信息列表
    """
    warnings = []

    # 模式1: 检测 $env 后面没有冒号的情况（截断的环境变量）
    # 例如: $env (后面没有冒号)
    pattern1 = r'\$env(?![a-zA-Z_:])'
    matches1 = re.finditer(pattern1, command)
    for match in matches1:
        # 获取上下文（前后各20个字符）
        start = max(0, match.start() - 20)
        end = min(len(command), match.end() + 20)
        context = command[start:end]
        warnings.append(
            f"PowerShell 环境变量引用不完整: 发现 '$env' 但后面缺少冒号或变量名。"
            f"上下文: '...{context}...'"
        )

    # 模式2: 检测 $env: 后面没有变量名的情况
    # 例如: $env: (后面没有变量名)
    pattern2 = r'\$env:\s*(?=[^\w]|$)'
    matches2 = re.finditer(pattern2, command)
    for match in matches2:
        start = max(0, match.start() - 20)
        end = min(len(command), match.end() + 20)
        context = command[start:end]
        warnings.append(
            f"PowerShell 环境变量引用不完整: '$env:' 后缺少变量名。"
            f"上下文: '...{context}...'"
        )

    # 模式3: 检测 $env 后面直接跟引号的情况（截断）
    # 例如: $env" 或 $env'
    pattern3 = r'\$env(["\'])'
    matches3 = re.finditer(pattern3, command)
    for match in matches3:
        start = max(0, match.start() - 20)
        end = min(len(command), match.end() + 20)
        context = command[start:end]
        warnings.append(
            f"PowerShell 环境变量引用可能被截断: 发现 '$env{match.group(1)}'。"
            f"上下文: '...{context}...'"
        )

    return warnings


def _check_quote_matching(command: str) -> List[str]:
    """
    检查引号是否成对匹配。

    检查单引号 ' 和双引号 " 是否成对。

    Args:
        command: 命令字符串

    Returns:
        警告信息列表
    """
    warnings = []

    # 检查双引号
    double_quote_count = command.count('"')
    if double_quote_count % 2 != 0:
        warnings.append(
            f"引号不匹配: 双引号 (\") 数量为 {double_quote_count}，应为偶数。"
            f"这可能表示引号被截断或未正确配对。"
        )

    # 检查单引号（排除转义的单引号）
    # 在 PowerShell 中，单引号内的单引号需要用 '' 来转义
    # 这里简单计算，不考虑转义情况
    single_quote_count = command.count("'")
    if single_quote_count % 2 != 0:
        warnings.append(
            f"引号不匹配: 单引号 (') 数量为 {single_quote_count}，应为偶数。"
            f"这可能表示引号被截断或未正确配对。"
        )

    return warnings


def _check_command_length(command: str) -> List[str]:
    """
    检查命令长度是否超过系统限制。

    Windows CMD: 8191 字符
    Linux/Unix: 通常更长（例如 131072 或更多）

    Args:
        command: 命令字符串

    Returns:
        警告信息列表
    """
    warnings = []

    command_length = len(command)

    # Windows 系统限制
    if sys.platform == "win32":
        WINDOWS_CMD_LIMIT = 8191
        if command_length > WINDOWS_CMD_LIMIT:
            warnings.append(
                f"命令长度超过 Windows CMD 限制: 当前长度 {command_length} 字符，"
                f"限制为 {WINDOWS_CMD_LIMIT} 字符。命令可能被截断。"
            )
        elif command_length > WINDOWS_CMD_LIMIT * 0.9:
            # 接近限制时也给出警告
            warnings.append(
                f"命令长度接近 Windows CMD 限制: 当前长度 {command_length} 字符，"
                f"限制为 {WINDOWS_CMD_LIMIT} 字符（使用率 {command_length/WINDOWS_CMD_LIMIT*100:.1f}%）。"
            )
    else:
        # Linux/Unix 系统（限制通常更长，但仍需提醒）
        UNIX_LIMIT = 131072  # 常见限制
        if command_length > UNIX_LIMIT:
            warnings.append(
                f"命令长度超过 Unix 系统常见限制: 当前长度 {command_length} 字符，"
                f"限制为 {UNIX_LIMIT} 字符。命令可能被截断。"
            )

    return warnings


def validate_and_log_warnings(command: str, logger=None) -> Tuple[bool, List[str]]:
    """
    验证命令参数并记录警告日志。

    Args:
        command: 要验证的命令字符串
        logger: 可选的日志记录器实例

    Returns:
        (is_valid, warnings): 验证结果和警告信息列表
    """
    is_valid, warnings = validate_command_params(command)

    if warnings and logger:
        for warning in warnings:
            logger.warning(f"[参数完整性检查] {warning}")

    return is_valid, warnings


# 用于测试的示例代码
if __name__ == "__main__":
    # 测试用例
    test_cases = [
        # 正常命令
        ("powershell Get-Process", True),
        # 截断的环境变量（错误示例）
        ("powershell -Command \"Invoke-WebRequest -Uri 'https://skillhub.cn/install' -OutFile '$env\"", False),
        # 正常的环境变量
        ("powershell Write-Host $env:TEMP", True),
        # 引号不匹配
        ("echo \"test", False),
        # 命令过长（模拟）
        ("python " + "a" * 8200, False),
    ]

    print("=" * 60)
    print("参数完整性检查测试")
    print("=" * 60)

    for cmd, expected_valid in test_cases:
        print(f"\n命令: {cmd[:80]}...")
        is_valid, warnings = validate_command_params(cmd)
        print(f"检查结果: {'通过' if is_valid else '失败'}")
        if warnings:
            print("警告信息:")
            for warning in warnings:
                print(f"  - {warning}")
        print(f"预期结果: {'通过' if expected_valid else '失败'}")
        print(f"测试结果: {'正确' if is_valid == expected_valid else '错误'}")