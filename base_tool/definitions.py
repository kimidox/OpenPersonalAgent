from __future__ import annotations

CONTROL_TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "select_skill",
        "description": (
            "加载指定的 Skill 文档，获取完整的操作指南。\n"
            "参数：skill_id（必需），要加载的 Skill 的 ID。\n"
            "可多次调用加载多个 Skill，已加载的不会重复追加。"
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
            "参数：command(必需)、cwd(可选)、skill_id(可选)、timeout_sec(可选，默认60秒)。"
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
            "使用场景：\n"
            "- 用户要求设置提醒（如'提醒我明天下午3点开会'）\n"
            "- 创建一次性或重复性定时任务\n"
            "- 设置每日、每周或每月的例行提醒\n"
            "参数：title(必需，任务标题)、trigger_time(必需，ISO格式时间)、content(可选，详细内容)、repeat_type(可选，重复类型)。\n"
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
]
