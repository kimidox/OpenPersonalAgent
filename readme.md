# OpenPersonalAgent · SkillAgent

[中文版README](./readme_CN.md)

## Project Overview

OpenPersonalAgent is an **intelligent agent system (SkillAgent) based on LLM tool calling**, featuring an innovative **"Skill-First" architecture**:

- 📋 **Business Rules as Documents**: Write business specifications as Markdown Skill documents on disk
- 🔧 **On-Demand Dynamic Loading**: Agent intelligently selects and loads relevant Skills based on user needs
- 🧩 **Multi-Skill Composition**: Combine multiple Skill constraints in a single task
- ⚡ **Atomic Command Execution**: Complete file operations and desktop automation via `run_command` within a bounded workspace
- 🤖 **Multi-Model Support**: Supports GLM, Qwen, Gemma, and other LLM backends

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
- ✅ **Package Installation Confirmation**: Detects pip/npm commands and requires user confirmation
- ✅ **Skill Dependency Management**: Auto-detects Skill package requirements.txt and prompts installation
- ✅ **Step Limit Protection**: `SKILL_AGENT_MAX_STEPS` (default 50) prevents infinite loops
- ✅ **Write Operation Monitoring**: Auto-detects repeated writes and intelligently ends tasks

### 3. Multi-Model Support

The project supports multiple LLM backends:

| Model Type | Example Models | Features |
|---------|-------------|------|
| **GLM Series** | glm-5, glm-4 | Zhipu AI, supports deep thinking |
| **Qwen Series** | qwen3.5, qwen-turbo | Alibaba Tongyi Qianwen series |
| **Gemma Series** | gemma-2, gemma-7b | Google open-source models |
| **Other Compatible** | gpt-4, claude, etc. | OpenAI API compatible |

### 4. Intelligent Memory System

- ✅ **Skill Execution Memory**: Records execution experiences (failures, fixes, best practices) to avoid repeating mistakes
- ✅ **Lazy Loading**: Memory loaded on-demand when Skill encounters difficulties
- ✅ **FTS5 Semantic Search**: SQLite FTS5 full-text indexing for relevant memory retrieval
- ✅ **Async Summarization**: Background thread summarization without blocking main workflow
- ✅ **Long-term Memory**: Cross-session user memory with semantic search support

### 5. Dynamic System Prompt

- ✅ **Placeholder Mechanism**: `{SKILL_CATALOG}`, `{ACTIVE_SKILLS}`, `{USER_MEMORY}`, etc.
- ✅ **Dynamic Construction**: System prompt rebuilt before each LLM call
- ✅ **Skill Switching**: Efficiently replace Skill content without appending messages
- ✅ **Memory Integration**: User memory and recent conversation summary auto-injected

### 6. Modular Frontend Architecture

- ✅ **Component-based Design**: Reusable UI components (ChatBubble, MessageCard, etc.)
- ✅ **State Management**: Centralized session state, stream state, UI state
- ✅ **Style Management**: Type-safe style constants and theme support
- ✅ **Decoupled Logic**: Message handling and stream rendering as independent modules

---

## 📁 Built-in Skill Examples

The project provides 8 ready-to-use Skill examples demonstrating different scenarios:

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

### 5️⃣ DuckDuckGo Search (`id: 8`)
- **Function**: Web search using DuckDuckGo search engine
- **Features**: Supports text search, news search, image search
- **Output**: Automatically fetches detailed content from search results

### 6️⃣ Baidu Search (`id: 9`)
- **Function**: Web search using Baidu search engine
- **Features**: Supports text search, news search, image search
- **Output**: Automatically fetches detailed content from search results
- **Scenarios**: Chinese content search

### 7️⃣ Fund Query (`id: 88`)
- **Function**: Query fund information using akshare
- **Features**: Fund basic info, net value, historical data, fund list with filters
- **Output**: JSON formatted fund data

### 8️⃣ Image Matching Test (`id: 7`)
- **Function**: Screen capture, template matching, automated clicking
- **Features**: Hotkey simulation, coordinate clicking, OpenCV template matching
- **Scenarios**: Desktop automation testing

---

## 🏗️ Technical Architecture

```
PersonalWindowGLM/
├── main.py                     # Program entry
├── skill_agent.py              # Core Agent logic
├── ui_skill_agent.py           # Desktop GUI (PySide6)
├── config.py                   # Configuration management
├── executor.py                 # Command executor
├── base_tool/                  # Atomic tool definitions
│   ├── definitions.py          # Tool schema definitions
│   ├── dispatch.py             # Tool dispatch and security validation
│   └── context.py              # ToolContext implementation
├── skill/                      # Skill loading and execution
│   ├── loader.py               # File scanning and parsing
│   ├── registry.py             # Skill registry
│   ├── execution.py            # Control tool execution
│   ├── processing.py           # Skill processing utilities
│   ├── memory_summarizer.py    # Skill memory summarization
│   └── types.py                # Skill type definitions
├── llm/                        # LLM interface
│   ├── BaseChatModel.py        # Model base class
│   ├── glm_chat_model.py       # GLM model implementation
│   ├── qwen_chat_model.py      # Qwen model implementation
│   ├── gemma_chat_model.py     # Gemma model implementation
│   └── llm_config_manager.py   # Model configuration management
├── memory/                     # Session persistence
│   ├── memory.py               # Memory management interface
│   ├── sqlite_memory.py        # SQLite storage implementation
│   ├── long_term_memory.py     # Long-term memory management
│   ├── searcher.py             # FTS5 semantic search
│   └── conversation.py         # Conversation management
├── prompt/                     # Dynamic prompt management
│   ├── dynamic_prompt.py       # Dynamic system prompt builder
│   └── template.py             # Prompt template definitions
├── ui/                         # Modular frontend
│   ├── components/             # Reusable UI components
│   │   ├── chat_bubble.py      # Chat bubble component
│   │   ├── message_card.py     # Message card component
│   │   └── settings_dialog.py  # Settings dialog
│   ├── views/                  # Page views
│   │   └── main_window.py      # Main window
│   ├── state/                  # State management
│   │   ├── session_state.py    # Session state
│   │   └── stream_state.py     # Stream state
│   ├── styles/                 # Style management
│   │   └── style_manager.py    # Style manager
│   └── utils/                  # UI utilities
│       ├── message_handler.py  # Message handling
│       └── stream_renderer.py  # Stream rendering
├── database/                   # Database layer
└── PersonalData/               # User data directory
    ├── Skills/                 # Skill document directory
    │   ├── DuckDuckGoSearch/
    │   ├── baiduSearch/
    │   ├── 基金查询/
    │   ├── excel操作/
    │   ├── 小说生成/
    │   ├── 时间格式转换/
    │   ├── 聊天语气/
    │   └── 图片匹配测试/
    ├── data/                   # Database files
    └── logs/                   # Log files
```

---

## 🔄 Skill Workflow

### Loading Mechanism
1. **Directory Scan**: Each first-level subfolder is treated as a Skill package
2. **Main Document Resolution**: Prefer `<folder_name>.md` or `SKILL.md`, otherwise take first `.md`
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
      Step 2: Extract all backtick-wrapped file paths
      Step 3: Read each referenced file (must specify skill_id)
      Step 4: Execute scripts under scripts/ (if any)
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
Dangerous Prefixes: del, erase, rmdir, rd, copy, move, ren, rename, mkdir, md
Dangerous Patterns: >, >>, set-content, remove-item, rm, etc.

Triggered Actions:
→ Show confirmation dialog ("Confirm" / "Cancel")
→ User cancellation terminates command
→ Record to session history
```

### Package Installation Confirmation
```python
# skill_agent.py - _is_package_install_command()
Supported Package Managers: pip, pip3, npm, yarn, pnpm, conda, cargo, gem, go, apt, choco, scoop, winget

Triggered Actions:
→ Show confirmation dialog with package names
→ Execute installation after user confirmation
```

### Skill Dependency Auto-Detection
```python
# base_tool/dispatch.py - check_skill_dependencies()
- Auto-scan requirements.txt in Skill package
- Detect if required dependencies are installed
- Prompt user to confirm installation of missing packages
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
SKILL_AGENT_AUTO_LOAD=true           # Auto-load Skills
DEFAULT_SKILL_AGENT_USER=default_user

# ===== Screenshot Configuration =====
SCREENSHOT_GRID_STEP_PX=32           # Screenshot grid step size
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
- PySide6 >= 6.5.0 (GUI interface)
- openai >= 1.0.0 (LLM invocation)
- sqlalchemy >= 2.0.0 (Database)
- pydantic >= 2.0.0 (Data validation)
- Pillow >= 9.0.0 (Image processing)
- opencv-python >= 4.8.0 (Image matching)
- pyautogui >= 0.9.54 (Desktop automation)
- pandas ~= 3.0.1 (Data processing)

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

![SkillAgent Main Interface](doc/img_1.png)


![Settings Dialog](doc/img_2.png)

---

## 📝 Developing Custom Skills

### Skill Document Structure
```markdown
---
id: 100                          # Unique identifier (number or string)
name: My Custom Skill            # Display name
description: Brief description   # Shown in catalog
---

## Function Description
Detailed description of Skill functionality and use cases...

## Execution Steps
1. First step...
2. Second step...

## Invocation Command
`python scripts/my_script.py "{parameter}"`

## Dependencies (Optional)
Create requirements.txt in the Skill package:
```
ddgs
requests
```

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
├── output/              # Optional: output directory
└── requirements.txt     # Optional: Python dependencies
```

### Best Practices
✅ **Clear Steps**: Use ordered lists to define clear execution flow  
✅ **Parameter Description**: Detailed description of input parameters and formats  
✅ **Constraint Declaration**: Mark mandatory rules with 【Mandatory Constraint】  
✅ **Error Handling**: Describe exception handling approaches  
✅ **Resource References**: Use backticks to mark intra-package file paths `` `./example/file.md` ``  
✅ **Dependency Declaration**: Declare required Python packages in requirements.txt

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
A: Any OpenAI API-compatible backend (configured via `OPENAI_BASE_URL`). Built-in support: GLM, Qwen, Gemma series.

**Q: How to export session records?**
A: Session data stored in SQLite database (`PersonalData/data/`), can query directly or use export function in UI.

**Q: How to install Skill dependencies?**
A: When executing a Skill with missing dependencies, the system will automatically prompt user to confirm installation.

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

### v2.1.0 (Current Version)
- ✨ Added Baidu Search Skill for Chinese content search
- ✨ Added Fund Query Skill with akshare integration
- ✨ Added Skill Execution Memory system to record experiences and avoid repeating mistakes
- ✨ Added FTS5 semantic search for memory retrieval
- ✨ Added Dynamic System Prompt with placeholder mechanism
- ✨ Added lazy loading for Skill memory
- ✨ Added async Skill summarization in background threads
- ✨ Refactored frontend architecture with modular design
- 🔧 Optimized memory system with SQLite FTS5 indexing
- 🔧 Improved long-term memory with semantic search support

### v2.0.0
- ✨ Refactored to Skill-First architecture
- ✨ Added multi-Skill composition execution
- ✨ Added dangerous command detection and confirmation mechanism
- ✨ Added package installation confirmation mechanism
- ✨ Added Skill dependency auto-detection and installation
- ✨ Added auto-end detection
- ✨ Added session persistence and multi-tab support
- ✨ Added multi-model support (GLM, Qwen, Gemma)
- 🔧 Optimized workspace sandbox security
- 🐛 Fixed multiple stability issues

---

**⭐ If this project helps you, please give it a Star!**
