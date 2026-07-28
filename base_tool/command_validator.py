"""
结构化参数校验器模块

提供结构化的命令参数验证,在工具执行前进行严格验证。
检测引号匹配、参数截断、禁止命令模式等问题,返回结构化错误信息。
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum


class ErrorType(Enum):
    """错误类型枚举"""
    QUOTE_MISMATCH = "QUOTE_MISMATCH"  # 引号不匹配
    PARAMETER_TRUNCATION = "PARAMETER_TRUNCATION"  # 参数截断
    FORBIDDEN_SYNTAX = "FORBIDDEN_SYNTAX"  # 禁止的语法模式
    ENV_VAR_TRUNCATION = "ENV_VAR_TRUNCATION"  # 环境变量截断
    COMMAND_TOO_LONG = "COMMAND_TOO_LONG"  # 命令过长
    VALID = "VALID"  # 验证通过


@dataclass
class ValidationResult:
    """
    验证结果数据结构

    Attributes:
        is_valid: 是否通过验证
        error_type: 错误类型代码(如 "QUOTE_MISMATCH")
        error_context: 错误上下文信息(位置、片段等)
        fix_suggestion: 修复建议
        retry_template: 重试模板
    """
    is_valid: bool
    error_type: str = "VALID"
    error_context: Dict = field(default_factory=dict)
    fix_suggestion: str = ""
    retry_template: str = ""

    def __post_init__(self):
        """初始化后处理"""
        if self.is_valid and self.error_type == "VALID":
            # 验证通过时清空其他字段
            self.error_context = {}
            self.fix_suggestion = ""
            self.retry_template = ""

    def to_dict(self) -> Dict:
        """转换为字典格式"""
        return {
            "is_valid": self.is_valid,
            "error_type": self.error_type,
            "error_context": self.error_context,
            "fix_suggestion": self.fix_suggestion,
            "retry_template": self.retry_template
        }

    @classmethod
    def valid_result(cls) -> 'ValidationResult':
        """创建验证通过的结果"""
        return cls(is_valid=True)

    @classmethod
    def error_result(cls, error_type: str, error_context: Dict,
                     fix_suggestion: str, retry_template: str) -> 'ValidationResult':
        """创建验证失败的结果"""
        return cls(
            is_valid=False,
            error_type=error_type,
            error_context=error_context,
            fix_suggestion=fix_suggestion,
            retry_template=retry_template
        )


@dataclass
class QuoteMatchResult:
    """引号匹配检测结果"""
    has_error: bool
    quote_type: str  # "single" 或 "double"
    unmatched_count: int
    positions: List[int]  # 未匹配引号的位置
    context: str  # 错误上下文


@dataclass
class ForbiddenPatternMatch:
    """禁止模式匹配结果"""
    pattern_name: str  # 模式名称
    matched_text: str  # 匹配的文本
    position: int  # 匹配位置
    context: str  # 错误上下文
    alternative: str  # 替代方案


class CommandValidator:
    """
    结构化参数校验器

    在工具执行前对命令参数进行严格验证,检测多种问题模式。
    """

    # 禁止的命令模式定义
    FORBIDDEN_PATTERNS = {
        "batch_variable": {
            "pattern": r"%%[a-zA-Z]",
            "description": "批处理变量语法 %%a",
            "alternative": "使用 PowerShell 变量 $var 或 Python 变量"
        },
        "findstr_c": {
            "pattern": r"findstr\s+/C:",
            "description": "findstr /C: 语法",
            "alternative": "使用 Select-String -Pattern 'pattern' (PowerShell)"
        },
        "wmic_command": {
            "pattern": r"\bwmic\b",
            "description": "WMIC 命令",
            "alternative": "使用 Get-WmiObject 或 Get-CimInstance (PowerShell)"
        },
        "batch_for_loop": {
            "pattern": r"\bfor\s+%\w+\s+in\s*\(",
            "description": "批处理 FOR 循环",
            "alternative": "使用 PowerShell For-Each 或 Python for 循环"
        },
        "batch_if": {
            "pattern": r"\bif\s+%",
            "description": "批处理 IF 语句",
            "alternative": "使用 PowerShell if 语句或 Python if 语句"
        },
        "batch_set": {
            "pattern": r"\bset\s+%\w+%",
            "description": "批处理 SET 命令",
            "alternative": "使用 PowerShell $var = 'value' 或 Python 变量赋值"
        }
    }

    def __init__(self):
        """初始化校验器"""
        self.command: str = ""
        self.args: Dict = {}

    def validate(self, command: str, args: Optional[Dict] = None) -> ValidationResult:
        """
        验证命令参数的完整性

        Args:
            command: 要验证的命令字符串
            args: 可选的参数字典

        Returns:
            ValidationResult: 结构化验证结果
        """
        if not command:
            return ValidationResult.valid_result()

        self.command = command
        self.args = args or {}

        # 1. 检测引号匹配
        quote_result = self._check_quote_matching()
        if not quote_result.is_valid:
            return quote_result

        # 2. 检测参数截断
        truncation_result = self._check_parameter_truncation()
        if not truncation_result.is_valid:
            return truncation_result

        # 3. 检测禁止命令模式
        forbidden_result = self._check_forbidden_patterns()
        if not forbidden_result.is_valid:
            return forbidden_result

        # 4. 检测环境变量截断
        env_var_result = self._check_environment_variables()
        if not env_var_result.is_valid:
            return env_var_result

        # 所有检查通过
        return ValidationResult.valid_result()

    def _check_quote_matching(self) -> ValidationResult:
        """
        检查引号是否成对匹配

        Returns:
            ValidationResult: 验证结果
        """
        if not self.command:
            return ValidationResult.valid_result()

        # 检测双引号
        double_quote_result = self._detect_unmatched_quotes('"')
        if double_quote_result.has_error:
            return self._create_quote_error_result(double_quote_result)

        # 检测单引号
        single_quote_result = self._detect_unmatched_quotes("'")
        if single_quote_result.has_error:
            return self._create_quote_error_result(single_quote_result)

        return ValidationResult.valid_result()

    def _detect_unmatched_quotes(self, quote_char: str) -> QuoteMatchResult:
        """
        检测未匹配的引号

        Args:
            quote_char: 引号字符 (' 或 ")

        Returns:
            QuoteMatchResult: 检测结果
        """
        count = self.command.count(quote_char)

        if count % 2 == 0:
            # 引号成对
            return QuoteMatchResult(
                has_error=False,
                quote_type="double" if quote_char == '"' else "single",
                unmatched_count=0,
                positions=[],
                context=""
            )

        # 找出所有引号的位置
        positions = []
        for i, char in enumerate(self.command):
            if char == quote_char:
                positions.append(i)

        # 获取上下文(第一个未匹配的引号附近)
        first_unmatched_pos = positions[-1]
        context_start = max(0, first_unmatched_pos - 30)
        context_end = min(len(self.command), first_unmatched_pos + 30)
        context = self.command[context_start:context_end]

        return QuoteMatchResult(
            has_error=True,
            quote_type="double" if quote_char == '"' else "single",
            unmatched_count=count % 2,
            positions=positions,
            context=f"...{context}..."
        )

    def _create_quote_error_result(self, quote_result: QuoteMatchResult) -> ValidationResult:
        """
        创建引号错误的验证结果

        Args:
            quote_result: 引号检测结果

        Returns:
            ValidationResult: 验证结果
        """
        quote_name = "双引号 (\")" if quote_result.quote_type == "double" else "单引号 (')"

        # 生成修复建议
        fix_suggestion = (
            f"{quote_name}不匹配,总共有 {len(quote_result.positions)} 个引号。"
            f"请检查引号是否成对出现,确保每个开引号都有对应的闭引号。"
        )

        # 生成重试模板
        if quote_result.quote_type == "double":
            retry_template = (
                "正确格式示例:\n"
                "  python script.py \"参数1 参数2\" --option \"值\"\n"
                "注意:每个双引号必须成对出现"
            )
        else:
            retry_template = (
                "正确格式示例:\n"
                "  powershell -Command 'Get-Process | Select-Object Name'\n"
                "注意:每个单引号必须成对出现"
            )

        return ValidationResult.error_result(
            error_type=ErrorType.QUOTE_MISMATCH.value,
            error_context={
                "quote_type": quote_result.quote_type,
                "unmatched_count": quote_result.unmatched_count,
                "positions": quote_result.positions,
                "context": quote_result.context,
                "total_quotes": len(quote_result.positions)
            },
            fix_suggestion=fix_suggestion,
            retry_template=retry_template
        )

    def _check_parameter_truncation(self) -> ValidationResult:
        """
        检查参数截断

        识别未闭合引号和参数边界问题

        Returns:
            ValidationResult: 验证结果
        """
        if not self.command:
            return ValidationResult.valid_result()

        # 1. 检测参数标志后缺少值(如: python script.py --param)
        # 匹配以 --param 结尾的命令,且前面没有等号
        if re.search(r'--\w+$', self.command) and not re.search(r'--\w+=', self.command):
            match = re.search(r'--\w+$', self.command)
            context_start = max(0, match.start() - 30)
            context_end = min(len(self.command), match.end() + 30)
            context = self.command[context_start:context_end]

            return ValidationResult.error_result(
                error_type=ErrorType.PARAMETER_TRUNCATION.value,
                error_context={
                    "matched_text": match.group(),
                    "position": match.start(),
                    "context": f"...{context}...",
                    "description": "参数标志后缺少值"
                },
                fix_suggestion=(
                    "检测到参数标志后缺少值。"
                    "请检查命令参数是否完整,确保所有参数都有正确的值。"
                ),
                retry_template=(
                    "正确格式示例:\n"
                    "  python script.py --option value\n"
                    "  python script.py --option=\"value with spaces\"\n"
                    "注意:确保每个参数标志后都有对应的值"
                )
            )

        # 2. 检测未闭合的字符串参数(更精确的检测)
        # 使用更智能的分割方法,考虑引号内的空格
        truncated_param = self._detect_truncated_parameter_smart()
        if truncated_param:
            return truncated_param

        return ValidationResult.valid_result()

    def _detect_truncated_parameter_smart(self) -> Optional[ValidationResult]:
        """
        使用智能方法检测截断的参数

        分析引号配对情况,检测真正截断的参数

        Returns:
            Optional[ValidationResult]: 如果检测到截断返回验证结果,否则返回 None
        """
        # 找出所有引号的位置
        quote_positions = []
        for i, char in enumerate(self.command):
            if char in ('"', "'"):
                quote_positions.append((i, char))

        # 如果没有引号,直接返回
        if not quote_positions:
            return None

        # 检查引号是否成对
        double_quotes = [(pos, char) for pos, char in quote_positions if char == '"']
        single_quotes = [(pos, char) for pos, char in quote_positions if char == "'"]

        # 检查双引号截断
        if double_quotes:
            result = self._check_quote_sequence_truncation(double_quotes, '"')
            if result:
                return result

        # 检查单引号截断
        if single_quotes:
            result = self._check_quote_sequence_truncation(single_quotes, "'")
            if result:
                return result

        return None

    def _check_quote_sequence_truncation(self, quote_positions: List[Tuple[int, str]],
                                         quote_char: str) -> Optional[ValidationResult]:
        """
        检查引号序列是否存在截断

        Args:
            quote_positions: 引号位置列表
            quote_char: 引号字符

        Returns:
            Optional[ValidationResult]: 如果检测到截断返回验证结果,否则返回 None
        """
        # 如果引号数量是奇数,说明有未匹配的引号
        if len(quote_positions) % 2 != 0:
            # 找到未匹配的引号位置
            last_quote_pos, _ = quote_positions[-1]

            # 获取上下文
            context_start = max(0, last_quote_pos - 30)
            context_end = min(len(self.command), last_quote_pos + 30)
            context = self.command[context_start:context_end]

            # 检查这个引号后面是否还有内容
            after_quote = self.command[last_quote_pos + 1:].strip()

            # 如果引号后面没有内容,或者后面的内容很短,可能是截断
            # 但如果引号已经通过成对检查,这里就不需要报错
            # 这个检查主要是为了检测参数值被截断的情况

        return None

    def _check_forbidden_patterns(self) -> ValidationResult:
        """
        检查禁止的命令模式

        检测批处理变量、findstr /C:、wmic 等禁止语法

        Returns:
            ValidationResult: 验证结果
        """
        if not self.command:
            return ValidationResult.valid_result()

        for pattern_name, pattern_info in self.FORBIDDEN_PATTERNS.items():
            pattern = pattern_info["pattern"]
            matches = list(re.finditer(pattern, self.command, re.IGNORECASE))

            if matches:
                match = matches[0]
                matched_text = match.group()

                # 获取上下文
                context_start = max(0, match.start() - 30)
                context_end = min(len(self.command), match.end() + 30)
                context = self.command[context_start:context_end]

                forbidden_match = ForbiddenPatternMatch(
                    pattern_name=pattern_name,
                    matched_text=matched_text,
                    position=match.start(),
                    context=f"...{context}...",
                    alternative=pattern_info["alternative"]
                )

                return self._create_forbidden_pattern_error(forbidden_match)

        return ValidationResult.valid_result()

    def _create_forbidden_pattern_error(self, forbidden_match: ForbiddenPatternMatch) -> ValidationResult:
        """
        创建禁止模式错误的验证结果

        Args:
            forbidden_match: 禁止模式匹配结果

        Returns:
            ValidationResult: 验证结果
        """
        pattern_descriptions = {
            "batch_variable": "批处理变量语法 %%a",
            "findstr_c": "findstr /C: 语法",
            "wmic_command": "WMIC 命令",
            "batch_for_loop": "批处理 FOR 循环",
            "batch_if": "批处理 IF 语句",
            "batch_set": "批处理 SET 命令"
        }

        description = pattern_descriptions.get(
            forbidden_match.pattern_name,
            forbidden_match.pattern_name
        )

        fix_suggestion = (
            f"检测到禁止的语法模式: {description}。"
            f"在当前环境中不应使用此语法。"
        )

        retry_template = (
            f"替代方案: {forbidden_match.alternative}\n\n"
            f"示例:\n"
            f"  ❌ 错误: {forbidden_match.matched_text}\n"
            f"  ✅ 正确: {forbidden_match.alternative}"
        )

        return ValidationResult.error_result(
            error_type=ErrorType.FORBIDDEN_SYNTAX.value,
            error_context={
                "pattern_name": forbidden_match.pattern_name,
                "matched_text": forbidden_match.matched_text,
                "position": forbidden_match.position,
                "context": forbidden_match.context,
                "description": description
            },
            fix_suggestion=fix_suggestion,
            retry_template=retry_template
        )

    def _check_environment_variables(self) -> ValidationResult:
        """
        检查环境变量引用是否截断

        检测 PowerShell 环境变量格式是否完整

        Returns:
            ValidationResult: 验证结果
        """
        if not self.command:
            return ValidationResult.valid_result()

        # 检测环境变量截断的模式
        env_var_patterns = [
            # $env 后面没有冒号(截断的环境变量)
            (r'\$env(?![a-zA-Z_:])', "环境变量引用不完整: 缺少冒号或变量名"),
            # $env: 后面没有变量名
            (r'\$env:\s*(?=[^\w]|$)', "环境变量引用不完整: 缺少变量名"),
            # $env 后面直接跟引号(截断)
            (r'\$env(["\'])', "环境变量引用可能被引号截断"),
        ]

        for pattern, description in env_var_patterns:
            matches = list(re.finditer(pattern, self.command))

            if matches:
                match = matches[0]
                matched_text = match.group()

                # 获取上下文
                context_start = max(0, match.start() - 30)
                context_end = min(len(self.command), match.end() + 30)
                context = self.command[context_start:context_end]

                return ValidationResult.error_result(
                    error_type=ErrorType.ENV_VAR_TRUNCATION.value,
                    error_context={
                        "pattern": pattern,
                        "matched_text": matched_text,
                        "position": match.start(),
                        "context": f"...{context}...",
                        "description": description
                    },
                    fix_suggestion=(
                        f"{description}。"
                        f"PowerShell 环境变量格式应为 $env:VARIABLE_NAME。"
                    ),
                    retry_template=(
                        "正确格式示例:\n"
                        "  $env:TEMP\n"
                        "  $env:PATH\n"
                        "  $env:USERPROFILE\n\n"
                        "注意:环境变量名必须紧跟在 $env: 后面,不能有空格"
                    )
                )

        return ValidationResult.valid_result()


def validate_command(command: str, args: Optional[Dict] = None) -> ValidationResult:
    """
    验证命令的便捷函数

    Args:
        command: 要验证的命令字符串
        args: 可选的参数字典

    Returns:
        ValidationResult: 结构化验证结果
    """
    validator = CommandValidator()
    return validator.validate(command, args)


def format_validation_error(result: ValidationResult) -> str:
    """
    格式化验证错误信息为可读字符串

    Args:
        result: 验证结果

    Returns:
        str: 格式化后的错误信息
    """
    if result.is_valid:
        return "验证通过"

    error_msg = f"❌ 参数验证失败\n\n"
    error_msg += f"错误类型: {result.error_type}\n\n"

    if result.error_context:
        error_msg += "错误详情:\n"
        for key, value in result.error_context.items():
            if key == "context":
                error_msg += f"  上下文: {value}\n"
            elif key == "description":
                error_msg += f"  描述: {value}\n"
            elif key not in ["positions", "pattern"]:
                error_msg += f"  {key}: {value}\n"

    if result.fix_suggestion:
        error_msg += f"\n💡 修复建议:\n  {result.fix_suggestion}\n"

    if result.retry_template:
        error_msg += f"\n📝 {result.retry_template}\n"

    return error_msg


# 测试和示例代码
if __name__ == "__main__":
    print("=" * 80)
    print("结构化参数校验器测试")
    print("=" * 80)

    validator = CommandValidator()

    # 测试用例
    test_cases = [
        ("python script.py \"参数1 参数2\"", True, "正常的双引号"),
        ("python script.py '参数1 参数2'", True, "正常的单引号"),
        ("python script.py \"参数1", False, "不匹配的双引号"),
        ("python script.py '参数1", False, "不匹配的单引号"),
        ("python script.py --param", False, "参数截断"),
        ("for %a in (*.txt) do echo %a", False, "批处理变量"),
        ("findstr /C:\"pattern\" file.txt", False, "findstr /C:"),
        ("wmic process get name", False, "WMIC 命令"),
        ("powershell Write-Host $env:TEMP", True, "正常的环境变量"),
        ("powershell Write-Host $env", False, "截断的环境变量"),
        ("powershell Write-Host $env: ", False, "环境变量缺少变量名"),
    ]

    for command, expected_valid, description in test_cases:
        print(f"\n{'-' * 80}")
        print(f"测试: {description}")
        print(f"命令: {command}")

        result = validator.validate(command)

        if result.is_valid:
            print("✅ 验证通过")
        else:
            print("❌ 验证失败")
            print(format_validation_error(result))

        # 验证预期结果
        if result.is_valid == expected_valid:
            print(f"✅ 测试结果正确")
        else:
            print(f"❌ 测试结果错误 (预期: {'通过' if expected_valid else '失败'})")

    print("\n" + "=" * 80)
    print("测试完成")
    print("=" * 80)