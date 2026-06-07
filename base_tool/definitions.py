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
    "run_command": "执行命令行程序或脚本。",
    "file_operation": "文件操作工具。支持四种操作：",
    "edit": "精确编辑文件。在文件中搜索指定内容并替换。",
    "read_memory": "读取长期记忆。从数据库中读取已保存的信息。",
    "write_memory": "写入长期记忆。将内容保存到数据库中。",
    "create_scheduled_task": "创建定时任务提醒。",
    "list_scheduled_tasks": "列出定时任务。",
    "delete_scheduled_task": "删除定时任务。",
    "uploaded_files": "管理已上传文件。支持三种操作：list(列出文件)、get_content(获取内容)、get_metadata(获取元信息)。",
    "get_accessibility_tree": "获取窗口的Accessibility Tree（UI元素结构树）。返回窗口中所有UI元素的名称、类型、坐标等信息。",
    "find_element": "查找UI元素。支持按名称、AutomationId、控件类型、坐标等方式查找。",
    "click_element": "点击UI元素。使用InvokePattern或鼠标点击。",
    "type_text": "在UI元素中输入文本。使用ValuePattern或SendKeys。",
    "scroll_element": "滚动UI元素。支持上下左右滚动。",
    "get_element_state": "获取UI元素的状态信息。",
    "start_application": "启动应用程序。支持通过程序名、路径或URL启动应用。",
    "list_installed_apps": "查询系统已安装的应用程序列表。返回程序名称、安装路径、可执行文件等信息。",
}

CONTROL_TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "select_skill",
        "description": (
            "加载指定的 Skill 文档，获取完整的操作指南。\n"
            "参数：skill_id（必需），要加载的 Skill 的 ID。\n"
            "可多次调用加载多个 Skill，已加载的不会重复追加。\n"
            "【Skill 加载铁律】（不可跳过）\n"
            "1. 完整阅读主文档全部内容\n"
            "2. 逐行扫描文档，提取所有反引号包裹的文件路径\n"
            "3. 对每个文件路径，**必须**调用 run_command 读取内容（必须指定 skill_id）\n"
            "4. 若文档要求运行 scripts/ 下的 .py 脚本，**必须**执行\n"
            "5. 若文档语义化表明要求执行其他工具操作，***必须**执行\n"
            "6. 将所有内容完整合并为最终上下文\n"
            "7. 若发现新的 Skill 引用，递归加载直到无新文件"
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
            "参数：question(必需)、choices(可选)、context(可选)。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "要问用户的问题"
                },
                "choices": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "可选的回答选项列表"
                },
                "context": {
                    "type": "string",
                    "description": "问题的上下文信息"
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
            "参数：message（必需），给用户的完整答复。"
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
    {
        "name": "load_skill_memory",
        "description": (
            "加载指定 Skill 的执行经验（skill_memory.md）。"
            "经验内容包含之前执行该 Skill 时遇到的问题及解决方案。"
            "可通过 query 参数进行语义检索，精准获取与当前问题相关的经验。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "skill_id": {"type": "string", "description": "Skill 唯一标识"},
                "query": {"type": "string", "description": "检索关键词，用于语义搜索相关经验。不提供则返回最近的记录。"},
                "limit": {"type": "integer", "description": "返回经验记录的最大数量，默认 5。"},
            },
            "required": ["skill_id","query","limit"],
        },
    },
]

ATOMIC_TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "run_command",
        "description": (
            "执行命令行程序或脚本。\n"
            "常用场景：\n"
            "- 运行 Python 脚本: python script.py\n"
            "- 安装依赖: pip install package\n"
            "- 运行测试: pytest\n"
            "- Git 操作: git status\n"
            "参数：command(必需)、cwd(可选)、skill_id(可选)、timeout_sec(可选，默认60秒)。\n\n"
            "【文件操作编码规范】（必须遵守）\n"
            "1. 写入或修改文件时，优先使用 Write 或 SearchReplace 工具（原生支持 UTF-8 编码）\n"
            "2. 若必须使用 run_command 进行文件写入，必须显式指定 UTF-8 编码：\n"
            "   - PowerShell: 使用 -Encoding UTF8 参数（如 Set-Content -Path file.txt -Value \"内容\" -Encoding UTF8）\n"
            "   - 禁止使用裸重定向 > 或不带编码参数的 Set-Content、Out-File 等命令\n"
            "3. 违反编码规范会导致文件乱码，影响后续处理\n\n"
            "【错误处理规范】执行后如果满足以下任一条件，必须立即调用 load_skill_memory：\n"
            "- exit_code ≠ 0（命令执行失败）\n"
            "- 返回 stderr 有错误信息\n"
            "- 文件未找到或路径错误\n"
            "- 连续失败次数 ≥ 1 次"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "要执行的 CMD 命令字符串",
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
                    "description": "超时秒数，默认 60，最大 180",
                },
            },
            "required": ["command","cwd"],
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
            "参数：action(必需，read/write/delete/list)、path(必需)、content(可选，仅write)、skill_id(可选，访问skill包内文件)。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["read", "write", "delete", "list"],
                    "description": "操作类型：read读取、write写入、delete删除、list列出目录"
                },
                "path": {
                    "type": "string",
                    "description": "文件或目录路径"
                },
                "content": {
                    "type": "string",
                    "description": "写入内容（仅 action=write 时使用，注意write会全量覆盖。）"
                },
                "skill_id": {
                    "type": "string",
                    "description": "Skill ID，指定后 path 相对于 skill 包目录"
                }
            },
            "required": ["action", "path"]
        },
    },
    {
        "name": "edit",
        "description": (
            "精确编辑文件。在文件中搜索指定内容并替换。\n"
            "特点：只替换第一个匹配项，未找到则报错。\n"
            "参数：path(必需)、old_str(必需，要搜索的内容)、new_str(必需，替换后的内容)、skill_id(可选)。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "要编辑的文件路径"
                },
                "old_str": {
                    "type": "string",
                    "description": "要搜索的内容（必须精确匹配）"
                },
                "new_str": {
                    "type": "string",
                    "description": "替换后的内容"
                },
                "skill_id": {
                    "type": "string",
                    "description": "Skill ID，指定后 path 相对于 skill 包目录"
                }
            },
            "required": ["path", "old_str", "new_str"]
        },
    },
    {
        "name": "read_memory",
        "description": (
            "读取长期记忆。从数据库中读取已保存的信息。\n"
            "使用场景：\n"
            "- 用户提及之前的偏好、设置或重要信息时\n"
            "- 询问'你还记得...'或'上次我们...'相关问题\n"
            "- 需要延续之前会话中的上下文或决策时\n"
            "提供关键词时会进行语义检索，返回最相关的记忆片段。\n"
            "不提供关键词时返回所有记忆（向后兼容）。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "检索关键词，用于匹配相关的记忆内容，为空时返回所有记忆",
                },
                "limit": {
                    "type": "integer",
                    "description": "最大返回记忆数量，默认 10",
                },
            },
            "required": ['query','limit'],
        },
    },
    {
        "name": "write_memory",
        "description": (
            "写入长期记忆。将内容保存到数据库中。\n"
            "使用场景：\n"
            "- 用户明确要求记住某件事（如'记住这个...'、'以后都这样...'）\n"
            "- 保存用户的长期偏好或习惯\n"
            "- 记录重要的项目配置、决策或约定\n"
            "- 保存需要跨会话使用的上下文信息\n"
            "参数：content(必需，要保存的内容)、mode(可选，append追加/overwrite覆盖，默认append)。\n"
            "追加时会自动添加时间戳标记。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "要保存到长期记忆的内容，应清晰、完整、自包含",
                },
                "mode": {
                    "type": "string",
                    "description": "写入模式：append（追加）或 overwrite（覆盖），默认为 append",
                },
            },
            "required": ["content"],
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
        "name": "get_accessibility_tree",
        "description": (
            "获取窗口的Accessibility Tree（UI元素结构树）。\n"
            "【重要约束】调用本工具前，必须先调用 select_skill(skill_id='desktop_automation') 加载桌面自动化Skill文档，了解完整的执行流程和规划要求。\n"
            "【两种使用方式】\n"
            "1. 不指定参数：返回当前系统所有活跃窗口列表（窗口句柄、标题、进程ID等）\n"
            "2. 指定window_title或process_id：返回该窗口的详细UI元素结构树\n"
            "这是Windows桌面自动化的核心感知工具，通过UI Automation API获取窗口信息。\n"
            "返回信息包括：元素名称、控件类型、AutomationId、坐标、状态、支持的Pattern等。\n"
            "使用场景：\n"
            "- 了解当前系统有哪些活跃窗口\n"
            "- 需要了解窗口中有哪些可操作的UI元素\n"
            "- 需要定位按钮、输入框、菜单等控件\n"
            "- 需要获取元素的精确坐标或ID\n"
            "参数：window_title(可选，窗口标题)、process_id(可选，进程ID)、max_depth(可选，最大遍历深度，默认5)、max_elements(可选，最大元素数量，默认500)。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "window_title": {
                    "type": "string",
                    "description": "窗口标题（支持部分匹配），不提供则获取焦点窗口"
                },
                "process_id": {
                    "type": "integer",
                    "description": "进程ID，用于精确定位窗口"
                },
                "max_depth": {
                    "type": "integer",
                    "description": "最大遍历深度，默认5"
                },
                "max_elements": {
                    "type": "integer",
                    "description": "最大元素数量限制，默认500"
                }
            },
            "required": []
        },
    },
    {
        "name": "find_element",
        "description": (
            "查找UI元素。\n"
            "【重要约束】调用本工具前，必须先调用 select_skill(skill_id='desktop_automation') 加载桌面自动化Skill文档。\n"
            "支持多种查找策略：\n"
            "- by_name: 按元素名称查找（支持部分匹配）\n"
            "- by_automation_id: 按AutomationId精确查找\n"
            "- by_control_type: 按控件类型查找（如Button、Edit等）\n"
            "- by_coordinates: 按屏幕坐标查找该位置的元素\n"
            "- by_pattern: 按支持的Pattern查找（如InvokePattern表示可点击）\n"
            "使用场景：\n"
            "- 需要定位特定的按钮、输入框等控件\n"
            "- 需要找到所有可点击的元素\n"
            "- 需要确认某个坐标处是什么元素\n"
            "参数：method(必需，查找方法)、query(必需，查找条件)、window_title(可选，限制搜索范围)、max_results(可选，最大结果数)。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "method": {
                    "type": "string",
                    "enum": ["by_name", "by_automation_id", "by_control_type", "by_coordinates", "by_pattern"],
                    "description": "查找方法：by_name按名称、by_automation_id按ID、by_control_type按类型、by_coordinates按坐标、by_pattern按Pattern"
                },
                "query": {
                    "type": "string",
                    "description": "查找条件：名称、AutomationId、控件类型、坐标(x,y)或Pattern名称"
                },
                "window_title": {
                    "type": "string",
                    "description": "窗口标题，限制搜索范围"
                },
                "max_results": {
                    "type": "integer",
                    "description": "最大返回结果数，默认50"
                }
            },
            "required": ["method", "query"]
        },
    },
    {
        "name": "click_element",
        "description": (
            "点击UI元素。\n"
            "【重要约束】调用本工具前，必须先调用 select_skill(skill_id='desktop_automation') 加载桌面自动化Skill文档。\n"
            "支持两种点击方式：\n"
            "- invoke: 使用InvokePattern（推荐，更可靠）\n"
            "- mouse: 使用鼠标点击坐标\n"
            "使用场景：\n"
            "- 点击按钮、菜单项等可交互元素\n"
            "- 确认对话框\n"
            "- 选择选项\n"
            "参数：element(必需，元素信息或元素定位条件)、method(可选，点击方式，默认invoke)、wait_time(可选，点击后等待时间)。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "element": {
                    "type": "string",
                    "description": "元素定位条件：可以是元素名称、AutomationId，或JSON格式的元素信息"
                },
                "method": {
                    "type": "string",
                    "enum": ["invoke", "mouse"],
                    "description": "点击方式：invoke使用InvokePattern，mouse使用鼠标点击"
                },
                "wait_time": {
                    "type": "number",
                    "description": "点击后等待时间（秒），默认0.1"
                },
                "window_title": {
                    "type": "string",
                    "description": "窗口标题，用于定位元素"
                }
            },
            "required": ["element"]
        },
    },
    {
        "name": "type_text",
        "description": (
            "在UI元素中输入文本。\n"
            "【重要约束】调用本工具前，必须先调用 select_skill(skill_id='desktop_automation') 加载桌面自动化Skill文档。\n"
            "支持两种输入方式：\n"
            "- value: 使用ValuePattern（推荐，更可靠）\n"
            "- sendkeys: 使用SendKeys模拟键盘输入\n"
            "使用场景：\n"
            "- 在文本框中输入内容\n"
            "- 填写表单\n"
            "- 搜索框输入关键词\n"
            "参数：element(必需，元素定位条件)、text(必需，要输入的文本)、method(可选，输入方式)、clear_first(可选，是否先清空)、wait_time(可选，输入后等待时间)。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "element": {
                    "type": "string",
                    "description": "元素定位条件：可以是元素名称、AutomationId，或JSON格式的元素信息"
                },
                "text": {
                    "type": "string",
                    "description": "要输入的文本内容"
                },
                "method": {
                    "type": "string",
                    "enum": ["value", "sendkeys"],
                    "description": "输入方式：value使用ValuePattern，sendkeys使用SendKeys"
                },
                "clear_first": {
                    "type": "boolean",
                    "description": "是否先清空现有内容，默认true"
                },
                "wait_time": {
                    "type": "number",
                    "description": "输入后等待时间（秒），默认0.1"
                },
                "window_title": {
                    "type": "string",
                    "description": "窗口标题，用于定位元素"
                }
            },
            "required": ["element", "text"]
        },
    },
    {
        "name": "scroll_element",
        "description": (
            "滚动UI元素。\n"
            "【重要约束】调用本工具前，必须先调用 select_skill(skill_id='desktop_automation') 加载桌面自动化Skill文档。\n"
            "支持四个方向：up/down/left/right\n"
            "支持两种滚动量：small（小步滚动）、large（大步滚动）\n"
            "使用场景：\n"
            "- 滚动列表查看更多内容\n"
            "- 滚动页面\n"
            "- 滚动表格\n"
            "参数：element(必需，元素定位条件)、direction(必需，滚动方向)、amount(可选，滚动量)、count(可选，滚动次数)。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "element": {
                    "type": "string",
                    "description": "元素定位条件：可以是元素名称、AutomationId，或JSON格式的元素信息"
                },
                "direction": {
                    "type": "string",
                    "enum": ["up", "down", "left", "right"],
                    "description": "滚动方向：up向上、down向下、left向左、right向右"
                },
                "amount": {
                    "type": "string",
                    "enum": ["small", "large"],
                    "description": "滚动量：small小步、large大步，默认small"
                },
                "count": {
                    "type": "integer",
                    "description": "滚动次数，默认1"
                },
                "window_title": {
                    "type": "string",
                    "description": "窗口标题，用于定位元素"
                }
            },
            "required": ["element", "direction"]
        },
    },
    {
        "name": "get_element_state",
        "description": (
            "获取UI元素的状态信息。\n"
            "【重要约束】调用本工具前，必须先调用 select_skill(skill_id='desktop_automation') 加载桌面自动化Skill文档。\n"
            "返回元素当前状态：是否启用、是否可见、是否可聚焦、是否有焦点、值等。\n"
            "使用场景：\n"
            "- 确认元素是否可操作\n"
            "- 检查CheckBox是否已选中\n"
            "- 检查输入框当前值\n"
            "参数：element(必需，元素定位条件)、window_title(可选，窗口标题)。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "element": {
                    "type": "string",
                    "description": "元素定位条件：可以是元素名称、AutomationId，或JSON格式的元素信息"
                },
                "window_title": {
                    "type": "string",
                    "description": "窗口标题，用于定位元素"
                }
            },
            "required": ["element"]
        },
    },
    {
        "name": "start_application",
        "description": (
            "启动应用程序。\n"
            "【重要约束】调用本工具前，必须先调用 select_skill(skill_id='desktop_automation') 加载桌面自动化Skill文档，了解完整的执行流程和规划要求。\n"
            "支持三种启动方式：\n"
            "- by_name: 通过程序名称启动（如 notepad、chrome、excel）\n"
            "- by_path: 通过完整路径启动（如 C:\\Program Files\\app.exe）\n"
            "- by_url: 通过URL启动（会打开默认浏览器）\n"
            "使用场景：\n"
            "- 启动记事本、Excel等常用程序\n"
            "- 启动特定路径的应用程序\n"
            "- 打开网页链接\n"
            "参数：app(必需，程序名/路径/URL)、method(可选，启动方式，默认by_name)、wait_time(可选，启动后等待时间)。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "app": {
                    "type": "string",
                    "description": "程序名称、完整路径或URL"
                },
                "method": {
                    "type": "string",
                    "enum": ["by_name", "by_path", "by_url"],
                    "description": "启动方式：by_name通过程序名、by_path通过路径、by_url通过URL"
                },
                "wait_time": {
                    "type": "number",
                    "description": "启动后等待时间（秒），默认2秒"
                },
                "args": {
                    "type": "string",
                    "description": "启动参数（可选），如打开特定文件"
                }
            },
            "required": ["app"]
        },
    },
    {
        "name": "list_installed_apps",
        "description": (
            "查询系统已安装的应用程序列表。\n"
            "【重要约束】调用本工具前，必须先调用 select_skill(skill_id='desktop_automation') 加载桌面自动化Skill文档。\n"
            "【使用时机】在调用 start_application 启动程序前，应先调用本工具查询系统已有的程序，让大模型根据用户意图选择合适的程序。\n"
            "返回信息包括：程序名称、安装路径、可执行文件、是否在PATH中等。\n"
            "使用场景：\n"
            "- 用户想启动某个程序但不知道具体名称或路径\n"
            "- 需要了解系统有哪些可启动的应用\n"
            "- 根据用户意图匹配最合适的程序\n"
            "参数：filter(可选，过滤关键词，如'office'、'browser')、max_results(可选，最大返回数量，默认50)。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "description": "过滤关键词，用于筛选特定类型的程序（如'office'、'browser'、'editor'）"
                },
                "max_results": {
                    "type": "integer",
                    "description": "最大返回数量，默认50"
                }
            },
            "required": []
        },
    },
]
