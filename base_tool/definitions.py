from __future__ import annotations

ATOMIC_TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "run_command",
        "description": (
            "执行 Windows CMD 命令。command 为要执行的命令字符串，"
            "cwd 为可选的工作目录（相对 work_dir 的路径），"
            "若指定了 skill_id，则 cwd 为相对于该 skill 包目录的路径，"
            "timeout_sec 为超时秒数（默认 60，最大 180）。"
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
                    "description": "工作目录（相对 work_dir 的路径，可选）",
                },
                "skill_id": {
                    "type": "string",
                    "description": "Skill 的 id，若指定则 cwd 为相对于该 skill 包目录的路径",
                },
                "timeout_sec": {
                    "type": "number",
                    "description": "超时秒数，默认 60，最大 180",
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "read_memory",
        "description": (
            "读取长期记忆。从 MEMORY.md 文件中读取已保存的长期记忆内容。"
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "write_memory",
        "description": (
            "写入长期记忆。将内容写入到 MEMORY.md 文件中保存。"
            "mode 参数可指定写入模式：append（追加，默认）或 overwrite（覆盖）。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "要保存到长期记忆的内容",
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
