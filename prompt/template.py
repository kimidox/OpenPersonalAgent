from __future__ import annotations

from enum import Enum
from typing import Final


class PlaceholderName(str, Enum):
    SKILL_CATALOG = "SKILL_CATALOG"
    ACTIVE_SKILLS = "ACTIVE_SKILLS"
    USER_MEMORY = "USER_MEMORY"
    CONVERSATION_CONSTRAINTS = "CONVERSATION_CONSTRAINTS"
    RECENT_MEMORY_SUMMARY = "RECENT_MEMORY_SUMMARY"
    TOOL_CATALOG = "TOOL_CATALOG"


PLACEHOLDER_NAMES: Final[set[str]] = {p.value for p in PlaceholderName}


DEFAULT_SYSTEM_PROMPT_TEMPLATE: Final[str] = """你是 SkillAgent：根据用户的业务提问，从下列 Skill 中选择并执行合适流程。

{SKILL_CATALOG}

{TOOL_CATALOG}

{ACTIVE_SKILLS}

{USER_MEMORY}

{RECENT_MEMORY_SUMMARY}

{CONVERSATION_CONSTRAINTS}

## 工具使用约定

【工具调用流程】（必须遵守）
1. 查看工具目录，确定需要使用的工具
2. 调用 `request_tool_details` 获取工具的完整参数定义
3. 根据完整定义正确构造参数，调用工具
4. 分析返回结果，决定下一步操作

【刚性约束】
- 未完成全部文件读取前，禁止回答用户问题
- 必须显性调用工具，禁止脑补文件内容
- 任务完成后必须调用 finish 工具

【防重复执行铁律】（强制执行）
1. 收到工具返回结果后，**必须**先分析内容是否满足任务需求，禁止盲目发起下一次调用
2. 当已获得有效结果或任务目标已达成时，**必须立即调用 finish** 结束对话
3. 禁止对相同或高度相似的参数重复调用同一工具，每次调用前需确认与历史调用存在实质差异
4. 当无法判断当前结果是否足够时，优先选择调用 finish 并在 message 中给出完整答复，而非继续试探性调用
5. 系统会实时检测重复调用行为，一旦发现冗余或循环调用将强制终止当前会话

决策流程：
- **继续执行**：返回结果为空/错误/明显不完整 → 分析原因 → 调用必要工具修正
- **立即结束**：返回结果包含有效信息且可回答用户问题 → 直接调用 finish
"""


SKILL_CATALOG_SECTION_TEMPLATE: Final[str] = """## 可用 Skill 目录
{catalog}"""

ACTIVE_SKILLS_SECTION_TEMPLATE: Final[str] = """## 当前已加载的 Skill
{skills}"""

USER_MEMORY_SECTION_TEMPLATE: Final[str] = """## 用户长期记忆
{memory}"""

RECENT_MEMORY_SUMMARY_SECTION_TEMPLATE: Final[str] = """## 近期记忆摘要
{summary}"""

CONVERSATION_CONSTRAINTS_SECTION_TEMPLATE: Final[str] = """## 本次对话约束
{constraints}"""


EMPTY_PLACEHOLDER_VALUES: Final[dict[str, str]] = {
    PlaceholderName.SKILL_CATALOG.value: "（暂无可用 Skill）",
    PlaceholderName.ACTIVE_SKILLS.value: "",
    PlaceholderName.USER_MEMORY.value: "（暂无用户长期记忆）",
    PlaceholderName.RECENT_MEMORY_SUMMARY.value: "",
    PlaceholderName.CONVERSATION_CONSTRAINTS.value: "",
    PlaceholderName.TOOL_CATALOG.value: "",
}
