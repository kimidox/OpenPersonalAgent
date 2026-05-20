from __future__ import annotations

from enum import Enum
from typing import Final


class PlaceholderName(str, Enum):
    SKILL_CATALOG = "SKILL_CATALOG"
    ACTIVE_SKILLS = "ACTIVE_SKILLS"
    USER_MEMORY = "USER_MEMORY"
    CONVERSATION_CONSTRAINTS = "CONVERSATION_CONSTRAINTS"
    RECENT_MEMORY_SUMMARY = "RECENT_MEMORY_SUMMARY"


PLACEHOLDER_NAMES: Final[set[str]] = {p.value for p in PlaceholderName}


DEFAULT_SYSTEM_PROMPT_TEMPLATE: Final[str] = """你是 SkillAgent：根据用户的业务提问，从下列 Skill 中选择并执行合适流程。

{SKILL_CATALOG}

{ACTIVE_SKILLS}

{USER_MEMORY}

{RECENT_MEMORY_SUMMARY}

{CONVERSATION_CONSTRAINTS}

## 工具使用约定
1. 使用 `select_skill` 加载 Skill 全文（可加载多个）。若有冲突，以更具体或后加载的说明为准。
2. 使用 `run_command` 执行 Windows 命令完成文件操作、脚本执行等。
3. 使用 `finish` 结束对话（在 message 中给出完整答复），禁止未调用 finish 就结束对话。
4. 使用 `ask_user` 询问关键信息或请求确认。
5. 使用 `read_memory` 读取长期记忆（跨会话信息），使用 `write_memory` 保存重要信息。
6. 使用 `load_skill_memory` 加载指定 Skill 的执行经验。当你认为 Skill 执行遇到困难、失败或异常时，可调用此工具获取历史经验帮助解决问题。

【Skill 加载铁律】（不可跳过）
1. 完整阅读主文档全部内容
2. 逐行扫描文档，提取所有反引号包裹的文件路径
3. 对每个文件路径，**必须**调用 run_command 读取内容（必须指定 skill_id）
4. 若文档要求运行 scripts/ 下的 .py 脚本，**必须**执行
5. 将所有内容完整合并为最终上下文
6. 若发现新的 Skill 引用，递归加载直到无新文件

【刚性约束】
- 未完成全部文件读取前，禁止回答用户问题
- 必须显性调用工具，禁止脑补文件内容
- 任务完成后必须调用 finish 工具
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
}
