# OpenPersonalAgent · SkillAgent

[中文版readme](./readme_CN.md)

## Project Overview

OpenPersonalAgent is an **intelligent agent system (SkillAgent) based on LLM tool calling**, featuring an innovative **"Skill-First" architecture**:

- 📋 **Business Rules as Documents**: Write business specifications as Markdown Skill documents on disk
- 🔧 **On-Demand Dynamic Loading**: Agent intelligently selects and loads relevant Skills based on user needs
- 🧩 **Multi-Skill Composition**: Combine multiple Skill constraints in a single task
- ⚡ **Atomic Command Execution**: Complete file operations and desktop automation via `run_command` within a bounded workspace

---

## ✨ Core Features

### 1. Intelligent Skill System

| Layer | Function | Description |
|------|----------|-------------|
| **Skill Registry** | Scan Skills directory, parse metadata and body | Supports hot-reload via `reload_skills()` |
| **Control Tools** | `select_skill` / `finish` / `ask_user` | Load Skills, end session, ask user |
| **Atomic Tools** | `run_command` | Unified execution through `ToolContext(work_dir)` |

### 2. Secure Execution Mechanism

- ✅ **Workspace Isolation**: All file operations confined to `work_dir`, preventing path traversal attacks
- ✅ **Dangerous Command Detection**: Auto-detects `del`, `rmdir`, `>` etc. and requires user confirmation
- ✅ **Step Limit Protection**: `SKILL_AGENT_MAX_STEPS` (default 50) prevents infinite loops
- ✅ **Write Operation Monitoring**: Auto-detects repeated writes and intelligently ends tasks

---

## 📁 Built-in Skill Examples

The project provides 5 ready-to-use Skill examples demonstrating different scenarios:

### 1️⃣ Novel Generation (`id: 1`)
- **Function**: Automatically generate novel content based on chapter outlines
- **Features**: Auto-numbering, plot consistency maintenance, word count control (3000-5000 words)
- **Output**: Markdown formatted chapter files

### 2️⃣ Chat Tone (`id: 2`)
- **Function**: Add personalized tone style to AI responses
- **Features**: Musical note symbols, tone words, sentence pattern templates
- **Scenarios**: Role-playing, personalized assistant

### 3️⃣ Time Format Conversion (`id: 5`)
- **Function**: Unified time format conversion (datetime ↔ timestamp)
- **Features**: Timezone support, multiple input format recognition

### 4️⃣ Excel Operations (`id: 6`)
- **Function**: Automated Excel file reading
- **Integration**: Python script invocation

---

## 🏗️ Technical Architecture

```
PersonalWindowGLM/
├── skill_agent.py              # Core Agent logic
├── ui_skill_agent.py           # Desktop GUI (PySide6)
├── config.py                   # Configuration management
├── base_tool/                  # Atomic tool definitions
│   ├── definitions.py          # Tool schema definitions
│   ├── dispatch.py             # Tool dispatch and security validation
│   └── context.py              # ToolContext implementation
├── skill/                      # Skill loading and execution
│   ├── loader.py               # File scanning and parsing
│   ├── registry.py             # Skill registry
│   └── execution.py            # Control tool execution
├── memory/                     # Session persistence
│   └── conversation.py         # SQLite storage
├── database/                   # Database layer
└── PersonalData/Skills/        # Skill document directory
    ├── excel操作/
    ├── 小说生成/
    ├── 时间格式转换/
    └── 聊天语气/
```

---

## 🔄 Skill Workflow

### Loading Mechanism
1. **Directory Scan**: Each subfolder is treated as a Skill package
2. **Main Document Resolution**: Prefer `<folder_name>.md`, otherwise take first `.md`
3. **Metadata Extraction**: Parse frontmatter wrapped in `---` (`id`, `name`, `description`)
4. **Runtime Indexing**: Maintained by `SkillRegistry`, supports hot-reload

### Execution Flow
```
User Query → [System Prompt: Skill Catalog Summary]
           ↓
      Model Decision: select_skill(skill_id)
           ↓
      [Mandatory 6-Step Loading Process]
      Step 1: Read complete main document
      Step 2: Extract all referenced file paths
      Step 3: Read each referenced file (must specify skill_id)
      Step 4: Execute scripts under scripts/
      Step 5: Merge into final context
      Step 6: Recursively load associated Skills
           ↓
      [Context Injection: All loaded Skill full texts]
           ↓
      Execute run_command to complete operations
           ↓
      finish(message) Return result
```

### Multi-Skill Composition
- **Cumulative Loading**: Multiple `select_skill` calls merge rather than overwrite
- **Deduplication Optimization**: Same Skill not appended repeatedly
- **Conflict Resolution**: More specific or later-loaded rules take precedence
- **Cross-Skill Collaboration**: Documents can declare dependencies on other Skills

---

## 🛡️ Security Design Details

### Workspace Sandbox
```python
# base_tool/dispatch.py - _resolve_safe()
- All paths resolved to real paths under Path(work_dir).resolve()
- Forbidden ../ path traversal
- Error message: "Path must stay inside the working directory"
```

### Dangerous Command Interception
```python
# skill_agent.py - _is_dangerous_command()
Dangerous Prefixes: del, erase, rmdir, rd, copy, move, ren, mkdir
Dangerous Patterns: >, >>, set-content, remove-item, rm, etc.

Triggered Actions:
→ Show confirmation dialog ("Confirm" / "Cancel")
→ User cancellation terminates command
→ Record to session history
```

### Auto-End Detection
- Monitor last 10 commands
- Detect 2+ repeated successful writes → auto-call `finish()`
- Prevent infinite write loops

---

## 💾 Session Persistence

### Multi-Tab Support
- **New Session**: `start_new_conversation()` → Generate UUID
- **Switch Session**: `set_conversation_id(id)`
- **History List**: `list_saved_conversations()`

### Stored Content
- Complete conversation history (system/user/assistant/tool)
- Loaded Skill list
- Tool call records (with parameters)
- Reasoning process (reasoning_content)

### Skill Visibility Control
- **Disable Mechanism**: `skill_agent_disabled_skills.json`
- **UI Management**: Settings dialog can toggle enable/disable
- **Effect**: Disabled Skills not shown in catalog, cannot be selected

---

## ⚙️ Configuration

Configure via `.env` file in project root:

```bash
# ===== LLM Configuration =====
OPENAI_API_KEY=your-api-key
OPENAI_BASE_URL=https://api.example.com/v1
MODEL_NAME=gpt-4

# ===== Workspace Configuration =====
WORKER_DIR=PersonalData              # Agent workspace root directory
SKILLS_DIR=Skills                    # Relative path to Skills

# ===== Execution Limits =====
SKILL_AGENT_MAX_STEPS=50             # Max tool calls per turn

# ===== UI Options =====
SKILL_AGENT_UI_SHOW_TOOL_CALLS=true  # Show tool call details
DEFAULT_SKILL_AGENT_USER=default_user
```

---

## 🚀 Quick Start

### Requirements
- Python 3.11+

### Install Dependencies
```bash
pip install -r requirements.txt
```

Main dependencies:
- PySide6 (GUI interface)
- python-dotenv (configuration management)
- openai (LLM invocation)

### Run the Application
```bash
# Method 1: Direct run
python main.py

# Method 2: Package as exe (see build.bat)
# Packaged exe is in dist/OpenPersonalAgent/ directory
```

### First-Time Setup
1. Copy `.env.example` to `.env`
2. Fill in API key and model configuration
3. Run `main.py` to launch the interface
4. View available Skills in the left sidebar list
5. Enter questions to start chatting

---

## 🎨 Interface Preview

![SkillAgent Main Interface](doc/img.png)

![Skill Conversation Example](doc/img_1.png)

![Tool Call Logs](doc/img_2.png)

![Settings Dialog](doc/img_3.png)

---

## 📝 Developing Custom Skills

### Skill Document Structure
```markdown
---
id: 100                          # Unique identifier (numeric)
name: My Custom Skill            # Display name
description: Brief description   # Shown in catalog
---

## Function Description
Detailed description of Skill functionality and use cases...

## Execution Steps
1. First step...
2. Second step...

## Invocation Command
`scripts/my_script.py "{parameter}"`

## Notes
- Constraint 1
- Constraint 2
```

### Directory Convention
```
my_skill/                # Skill package directory (first-level subfolder)
├── SKILL.md             # Main document (preferred) or my_skill.md
├── scripts/             # Optional: script files
│   └── my_script.py
├── example/             # Optional: example files
│   └── demo.md
└── output/              # Optional: output directory
```

### Best Practices
✅ **Clear Steps**: Use ordered lists to define clear execution flow  
✅ **Parameter Description**: Detailed description of input parameters and formats  
✅ **Constraint Declaration**: Mark mandatory rules with 【Mandatory Constraint】  
✅ **Error Handling**: Describe exception handling approaches  
✅ **Resource References**: Use backticks to mark intra-package file paths `` `./example/file.md` ``  

---

## 🔍 Advanced Features

### Token Economy
- First turn only injects **Skill catalog summary** (lightweight)
- Full documents loaded only after `select_skill`
- Effectively controls context length and cost

### Observability
```python
# Log callback interface
run(user_query, log_callback=lambda msg, type: print(f"[{type}] {msg}"))

# Message types:
# - "think": Model reasoning process
# - "tool": Tool calls
# - "doc": Skill document loading
# - "base_tool": Command execution results
# - "assistant": Final response
# - "await_user": Waiting for user confirmation
```

### Recursive Skill Loading
Skill documents can reference other Skill files:
- Paths like `` `./path/to/file.md` `` in main document are auto-extracted
- Each extracted file will be read
- If new Skill references found, continue recursive loading
- Until no new files remain

---

## ❓ FAQ

**Q: How to add new Skills?**
A: Create a new folder under `PersonalData/Skills/`, write an `.md` document. Restart or call `reload_skills()` to take effect.

**Q: What if dangerous commands are falsely blocked?**
A: Currently uses hard-coded detection logic. To adjust whitelist, modify `_is_dangerous_command()` method in `skill_agent.py`.

**Q: Which LLM backends are supported?**
A: Any OpenAI API-compatible backend (configured via `OPENAI_BASE_URL`). Tested: GPT-4, Claude, local Ollama, etc.

**Q: How to export session records?**
A: Session data stored in SQLite database (`database/sqllite_data/`), can query directly or use export function in UI.

---

## 📄 License

MIT License

---

## 🤝 Contributing Guide

Issues and Pull Requests are welcome!

1. Fork this repository
2. Create feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to branch (`git push origin feature/AmazingFeature`)
5. Open Pull Request

---

## Changelog

### v2.0.0 (Current Version)
- ✨ Refactored to Skill-First architecture
- ✨ Added multi-Skill composition execution
- ✨ Added dangerous command detection and confirmation mechanism
- ✨ Added auto-end detection
- ✨ Added session persistence and multi-tab support
- 🔧 Optimized workspace sandbox security
- 🐛 Fixed multiple stability issues

---

**⭐ If this project helps you, please give it a Star!**
