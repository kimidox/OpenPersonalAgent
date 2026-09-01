from __future__ import annotations

"""
【目录+补发 渐进披露机制 - 工具定义模块】

本模块定义了三类工具定义：

1. REQUEST_TOOL_DETAILS_DEFINITION（补发工具）
   - 用于 LLM 按需获取原子工具的完整定义
   - 是"目录+补发"机制的核心工具
   - 初始化时直接提供给 LLM

2. TOOL_CATALOG（工具目录）
   - 提供所有原子工具的简要描述
   - 用于系统提示词中，让 LLM 快速了解可用工具
   - 不包含完整参数定义，减少 token 消耗

3. ATOMIC_TOOL_DEFINITIONS（原子工具完整定义）
   - 包含所有原子工具的完整参数 schema
   - 通过 request_tool_details 按需获取
   - 不在初始化时直接提供

工作流程：
┌────────────────────────────────────────────────────────────────────┐
│  1. 初始化阶段                                                       │
│     ├─ 系统提示词包含 TOOL_CATALOG（简要描述）                         │
│     ├─ tools 列表包含 REQUEST_TOOL_DETAILS_DEFINITION               │
│     └─ tools 列表包含 CONTROL_TOOL_DEFINITIONS                      │
└────────────────────────────────────────────────────────────────────┘
                    ↓
┌────────────────────────────────────────────────────────────────────┐
│  2. 补发阶段（运行时）                                                │
│     ├─ LLM 调用 request_tool_details 获取需要的工具                  │
│     ├─ 从 ATOMIC_TOOL_DEFINITIONS 中查找完整定义                     │
│     └─ 完整定义动态添加到 tools 列表                                  │
└────────────────────────────────────────────────────────────────────┘
                    ↓
┌────────────────────────────────────────────────────────────────────┐
│  3. 执行阶段                                                         │
│     ├─ LLM 使用获取到的工具执行任务                                   │
│     └─ 工具调用结果返回给 LLM                                         │
└────────────────────────────────────────────────────────────────────┘
"""

REQUEST_TOOL_DETAILS_DEFINITION = {
    "name": "request_tool_details",
    "description": (
        "请求获取指定工具的完整定义（包括参数 schema）。\n"
        "使用场景：当你需要使用某个工具但不确定其参数要求时。\n"
        "参数：tool_names（必需），要请求的工具名称列表。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "tool_names": {
                "type": "array",
                "items": {"type": "string"},
                "description": "要请求完整定义的工具名称列表"
            }
        },
        "required": ["tool_names"]
    }
}

TOOL_CATALOG = {
    "run_command": "执行 Python 命令或 PowerShell 命令。",
    "file_operation": "文件操作工具。支持四种操作：",
    "edit": "精确编辑文件。搜索指定内容并替换，支持唯一性校验、行号定位和批量替换。",
    "create_scheduled_task": "创建定时任务提醒。",
    "list_scheduled_tasks": "列出定时任务。",
    "delete_scheduled_task": "删除定时任务。",
    "uploaded_files": "管理已上传文件。支持三种操作：list(列出文件)、get_content(获取内容)、get_metadata(获取元信息)。",
    "read_uploaded_file": "按 file_id 读取用户上传文件的解析文本（持久层，跨会话可用）。历史消息中的「用户曾上传文件」短标记需用此工具获取内容。",
    "install_skill_from_zip": "从 ZIP 压缩包安装 Skill 包。",
    "install_cli_package": "从含 cli.json 清单的 ZIP 压缩包安装 CLI 包。",
    "list_cli_packages": "列出所有已安装的 CLI 包及其用法。",
    "update_prompt": "读取或修改工具的描述提示词（自优化）。支持 list/read/write/reset/rollback 五种操作。",
}

CONTROL_TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "select_skill",
        "description": (
            "加载指定的 Skill 文档，获取完整的操作指南。\n"
            "参数：skill_id（必需），要加载的 Skill 的 ID。\n"
            "可多次调用加载多个 Skill，已加载的不会重复追加。\n"
            "【Skill 加载后处理原则】\n"
            "1. 完整阅读返回的 Skill 文档（含已自动内联的附属文件内容）\n"
            "2. 文档中出现的「读取附属文件」「加载示例」「参考 X.md」等指令，"
            "系统已自动把附属文件内容内联到返回结果里，**不要**再调用 run_command/file_operation 去读\n"
            "3. 文档中提到的 `scripts/xxx.py` 是**命令模板**（用于 run_command 执行），不是要读取的文件\n"
            "4. 文档中的反引号包裹内容（如 `session_id`、`title`、`href`）是**字段名**，不是文件路径\n"
            "5. 仅当文档明确写「执行脚本」「运行命令」时，才调用 run_command，并**必须**传 skill_id 参数\n"
            "6. 不要陷入循环：同一 skill_id 不要重复 select_skill；附属文件已内联无需额外读取"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "skill_id": {
                    "type": "string",
                    "description": "要加载的 Skill 的 ID"
                }
            },
            "required": ["skill_id"]
        },
    },
    {
        "name": "ask_user",
        "description": (
            "向用户询问关键信息或请求确认。\n"
            "用于：缺关键信息、多种策略需选择、敏感/不可逆操作需确认。\n"
            "用户回复后会从当前进度继续。\n"
            "参数：question(必需)、choices(可选)、context(可选)。\n\n"
            "【参数构造规范】\n"
            "- question: 必须是非空字符串，不能为 None 或空字符串\n"
            "- choices: 可选参数，如果提供必须是字符串数组，不能包含 None 值\n"
            "- context: 可选参数，如果提供必须是非空字符串，不能为 None\n\n"
            "✅ 正确示例：\n"
            "1. ask_user(question=\"是否继续执行？\", choices=[\"是\", \"否\"])\n"
            "2. ask_user(question=\"请选择处理方式\", choices=[\"自动处理\", \"手动处理\", \"取消\"])\n"
            "3. ask_user(question=\"缺少关键信息\", context=\"需要提供文件路径\")\n\n"
            "❌ 错误示例：\n"
            "错误1: ask_user(question=None) \n"
            "原因：question 不能为 None，必须是字符串\n"
            "修正：ask_user(question=\"请提供信息\")\n\n"
            "错误2: ask_user(question=\"选择\", choices=[\"选项1\", None, \"选项3\"])\n"
            "原因：choices 数组不能包含 None 值\n"
            "修正：ask_user(question=\"选择\", choices=[\"选项1\", \"选项2\", \"选项3\"])\n\n"
            "错误3: ask_user(question=\"测试\", context=None)\n"
            "原因：如果提供 context 参数，必须是字符串，不能为 None\n"
            "修正：ask_user(question=\"测试\") 或 ask_user(question=\"测试\", context=\"说明信息\")"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "要问用户的问题。必须是有效的字符串，不能为 None 或空字符串。"
                },
                "choices": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "可选的回答选项列表。如果提供，必须是字符串数组，不能包含 None 值。"
                },
                "context": {
                    "type": "string",
                    "description": "问题的上下文信息（可选）。如果提供，必须是有效的字符串，不能为 None。"
                }
            },
            "required": ["question"]
        },
    },
    {
        "name": "finish",
        "description": (
            "完成任务，向用户提供最终答复。\n"
            "这是任务完成的唯一结束方式，必须调用此工具。\n"
            "参数：message（必需），给用户的完整答复。\n"
            "注意：只有当所有前置工具调用都成功返回、没有以'错误:'开头的结果时，才允许调用此工具报告任务完成。若前置调用失败，应继续尝试修复或向用户说明失败原因，而不得直接调用 finish 声称成功。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "给用户的最终答复消息"
                }
            },
            "required": ["message"]
        },
    },
]

ATOMIC_TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "run_command",
        "description": (
            "执行 Python 命令或 PowerShell 命令。仅支持这两种命令类型。\n"
            "常用场景：\n"
            "- 运行 Python 脚本: python script.py\n"
            "- 运行模块: python -m pytest / python -m http.server\n"
            "- 安装依赖: pip install package\n"
            "- PowerShell 命令: powershell Get-CimInstance Win32_OperatingSystem\n"
            "参数：command(必需)、cwd(可选)、skill_id(可选)、timeout_sec(可选，默认60秒)。\n\n"
            "【文件操作编码规范】写入或修改文件时，优先使用 file_operation 或 edit 工具。\n"
            "若必须用 run_command 写文件，必须显式指定 UTF-8 编码：\n"
            "- PowerShell: Set-Content -Path file -Value \"内容\" -Encoding UTF8\n"
            "- 禁止使用裸重定向 > 或不带编码参数的 Set-Content、Out-File\n\n"
            "【错误处理规范】\n"
            "- 简单错误（拼写错误、路径笔误）：修正后重试\n"
            "- 复杂错误或连续失败：先分析错误原因，搜索相关文档或日志再修正\n"
            "- 同一命令重试超 2 次仍失败：放弃并重新规划任务\n"
            "- 超时命令会返回部分输出，可增加 timeout_sec 或检查是否需要交互输入\n"
            "- 失败时返回结果会包含【重试引导】，请参考其中建议修正命令\n\n"
            "【注意事项】\n"
            "- 避免使用需要交互输入的命令（如 ping 不带 -n、pause）\n"
            "- 输出超过配置的阈值时会被截断（默认 12000 字符，可通过 .env 文件中的 TOOL_OUTPUT_MAX_LENGTH 配置）\n"
            "- 截断时会显示详细信息：原始长度和截断后长度（可通过 .env 文件中的 TOOL_TRUNCATE_SHOW_DETAILS=false 关闭）\n"
            "- **读取 skill 包内文件请用 file_operation(action=\"read\", skill_id=...)**，不要用 run_command + type/Get-Content\n"
            "- 执行 skill 包内脚本时**必须**传 skill_id 参数，命令中的相对路径（如 scripts/xxx.py）会自动相对于 skill 包目录解析\n\n"
            "【参数预校验说明】\n"
            "系统在执行命令前会进行参数格式预校验，检测以下问题：\n"
            "- 引号匹配:检测单引号和双引号是否成对匹配\n"
            "- 参数截断:识别参数是否完整，检测未闭合的引号和参数边界\n"
            "- 禁止语法:检测批处理变量(%%a)、findstr /C:\"...\"、wmic 等禁止语法\n"
            "- 环境变量:检测 PowerShell 环境变量引用是否完整($env:VAR)\n\n"
            "如果预校验失败，系统将返回结构化错误报告，包含：\n"
            "- 错误类型:标准化的错误类型代码(如 QUOTE_MISMATCH)\n"
            "- 错误摘要:一句话描述错误本质\n"
            "- 错误详情:包含错误位置、上下文等详细信息\n"
            "- 修复建议:针对性的修复步骤\n"
            "- 重试模板:修正后的命令格式示例\n\n"
            "【常见错误类型代码】\n"
            "- QUOTE_MISMATCH: 引号不匹配\n"
            "- UNCLOSED_QUOTE: 未闭合引号\n"
            "- PARAMETER_TRUNCATION: 参数截断\n"
            "- INCOMPLETE_ARGUMENT: 参数不完整\n"
            "- FORBIDDEN_SYNTAX: 禁止语法\n"
            "- CMD_BATCH_SYNTAX: CMD批处理语法\n"
            "- ENV_VAR_TRUNCATION: 环境变量截断"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": (
                        "要执行的命令行指令字符串。仅支持 Python 命令和 PowerShell 命令。\n\n"
                        "【命令编写规范】\n"
                        "1. Python 命令：直接以 python 开头，如 python script.py、python -m pytest\n"
                        "   - pip 命令也可直接使用：pip install requests\n"
                        "   - 会自动使用虚拟环境的 Python，无需手动激活\n"
                        "2. PowerShell 命令：以 powershell 开头，如 powershell Get-CimInstance Win32_OperatingSystem\n"
                        "3. 禁止使用 CMD 批处理语法（如 %%a、findstr /C:\"...\"、wmic 等），改用 PowerShell 等效命令\n"
                        "4. 避免在单条命令中混合使用过多管道符、重定向符和逻辑运算符\n"
                        "5. 常用系统信息查询示例：\n"
                        "   - 操作系统: powershell Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version\n"
                        "   - CPU: powershell Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores\n"
                        "   - 进程列表: powershell Get-Process | Select-Object Name,Id,CPU\n\n"
                        "【引号和参数构造规范】★★★ 重要 ★★★\n"
                        "引号使用规则：\n"
                        "- Python 命令中，包含空格或特殊字符的参数必须用引号包裹\n"
                        "- PowerShell 命令中，使用单引号包裹包含空格的字符串（单引号内的单引号用 '' 转义）\n"
                        "- 外层引号和内层引号必须交替使用，避免混淆\n"
                        "- **JSON 数据或复杂字符串建议用三引号包裹**\n\n"
                        "✅ 正确示例：\n"
                        "1. 带空格参数的 Python 命令：\n"
                        "   python scripts/search.py \"长鑫上市 A股 半导体 影响\" --engines baidu,bing,sogou,sohu,eastmoney --limit 10 --timeout 30\n"
                        "   说明：参数含空格，用双引号包裹整个参数值\n\n"
                        "2. 多参数命令（参数列表）：\n"
                        "   python scripts/analyze.py --keywords \"人工智能 机器学习\" --sources \"百度,必应\" --max-results 20\n"
                        "   说明：多个参数值用逗号分隔，整个值用引号包裹\n\n"
                        "3. PowerShell 字符串参数：\n"
                        "   powershell Write-Host 'Hello World'\n"
                        "   powershell Write-Host \"Hello $env:USERNAME\"\n"
                        "   说明：单引号用于字面字符串，双引号支持变量展开\n\n"
                        "4. 复杂 JSON 或配置参数：\n"
                        "   python scripts/config.py --data '{\"name\":\"test\",\"value\":123}'\n"
                        "   说明：JSON 字符串用单引号包裹（避免与内部双引号冲突）\n\n"
                        "❌ 常见错误示例：\n"
                        "错误1 - 引号不匹配：\n"
                        "   错误: python scripts/search.py \"长鑫上市 A股 半导体 影响 --engines baidu\n"
                        "   原因：缺少闭合引号\n"
                        "   修正：确保每个引号成对出现\n\n"
                        "错误2 - 参数截断：\n"
                        "   错误: python scripts/search.py \"长鑫上市 A股 半导体 影响\" --engines baidu,bing,sogou,sohu,eastmoney --limit 10 --timeout 30\n"
                        "   现象：错误提示 \"unrecognized arguments: A股 半导体 影响\"\"\n"
                        "   原因：引号被截断或参数解析错误\n"
                        "   诊断：检查引号是否完整，检查参数顺序是否符合脚本要求\n\n"
                        "错误3 - 引号嵌套错误：\n"
                        "   错误: python scripts/config.py --data \"{\"name\":\"test\"}\" \n"
                        "   原因：双引号嵌套双引号导致解析错误\n"
                        "   修正：python scripts/config.py --data '{\"name\":\"test\"}'\n\n"
                        "【参数验证提示】\n"
                        "如果命令执行失败，系统会返回详细的诊断信息：\n"
                        "1. 引号匹配检查：检测引号是否成对\n"
                        "2. 环境变量检查：检测 $env: 格式是否完整\n"
                        "3. 命令长度检查：检测是否超过系统限制\n"
                        "请根据诊断信息修正命令参数"
                    ),
                },
                "cwd": {
                    "type": "string",
                    "description": "工作目录路径,默认为\".\"。若指定 skill_id，则为相对于该 skill 包目录的路径（如 \"scripts\"）；否则为相对于 work_dir 的路径",
                },
                "skill_id": {
                    "type": "string",
                    "description": "Skill 的 id。指定后，cwd 将相对于该 skill 包目录解析。示例：skill_id=\"8\" 时，cwd=\"scripts\" 表示 DuckDuckGoSearch/scripts 目录",
                },
                "timeout_sec": {
                    "type": "number",
                    "description": "超时秒数，默认 60，最大 180。对于长时间运行的命令请适当增加此值。",
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "file_operation",
        "description": (
            "文件操作工具。支持四种操作：\n"
            "- read: 读取文件内容，参数 path\n"
            "- write: 写入文件，参数 path、content\n"
            "- delete: 删除文件，参数 path\n"
            "- list: 列出目录内容，参数 path\n"
            "参数：action(必需，read/write/delete/list)、path(必需)、content(可选，仅write)、skill_id(可选，访问skill包内文件)。\n\n"
            "【参数构造规范】\n"
            "- action: 必需参数，必须是 ['read', 'write', 'delete', 'list'] 之一\n"
            "- path: 必需参数，必须是有效的文件或目录路径字符串\n"
            "- content: 仅当 action='write' 时需要，必须是字符串\n"
            "- skill_id: 可选参数，如果提供必须是有效的 Skill ID 字符串\n\n"
            "✅ 正确示例：\n"
            "1. file_operation(action='read', path='data/config.json')\n"
            "2. file_operation(action='write', path='output/result.txt', content='处理结果')\n"
            "3. file_operation(action='list', path='scripts/')\n"
            "4. file_operation(action='read', path='SKILL.md', skill_id='8')\n\n"
            "❌ 错误示例：\n"
            "错误1: file_operation(action=None, path='test.txt')\n"
            "原因：action 不能为 None\n"
            "修正：file_operation(action='read', path='test.txt')\n\n"
            "错误2: file_operation(action='write', path='test.txt', content=None)\n"
            "原因：write 操作的 content 不能为 None\n"
            "修正：file_operation(action='write', path='test.txt', content='内容')"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["read", "write", "delete", "list"],
                    "description": "操作类型：read读取、write写入、delete删除、list列出目录。必须是枚举值之一，不能为 None。"
                },
                "path": {
                    "type": "string",
                    "description": "文件或目录路径。必须是有效的路径字符串，不能为 None。"
                },
                "content": {
                    "type": "string",
                    "description": "写入内容（仅 action=write 时使用，注意write会全量覆盖）。如果提供，必须是字符串，不能为 None。"
                },
                "skill_id": {
                    "type": "string",
                    "description": "Skill ID，指定后 path 相对于 skill 包目录。如果提供，必须是有效的字符串。"
                }
            },
            "required": ["action", "path"]
        },
    },
    {
        "name": "edit",
        "description": (
            "精确编辑文件。搜索指定内容并替换，支持唯一性校验、行号定位和批量替换。\n\n"
            "【核心行为】\n"
            "- 默认只替换第一个匹配项，但要求匹配必须唯一（匹配多次时拒绝替换）\n"
            "- 匹配多次时可设置 replace_all=true 替换所有匹配\n"
            "- 可用 start_line 指定从哪一行开始搜索，实现精确定位\n"
            "- 未找到时返回包含文件行数的信息，匹配多次时返回所有匹配行号\n\n"
            "【参数】\n"
            "- path(必需): 文件路径\n"
            "- old_str(必需): 要搜索的内容（必须精确匹配，包括空格和换行）\n"
            "- new_str(必需): 替换后的内容\n"
            "- start_line(可选): 从指定行号开始搜索（1-based），用于重复代码消歧\n"
            "- replace_all(可选, 默认false): 是否替换所有匹配项\n"
            "- skill_id(可选): Skill ID\n\n"
            "【唯一性校验】\n"
            "当 old_str 在文件中匹配多次且 replace_all=false 时，工具会拒绝替换并返回：\n"
            "- 匹配总次数\n"
            "- 每个匹配的行号位置\n"
            "- 建议扩大 old_str 范围或使用 start_line 消歧\n\n"
            "✅ 正确示例：\n"
            "1. edit(path='config.py', old_str='DEBUG = False', new_str='DEBUG = True')\n"
            "2. edit(path='data.txt', old_str='old content', new_str='new content')\n"
            "3. edit(path='app.py', old_str='return True', new_str='return False', start_line=42)\n"
            "4. edit(path='utils.py', old_str='old_name', new_str='new_name', replace_all=true)\n\n"
            "❌ 错误示例：\n"
            "错误1: edit(path='test.txt', old_str='old', new_str=None)\n"
            "原因：new_str 不能为 None\n"
            "修正：edit(path='test.txt', old_str='old', new_str='new')\n\n"
            "错误2: edit(path='test.txt', old_str='', new_str='new')\n"
            "原因：old_str 不能为空字符串\n"
            "修正：edit(path='test.txt', old_str='要替换的内容', new_str='new')"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "要编辑的文件路径。必须是有效的路径字符串，不能为 None。"
                },
                "old_str": {
                    "type": "string",
                    "description": "要搜索的内容（必须精确匹配，包括空格和换行）。必须是非空字符串，不能为 None。"
                },
                "new_str": {
                    "type": "string",
                    "description": "替换后的内容。必须是有效的字符串，不能为 None。"
                },
                "start_line": {
                    "type": "integer",
                    "description": "从指定行号开始搜索（1-based）。用于在重复代码中精确定位。如果提供，必须是正整数。"
                },
                "replace_all": {
                    "type": "boolean",
                    "description": "是否替换所有匹配项。默认 false（仅替换第一个匹配，且要求匹配唯一）。设为 true 时替换所有匹配。"
                },
                "skill_id": {
                    "type": "string",
                    "description": "Skill ID，指定后 path 相对于 skill 包目录。如果提供，必须是有效的字符串。"
                }
            },
            "required": ["path", "old_str", "new_str"]
        },
    },
    {
        "name": "create_scheduled_task",
        "description": (
            "创建定时任务提醒。\n"
            "执行类型：\n"
            "- notification: 通知弹窗提醒，到时间弹出通知窗口\n"
            "- agent_conversation: 智能体会话触发，自动创建会话并执行任务链路\n"
            "使用场景：\n"
            "- 用户要求设置提醒（如'提醒我明天下午3点开会'）\n"
            "- 创建一次性或重复性定时任务\n"
            "- 设置每日、每周或每月的例行提醒\n"
            "- 定时触发智能体执行特定任务链路\n"
            "参数：title(必需)、trigger_time(必需，ISO格式)、content(可选)、repeat_type(可选)、execution_type(可选，默认notification)、execution_chain(可选，仅agent_conversation类型)、skill_ids(可选，仅agent_conversation类型)。\n"
            "时间需先解析为ISO格式（YYYY-MM-DDTHH:MM:SS）。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "任务标题，简短描述任务内容",
                },
                "trigger_time": {
                    "type": "string",
                    "description": "触发时间，ISO格式字符串（YYYY-MM-DDTHH:MM:SS）",
                },
                "content": {
                    "type": "string",
                    "description": "任务详细内容（可选）",
                },
                "repeat_type": {
                    "type": "string",
                    "enum": ["none", "daily", "weekly", "monthly"],
                    "description": "重复类型：none(不重复)、daily(每天)、weekly(每周)、monthly(每月)，默认none",
                },
                "execution_type": {
                    "type": "string",
                    "enum": ["notification", "agent_conversation"],
                    "description": "执行类型。notification为通知弹窗提醒，agent_conversation为智能体会话触发（自动创建会话并执行任务链路）。默认notification。",
                },
                "execution_chain": {
                    "type": "string",
                    "description": "执行链路JSON字符串（仅agent_conversation类型需要）。包含goal、skills、steps等字段。",
                },
                "skill_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "需要加载的Skill ID列表（仅agent_conversation类型需要）。",
                },
            },
            "required": ["title", "trigger_time"],
        },
    },
    {
        "name": "list_scheduled_tasks",
        "description": (
            "列出定时任务。\n"
            "使用场景：\n"
            "- 用户询问'我有哪些定时任务'或'查看我的提醒'\n"
            "- 查看所有任务或特定状态的任务\n"
            "- 确认任务是否已创建成功\n"
            "参数：status(可选，筛选状态)。不提供则返回所有任务。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["pending", "triggered", "cancelled", "deleted"],
                    "description": "筛选状态：pending(待触发)、triggered(已触发)、cancelled(已取消)、deleted(已删除)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "delete_scheduled_task",
        "description": (
            "删除定时任务。\n"
            "使用场景：\n"
            "- 用户要求取消某个提醒或任务\n"
            "- 删除不再需要的定时任务\n"
            "参数：task_id(必需，要删除的任务ID)。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "要删除的任务ID",
                },
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "uploaded_files",
        "description": (
            "管理当前会话中用户上传的文件。\n"
            "支持三种操作：\n"
            "- list: 列出所有已上传文件的概览信息\n"
            "- get_content: 获取指定文件的完整解析内容\n"
            "- get_metadata: 获取指定文件的元信息（大小、类型、上传时间等）\n"
            "使用场景：\n"
            "- 用户上传了文件并要求分析、处理或提取信息\n"
            "- 需要查看用户上传了哪些文件\n"
            "- 需要获取文件的具体内容进行操作\n"
            "参数：action(必需，list/get_content/get_metadata)、file_name(可选，仅get_content和get_metadata需要)。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "get_content", "get_metadata"],
                    "description": "操作类型：list列出所有文件、get_content获取文件内容、get_metadata获取文件元信息"
                },
                "file_name": {
                    "type": "string",
                    "description": "文件名称（仅 action=get_content 或 get_metadata 时需要）"
                }
            },
            "required": ["action"]
        },
    },
    {
        "name": "read_uploaded_file",
        "description": (
            "按 file_id 读取用户上传文件的解析文本（持久层，跨会话可用）。\n"
            "使用场景：\n"
            "- 历史消息中出现「用户曾上传文件「xxx」，需要内容时调用 read_uploaded_file 工具获取」提示\n"
            "- 用户追问先前上传文件的具体内容\n"
            "参数：file_id(必需)，上传文件 ID（用户消息短标记中括号内给出）。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "file_id": {
                    "type": "string",
                    "description": "上传文件 ID（用户消息短标记中括号内给出，形如 file_id: xxx）"
                }
            },
            "required": ["file_id"]
        },
    },
    {
        "name": "install_skill_from_zip",
        "description": (
            "从 ZIP 压缩包安装 Skill。\n"
            "支持两种 ZIP 结构：\n"
            "- 平铺模式：ZIP 根目录直接包含 SKILL.md 等文件\n"
            "- 包目录模式：ZIP 内含一级子目录，子目录中包含 SKILL.md\n"
            "安装后 Skill 可立即被 SkillAgent 使用。\n"
            "参数：zip_path(必需，ZIP文件路径)、overwrite(可选，是否覆盖已存在的Skill，默认false)。\n"
            "注意：调用后请仔细阅读返回结果。如果返回结果以'错误:'开头，说明安装失败，必须向用户说明失败原因，不得调用 finish 报告成功。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "zip_path": {
                    "type": "string",
                    "description": "ZIP 包文件的绝对路径或相对于工作目录的路径"
                },
                "overwrite": {
                    "type": "string",
                    "description": "是否覆盖已存在的同名 Skill。可选值：true、false（默认 false）"
                }
            },
            "required": ["zip_path"]
        },
    },
    {
        "name": "install_cli_package",
        "description": (
            "从 ZIP 压缩包安装 CLI 包（ZIP 中必须包含 cli.json 清单文件）。\n"
            "cli.json 规范：name(必填，包名)、entry(必填，入口文件相对路径)、"
            "version/description(可选)、commands(可选，命令用法列表)。\n"
            "安装到用户数据目录 CLI/ 下，安装后可通过 run_command 按入口文件调用。\n"
            "参数：zip_path(必需，ZIP文件路径)、overwrite(可选，是否覆盖已存在的同名包，默认false)。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "zip_path": {
                    "type": "string",
                    "description": "ZIP 包文件的绝对路径或相对于工作目录的路径"
                },
                "overwrite": {
                    "type": "string",
                    "description": "是否覆盖已存在的同名 CLI 包。可选值：true、false（默认 false）"
                }
            },
            "required": ["zip_path"]
        },
    },
    {
        "name": "list_cli_packages",
        "description": (
            "列出所有已安装的 CLI 包及其用法说明。\n"
            "返回包名、版本、描述、安装目录、入口文件和可用命令列表。\n"
            "无需参数。"
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        },
    },
    {
        "name": "update_prompt",
        "description": (
            "读取或修改工具的描述提示词，实现提示词自优化。\n"
            "每个工具的 description 保存在 PersonalData/prompts/tools/{tool_name}.md，"
            "修改立即生效并持久化，修改前的版本自动快照为 .bak。\n"
            "操作类型：\n"
            "- list: 列出所有可优化的工具及覆盖状态（无需 tool_name）\n"
            "- read: 查看指定工具当前生效的完整 description\n"
            "- write: 保存优化后的 description（正文第一行将作为工具目录中的简要描述）\n"
            "- reset: 恢复指定工具的出厂默认描述\n"
            "- rollback: 回滚到上一次修改前的版本\n"
            "使用场景：\n"
            "- 总结工具调用失败经验，把错误案例和修正规范沉淀进工具描述\n"
            "- 精简冗长的工具描述以降低 token 消耗\n"
            "- 用户明确要求调整工具的使用规范\n"
            "参数：action(必需，list/read/write/reset/rollback)、tool_name(必需，除list外)、content(必需，仅write)。\n\n"
            "【write 内容规范】\n"
            "- content 为 description 正文，不要包含 <!-- --> 注释头（系统自动添加）\n"
            "- 第一行必须是该工具的一句话功能简介（会展示在工具目录中）\n"
            "- 后续行可包含使用规范、正误示例等；保持原有语言（默认中文）\n"
            "- 不要虚构工具不存在的参数或能力；参数 schema 不可被修改\n"
            "- 保存前建议先 read 当前版本，在其基础上优化而非凭空重写\n\n"
            "✅ 正确示例：\n"
            "1. update_prompt(action=\"read\", tool_name=\"run_command\")\n"
            "2. update_prompt(action=\"write\", tool_name=\"run_command\", content=\"执行 Python 或 PowerShell 命令。\\n【规范】...\")\n"
            "3. update_prompt(action=\"rollback\", tool_name=\"edit\")\n\n"
            "❌ 错误示例：\n"
            "错误1: update_prompt(action=\"write\", tool_name=\"run_command\", content=\"\")\n"
            "原因：content 不能为空\n\n"
            "错误2: update_prompt(action=\"read\")\n"
            "原因：read 需要 tool_name 参数"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "read", "write", "reset", "rollback"],
                    "description": "操作类型：list列出工具、read查看描述、write保存优化、reset恢复默认、rollback回滚上次修改"
                },
                "tool_name": {
                    "type": "string",
                    "description": "目标工具名称（action=list 时不需要）。可用工具名可通过 action=list 获取"
                },
                "content": {
                    "type": "string",
                    "description": "新的 description 正文（仅 action=write 时需要）。第一行为一句话功能简介，后续行可含使用规范与示例"
                }
            },
            "required": ["action"]
        },
    }
]


def get_all_tool_definitions_from_registry() -> list[dict]:
    """
    从注册表获取所有工具定义（向后兼容接口）。
    
    该函数合并以下来源的工具：
    1. 装饰器注册的工具（通过 @atomic_tool 和 @control_tool 装饰器）
    2. 本文件中的旧定义（ATOMIC_TOOL_DEFINITIONS 和 CONTROL_TOOL_DEFINITIONS）
    
    Returns:
        list[dict]: 所有工具定义列表，每个定义包含：
            - name: 工具名称
            - category: 工具类别（atomic、control等）
            - description: 工具描述
            - parameters: 参数定义（OpenAI function calling格式）
    """
    from .registry import get_tool_registry

    registry = get_tool_registry()

    # 获取注册表中的所有工具定义
    all_definitions = registry.get_all_tool_definitions()

    return all_definitions


# ---------------------------------------------------------------------------
# 工具描述覆盖层：应用用户数据目录下的描述覆盖（PersonalData/prompts/tools/*.md）
# 就地修改本模块常量，所有消费方（BaseChatModel/stream_parser/dispatch 等）
# 因持有同一批 list/dict 引用而自动生效。详见 prompt_overrides.py 模块说明。
# ---------------------------------------------------------------------------
try:
    from .prompt_overrides import apply_tool_overrides as _apply_tool_overrides

    _apply_tool_overrides()
except Exception:  # 覆盖层加载失败不影响启动，静默回退内置默认描述
    pass
