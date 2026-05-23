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
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "skill_id": {"type": "string", "description": "Skill 唯一标识"},
            },
            "required": ["skill_id"],
        },
    },
]

ATOMIC_TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "run_command",
        "description": (
            "执行 Windows CMD 命令完成文件操作、脚本执行等。\n"
            "常用示例：\n"
            "- 列出目录: dir\n"
            "- 读取文件: type filename\n"
            "- 写入文件: echo content > filename\n"
            "- 创建目录: mkdir foldername\n"
            "- 运行脚本: python script.py\n"
            "参数：command(必需)、cwd(可选)、skill_id(可选，用于读取Skill包内文件)、timeout_sec(可选，默认60秒)。"
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
            "required": [],
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
]
