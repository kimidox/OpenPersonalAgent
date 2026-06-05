# OpenPersonalAgent · SkillAgent

[中文版README](./readme_CN.md)

## Project Overview

OpenPersonalAgent is an **intelligent agent system (SkillAgent) based on LLM tool calling**, featuring an innovative **"Skill-First" architecture**:

- 📋 **Business Rules as Documents**: Write business specifications as Markdown Skill documents on disk
- 🔧 **On-demand Dynamic Loading**: Agent intelligently selects and loads relevant Skills based on user needs
- 🧩 **Multi-Skill Composition**: Combine multiple Skill constraints in a single task
- ⚡ **Atomic Command Execution**: Complete file operations and desktop automation via tools in a bounded workspace
- 🤖 **Multi-Model Support**: Supports GLM, Qwen, Gemma, and other LLM backends
- 🏗️ **Virtual Environment Isolation**: Automatic venv creation and management for secure dependency handling
- 📝 **Long-term Memory System**: Persistent user memory with semantic search using jieba Chinese segmentation
- 📄 **Document Parsing**: Support for parsing multiple file formats (PDF, Word, Excel, Markdown, Text, JSON)
- 📅 **Scheduled Tasks**: Create and manage timed tasks with notification or agent conversation execution
- 🔔 **Notification System**: System tray notifications and floating toast windows
- 🚀 **Windows Auto-Start**: Enable/disable automatic startup on Windows login
- ⚙️ **Multi-Config Management**: Manage multiple LLM configuration groups with automatic failover
- 📎 **File Upload & Preview**: Upload and parse documents directly in chat interface
- 🎨 **Background Mode**: Run in background with system tray icon
- 🛠️ **Tool Catalog Progressive Disclosure**: On-demand tool definition loading for token efficiency
- 💾 **Memory Optimization**: Smart memory management with configurable retention
- 🎙️ **Voice Recording & Transcription**: Record audio with sounddevice, transcribe using local Whisper model (faster-whisper)
- 🎭 **Floating Ball**: Desktop floating widget for quick chat access, recording, and background operation
- 🔊 **Text-to-Speech (TTS)**: Local text-to-speech synthesis with Piper engine
- 📋 **Built-in Skills Directory**: System-provided Skills in the Skills/ folder (user Skills in PersonalData/Skills)

---

## ✨ Core Features

### 1. Intelligent Skill System

| Layer | Function | Description |
|------|----------|-------------|
| **Skill Registry** | Scan Skills directory, parse metadata and body | Supports hot-reload via `reload_skills()` |
| **Control Tools** | `select_skill` / `finish` / `ask_user` / `load_skill_memory` | Load Skills, end session, ask user, load execution memory |
| **Atomic Tools** | `run_command` / `file_operation` / `edit` / `read_memory` / `write_memory` | Unified execution through `ToolContext(work_dir)` |

### 2. Secure Execution Mechanism

- ✅ **Workspace Isolation**: All file operations confined to `work_dir`, preventing path traversal attacks
- ✅ **Virtual Environment**: Automatic venv creation in `PersonalData/venv`, all Python commands execute in isolation
- ✅ **Dangerous Command Detection**: Auto-detects `del`, `rmdir`, `>` etc. and requires user confirmation
- ✅ **Package Installation Confirmation**: Detects pip/npm commands and requires user confirmation
- ✅ **Skill Dependency Management**: Auto-scans Skill requirements.txt and prompts for installation
- ✅ **Step Limit Protection**: `SKILL_AGENT_MAX_STEPS` (default 50) prevents infinite loops
- ✅ **Write Operation Monitoring**: Auto-detects repeated writes and intelligently ends tasks
- ✅ **Duplicate Call Detection**: Prevents infinite loops by detecting repeated tool calls

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
- ✅ **Skill Memory Loading**: `load_skill_memory` tool with semantic search for relevant experiences
- ✅ **Lazy Loading**: Memory loaded on-demand when Skill encounters difficulties
- ✅ **FTS5 Semantic Search**: SQLite FTS5 full-text indexing with jieba Chinese segmentation for better Chinese search
- ✅ **Async Summarization**: Background thread summarization without blocking main workflow
- ✅ **Long-term Memory**: Cross-session user memory with semantic search support
- ✅ **Memory Compaction**: Automatic memory compaction when reaching threshold
- ✅ **Read/Write Tools**: `read_memory` and `write_memory` for explicit memory management

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
- ✅ **Token Usage Display**: Optional token usage tracking in UI

### 7. Path & Configuration Management

- ✅ **Unified Path Manager**: `resource_path.paths` handles dev/bundled environment paths
- ✅ **Smart Config Loading**: `.env` auto-copied to user data dir on first run (bundled mode)
- ✅ **Data Directory Isolation**: Clear separation between bundled resources and user data

### 8. Logging System

- ✅ **Dual Output**: Console + rotating file logs in `PersonalData/logs/`
- ✅ **Module Loggers**: Per-module log adapters for better organization
- ✅ **Exception Hook**: Global exception handling and logging

### 9. Document Parser

- ✅ **Multiple Formats**: PDF, Word (DOCX), Excel (XLSX), Markdown, Text, JSON
- ✅ **Factory Pattern**: Dynamic parser selection based on file extension
- ✅ **Validation**: File validation before parsing
- ✅ **Unified Interface**: Consistent `ParseResult` format for all formats

### 10. Scheduled Tasks

- ✅ **Flexible Scheduling**: One-time or recurring (daily, weekly, monthly)
- ✅ **Dual Execution Modes**: Notification only or trigger agent conversation
- ✅ **Smart Timing**: Specify exact trigger time
- ✅ **Repeat Types**: none, daily, weekly, monthly
- ✅ **History Tracking**: Track triggered/pending/canceled task status

### 11. Notification System

- ✅ **System Tray Notifications**: Native Windows tray notifications
- ✅ **Floating Toast Windows**: Beautiful floating toast with fade animations
- ✅ **Configurable Duration**: Customizable display duration
- ✅ **Click-to-dismiss**: Toast windows can be dismissed early
- ✅ **Multiple Types**: System notification or toast display options

### 12. Multi-Configuration Management

- ✅ **Multiple Groups**: Manage multiple LLM configuration sets (model, API key, base URL, etc.)
- ✅ **Auto-Failover**: Automatic switch to next config on failure
- ✅ **Switch Tracking**: History of config switch events
- ✅ **Reorder Support**: Move configs up/down
- ✅ **Add/Delete**: Create new configs or delete unused ones
- ✅ **Parameter Editor**: Edit individual config settings
- ✅ **Default Reset**: Restore default config from .env

### 13. File Upload & Preview

- ✅ **Drag & Drop**: File upload area
- ✅ **Multiple Files**: Upload multiple files at once
- ✅ **Progress Bar**: Real-time parsing progress
- ✅ **File Preview**: Quick preview of parsed content
- ✅ **Max Limit**: Configurable maximum number of uploaded files
- ✅ **Parser Integration**: Direct integration with document parser
- ✅ **Error Handling**: Parse error display and handling

### 14. Background Mode

- ✅ **Tray Icon**: System tray icon in background
- ✅ **Auto-Start**: Windows auto-start in background mode
- ✅ **Task Scheduler**: Scheduled tasks still work in background
- ✅ **Window Size**: Configurable default window dimensions

### 15. Memory Optimization

- ✅ **Progressive Disclosure**: On-demand tool catalog
- ✅ **Background Retention**: Configurable number of messages to keep in background mode
- ✅ **Delay Optimization**: Delay before activating optimization
- ✅ **Token Economy**: Reduces token usage by loading only necessary tools

### 16. Windows Auto-Start

- ✅ **Registry-based**: Windows registry auto-start
- ✅ **Enable/Disable**: Toggle auto-start in settings
- ✅ **Command-line Support**: Auto-start with --background parameter

### 17. Voice Recording & Transcription

- ✅ **Audio Recording**: Sound device with sounddevice
- ✅ **Local Transcription**: faster-whisper model integration
- ✅ **Model Management**: Download/switch Whisper models (tiny/base/small/medium/large)
- ✅ **Recording Management**: Save recordings to PersonalData/records/
- ✅ **Transcription Options**: Configurable language, model size, device, compute type

### 18. Floating Ball Widget

- ✅ **Draggable Widget**: Floating on desktop
- ✅ **Floating Chat Window: Expandable mini-chat interface
- ✅ **Quick Recording**: One-click recording from floating ball
- ✅ **Context Menu**: Access main window, recording controls

### 19. Text-to-Speech (TTS)

- ✅ **Local Synthesis**: Piper TTS engine
- ✅ **Voice Management**: Multiple voice options
- ✅ **Audio Playback**: Integrated audio player
- ✅ **Synthesis Options**: Configurable speech rate, pitch, volume

---

## 📁 Built-in Skill Examples

The project provides 11 ready-to-use Skill examples demonstrating different scenarios:

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

### 9️⃣ WeChat Official Account Article Generation (`id: 100`)
- **Function**: Generate WeChat Official Account articles based on user-provided topics
- **Features**: Structured content (title, intro, body sections, conclusion), word count control (1500-2000 words)
- **Output**: Markdown formatted articles ready for WeChat platform

### 🔟 Meeting Minutes Generation (`id: meeting_minutes_generator`)
- **Function**: Convert transcribed audio/text into structured meeting minutes
- **Features**: Meeting overview, topic discussions, decisions, action items with assignees and deadlines
- **Output**: Well-formatted Markdown meeting minutes

### 1️⃣1️⃣ Scheduled Task Guide (`id: scheduled_task_guide`)
- **Function**: Guide users in creating scheduled tasks with proper execution types and chains
- **Features**: Execution type determination (notification vs agent conversation), execution chain generation, goal extraction
- **Scenarios**: Creating recurring reminders, automated tasks, scheduled agent conversations

---

## 🏗️ Technical Architecture

```
PersonalWindowGLM/
├── main.py                     # Program entry
├── agent.py                    # Legacy desktop automation agent (screenshot-based)
├── skill_agent.py              # Core Agent logic
├── ui_skill_agent.py           # Desktop GUI (PySide6)
├── config.py                   # Configuration management
├── executor.py                 # Command executor
├── logger.py                   # Logging system
├── resource_path.py            # Unified path manager (dev/bundled)
├── skill_agent_preferences.py  # Skill visibility/disabled state management
├── scheduled_tasks.py          # Scheduled task data model and management
├── scheduler.py                # Task scheduler engine
├── notification.py             # Notification system (system tray, toast)
├── autostart.py                # Windows auto-start management
├── recorder.py                 # Voice recording & transcription module
├── PersonalWindowGLM.spec      # PyInstaller spec
├── PersonalWindowGLM_onefile.spec  # Single-file spec
├── build.bat                   # Build script
├── base_tool/                  # Atomic tool definitions
│   ├── definitions.py          # Tool schema definitions (all control/atomic tools)
│   ├── dispatch.py             # Tool dispatch, security validation, venv management
│   └── context.py              # ToolContext implementation
├── skill/                      # Skill loading and execution
│   ├── loader.py               # File scanning, parsing, memory loading
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
│   ├── llm_config_manager.py   # Multi-LLM configuration manager with failover
│   └── token_usage.py          # Token usage tracking
├── memory/                     # Session persistence
│   ├── memory.py               # Memory management interface
│   ├── sqlite_memory.py        # SQLite storage implementation
│   ├── long_term_memory.py     # Long-term memory management
│   ├── searcher.py             # FTS5 semantic search with jieba
│   ├── conversation.py         # Conversation management
│   ├── migration.py            # Memory migration system
│   ├── message.py              # Message model
│   └── reindex_fts.py          # FTS index rebuild
├── prompt/                     # Dynamic prompt management
│   ├── dynamic_prompt.py       # Dynamic system prompt builder
│   └── template.py             # Prompt template definitions
├── document_parser/            # Document parsing module
│   ├── __init__.py             # Parser exports and registration
│   ├── base_parser.py          # Abstract base parser class
│   ├── models.py               # ParseResult data model
│   ├── parser_factory.py       # Parser factory for dynamic selection
│   ├── file_storage.py         # File storage utilities
│   └── parsers/                # Format-specific parsers
│       ├── pdf_parser.py       # PDF document parser
│       ├── word_parser.py      # Word (DOCX) parser
│       ├── excel_parser.py     # Excel (XLSX) parser
│       ├── markdown_parser.py  # Markdown parser
│       ├── text_parser.py      # Plain text parser
│       └── json_parser.py      # JSON parser
├── tts/                        # Text-to-Speech module
│   ├── __init__.py             # Module exports
│   ├── tts_engine.py           # TTS engine interface
│   ├── piper_engine.py         # Piper TTS engine implementation
│   ├── synthesizer.py          # Speech synthesizer
│   ├── audio_player.py         # Audio player
│   ├── voice_manager.py        # Voice manager
│   └── tts_config.py           # TTS configuration
├── ui/                         # Modular frontend
│   ├── components/             # Reusable UI components
│   │   ├── chat_bubble.py      # Chat bubble component
│   │   ├── message_card.py     # Message card component
│   │   ├── chat_session_tab.py # Chat session tab
│   │   ├── await_user_card.py  # Await user confirmation card
│   │   ├── settings_dialog.py  # Settings dialog with multi-config & tasks
│   │   ├── file_upload_area.py # File upload area
│   │   ├── file_preview_card.py# File preview component
│   │   ├── conversation_sidebar.py # Conversation sidebar
│   │   ├── conversation_list_item.py # Conversation list item
│   │   ├── tab_bar.py          # Tab bar component
│   │   └── tts_control.py      # TTS control component
│   ├── views/                  # Page views
│   │   ├── main_window.py      # Main window
│   │   ├── floating_ball.py    # Floating ball widget
│   │   ├── floating_chat_window.py # Floating chat window
│   │   └── worker_thread.py    # Worker thread
│   ├── state/                  # State management
│   │   ├── session_state.py    # Session state
│   │   ├── stream_state.py     # Stream state
│   │   └── ui_state.py         # UI state
│   ├── styles/                 # Style management
│   │   ├── color_scheme.py     # Color scheme
│   │   ├── style_manager.py    # Style manager
│   │   └── ui_skill_agent_styles.css # UI stylesheet
│   └── utils/                  # UI utilities
│       ├── html_utils.py       # HTML utilities
│       ├── markdown_utils.py   # Markdown utilities
│       ├── message_handler.py  # Message handling
│       ├── simple_stream_renderer.py # Simple stream renderer
│       ├── text_utils.py       # Text utilities
│       ├── stream_renderer.py  # Stream rendering
│       ├── file_upload_manager.py # File upload manager
│       └── file_upload_controller.py # File upload controller
├── Skills/                     # Built-in Skills directory (version controlled)
│   ├── meeting_minutes_generator/ # Meeting minutes generation Skill
│   └── scheduled_task_guide/   # Scheduled task creation guide Skill
└── PersonalData/               # User data directory (gitignored)
    ├── Skills/                 # User Skill document directory
    │   ├── DuckDuckGoSearch/
    │   ├── baiduSearch/
    │   ├── 基金查询/
    │   ├── excel操作/
    │   ├── 小说生成/
    │   ├── 时间格式转换/
    │   ├── 聊天语气/
    │   ├── 图片匹配测试/
    │   └── 微信公众号文章生成/
    ├── models/                 # Local model files (Whisper, TTS)
    │   └── base/               # Whisper base model example
    ├── records/                # Recording files directory
    ├── data/                   # Database files (app.db)
    ├── logs/                   # Log files (app_YYYYMMDD.log)
    ├── venv/                   # Auto-created virtual environment
    ├── cache/                  # Cache directory
    └── config/                 # Config directory
```

---

## 🔄 Skill Workflow

### Loading Mechanism
1. **Directory Scan**: Each first-level subfolder is treated as a Skill package
2. **Main Document Resolution**: Prefer `<folder_name>.md` or `SKILL.md`, otherwise take first `.md`
3. **Metadata Extraction**: Parse frontmatter wrapped in `---` (`id`, `name`, `description`)
4. **Memory File Detection**: Look for `skill_memory.md` for execution experiences
5. **Runtime Indexing**: Maintained by `SkillRegistry`, supports hot-reload

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
      [Optional: load_skill_memory for past experiences]
           ↓
      Execute atomic tools (run_command/file_operation/edit/etc)
           ↓
      finish(message) Return result
```

### Multi-Skill Composition
- **Cumulative Loading**: Multiple `select_skill` calls merge rather than overwrite
- **Deduplication Optimization**: Same Skill not appended repeatedly
- **Conflict Resolution**: More specific or later-loaded rules take precedence
- **Cross-Skill Collaboration**: Documents can declare dependencies on other Skills

---

## 🛠️ Atomic Tool Reference

### Control Tools
| Tool | Purpose | Parameters |
|------|---------|-----------|
| `select_skill` | Load a Skill document | `skill_id` (required) |
| `finish` | Complete the task | `message` (required) |
| `ask_user` | Ask user for info/confirmation | `question` (required), `choices` (optional), `context` (optional) |
| `load_skill_memory` | Load Skill execution memory | `skill_id` (required), `query` (required), `limit` (required) |

### File Operations
| Tool | Purpose | Parameters |
|------|---------|-----------|
| `file_operation` | Read/write/delete/list files | `action` (read/write/delete/list, required), `path` (required), `content` (write-only), `skill_id` (optional) |
| `edit` | Precise file edit (search & replace) | `path` (required), `old_str` (required), `new_str` (required), `skill_id` (optional) |

### Command Execution
| Tool | Purpose | Parameters |
|------|---------|-----------|
| `run_command` | Execute shell commands/scripts | `command` (required), `cwd` (required), `skill_id` (optional), `timeout_sec` (optional, default 60, max 180) |

### Memory Operations
| Tool | Purpose | Parameters |
|------|---------|-----------|
| `read_memory` | Read long-term memory (semantic search) | `query` (required), `limit` (required) |
| `write_memory` | Write to long-term memory | `content` (required), `mode` (optional, append/overwrite, default append) |

---

## 🛡️ Security Design Details

### Workspace Sandbox
```python
# base_tool/dispatch.py - _resolve_safe()
- All paths resolved to real paths under Path(work_dir).resolve()
- Forbidden ../ path traversal
- Error message: "Path must stay inside the working directory"
```

### Virtual Environment Isolation
```python
# base_tool/dispatch.py - _ensure_venv_exists()
- Auto-creates venv in PersonalData/venv on first use
- Finds system Python (skips virtual envs) via multiple strategies
- Auto-installs pip if missing using get-pip.py
- All Python commands use venv's python.exe
- Skill dependencies auto-installed in venv
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
→ Configurable via DANGEROUS_COMMAND_PREFIXES / DANGEROUS_COMMAND_CONTAINS
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
- Detect if required dependencies are installed in venv
- Prompt user to confirm installation of missing packages
- Auto-install on confirmation
```

### Auto-End Detection
- Monitor last N commands (configurable via REPEAT_DETECTION_WINDOW_SIZE)
- Detect repeated successful writes → auto-call `finish()`
- Prevent infinite write loops
- Configurable via MAX_CONSECUTIVE_REPEATS

---

## 💾 Session Persistence

### Multi-Tab Support
- **New Session**: `start_new_conversation()` → Generate UUID
- **Switch Session**: `set_conversation_id(id)`
- **History List**: `list_saved_conversations()`
- **Auto-Title**: First message becomes conversation title
- **DB Storage**: SQLite `Conversations` table

### Stored Content
- Complete conversation history (system/user/assistant/tool)
- Loaded Skill IDs list
- Tool call records (with parameters)
- Reasoning process (reasoning_content)
- Message metadata (timestamps, types)

### Skill Visibility Control
- **Disable Mechanism**: `skill_agent_disabled_skills.json`
- **UI Management**: Settings dialog can toggle enable/disable
- **Effect**: Disabled Skills not shown in catalog, cannot be selected
- **Storage**: User data dir (bundled mode) or project root (dev mode)

---

## ⚙️ Configuration

Configure via `.env` file in project root (dev) or user data dir (bundled):

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
MAX_ITERATIONS=20                    # Max iterations for legacy agent

# ===== UI Options =====
SKILL_AGENT_UI_SHOW_TOOL_CALLS=true  # Show tool call details
SKILL_AGENT_AUTO_LOAD=true           # Auto-load Skills
DEFAULT_SKILL_AGENT_USER=default_user
TOKEN_USAGE_ENABLED=true             # Enable token usage tracking
TOKEN_USAGE_SHOW_IN_UI=true          # Show token usage in UI
COPY_BUTTON_ENABLED_TYPES=user,assistant  # Enable copy button for these message types

# ===== Screenshot Configuration =====
SCREENSHOT_GRID_STEP_PX=32           # Screenshot grid step size

# ===== Memory Configuration =====
CONTEXT_WINDOW_SIZE=128000           # Context window size limit
COMPACTION_THRESHOLD=0.8             # Memory compaction threshold (0.0-1.0)
COMPACTION_KEEP_RECENT=10            # Keep N recent messages when compacting
COMPACTION_ENABLED=true              # Enable memory compaction
MEMORY_SEARCH_LIMIT=5                # Max memory search results
MEMORY_MIN_SCORE=0.0                 # Minimum memory search score (0.0-1.0)
MEMORY_SEARCH_ENABLED=true           # Enable memory search

# ===== Tool Call Deduplication =====
TOOL_CALL_DEDUPLICATION_ENABLED=true # Enable duplicate tool call detection
MAX_CONSECUTIVE_REPEATS=3            # Max consecutive repeats before warning
REPEAT_DETECTION_WINDOW_SIZE=10      # Window size for repeat detection

# ===== Dangerous Command Check =====
DANGEROUS_COMMAND_CHECK_ENABLED=true # Enable dangerous command detection
DANGEROUS_COMMAND_PREFIXES=del ,erase ,rmdir ,rd ,copy ,move ,ren ,rename ,mkdir ,md
DANGEROUS_COMMAND_CONTAINS= > , >> , >, >>, set-content , set-content-, add-content , add-content-, out-file , out-file-, new-item , new-item-, remove-item , remove-item-, rm

# ===== Window Size Configuration =====
WINDOW_WIDTH=780                    # Default window width
WINDOW_HEIGHT=620                   # Default window height

# ===== Scheduled Task Configuration =====
SCHEDULED_TASK_SHOW_WINDOW=false    # Show main window when task triggers agent conversation

# ===== Tool Catalog Progressive Disclosure =====
USE_TOOL_CATALOG=true               # Enable tool catalog (progressive disclosure)

# ===== Memory Optimization =====
MEMORY_OPTIMIZATION_ENABLED=true    # Enable memory optimization
MEMORY_OPTIMIZATION_DELAY_SECONDS=30 # Delay before activating optimization (seconds)
BACKGROUND_KEEP_MESSAGES_COUNT=50   # Number of messages to keep in background mode

# ===== Recording Configuration =====
RECORDING_SAMPLE_RATE=16000         # Recording sample rate (Hz)
RECORDING_CHANNELS=1                # Recording channels (1=mono, 2=stereo)
RECORDING_DTYPE=int16               # Recording data type
RECORDING_TRANSCRIPTION_LANGUAGE=zh # Transcription language code
WHISPER_MODEL_SIZE=base             # Whisper model size (tiny, base, small, medium, large)
WHISPER_DEVICE=cpu                  # Whisper device (cpu, cuda)
WHISPER_COMPUTE_TYPE=int8           # Whisper compute type (int8, float16, float32)

# ===== TTS Configuration =====
TTS_ENABLED=true                    # Enable text-to-speech
TTS_ENGINE=piper                    # TTS engine to use
TTS_VOICE=default                   # Default TTS voice
TTS_SPEED=1.0                       # TTS speech speed multiplier
TTS_PITCH=1.0                       # TTS pitch multiplier
TTS_VOLUME=1.0                      # TTS volume multiplier
```

---

## 🚀 Quick Start

### Requirements
- Python 3.11+
- Windows (primarily, cross-platform codebase)

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
- pygetwindow >= 0.0.9 (Window management)
- pandas ~= 3.0.1 (Data processing)
- jieba >= 0.42.1 (Chinese text segmentation)
- sounddevice >= 0.4.6 (Audio recording)
- numpy >= 1.20.0 (Audio processing)
- faster-whisper >= 1.0.0 (Voice transcription)

### Run the Application
```bash
# Method 1: Direct run
python main.py

# Method 2: Package as exe (see build.bat)
# Bundled exe uses %APPDATA%/OpenPersonalAgent/ for user data
```

### First-Time Setup
1. Copy `.env.example` to `.env` (if not exists)
2. Fill in API key and model configuration
3. Run `main.py` to launch the interface
4. Virtual environment auto-created in `PersonalData/venv/`
5. View available Skills in the left sidebar list
6. Enter questions to start chatting

---

## 🎙️ Voice Features & Model Download

This project supports local voice recognition (ASR) and text-to-speech (TTS) using sherpa-onnx ONNX models. Models are **external to the package** to reduce distribution size.

### Available Models

| Model | Type | Size | Description |
|-------|------|------|-------------|
| **sherpa-onnx-paraformer-zh-int8** | ASR | ~80 MB | Chinese speech recognition (INT8 quantized) |
| **sherpa-onnx-vits-zh-ll** | TTS (zh) | ~150 MB | Chinese TTS with 5 voice options |
| **vits-melo-tts-zh_en** | TTS (zh_en) | ~200 MB | Chinese-English mixed TTS |

### Download Models

#### Method 1: Using Download Script (Recommended)

```bash
# Download default models (ASR + Chinese TTS)
python download_models.py

# Download ASR model only
python download_models.py --asr

# Download TTS model (Chinese by default)
python download_models.py --tts

# Download Chinese TTS model
python download_models.py --tts zh

# Download Chinese-English TTS model
python download_models.py --tts zh_en

# Download all models
python download_models.py --all

# Check downloaded models
python download_models.py --check

# List available models
python download_models.py --list
```

#### Method 2: Auto-Download on First Use

When you first use voice features, the program will automatically download models if:
- `ASR_AUTO_DOWNLOAD=true` (default)
- `TTS_AUTO_DOWNLOAD=true` (default)

#### Method 3: Manual Download

Download from GitHub and extract to `PersonalData/model/`:
- ASR: https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-paraformer-zh-int8-2025-10-07.tar.bz2
- TTS (zh): https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/sherpa-onnx-vits-zh-ll.tar.bz2
- TTS (zh_en): https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-melo-tts-zh_en.tar.bz2

### Model Storage Location

- **Development mode**: `PersonalData/model/`
- **Bundled exe**: `%APPDATA%/OpenPersonalAgent/model/`

### Detailed Documentation

See [MODEL_DOWNLOAD.md](./MODEL_DOWNLOAD.md) for:
- Complete model introduction
- Configuration options
- Voice selection guide
- FAQ and troubleshooting

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

### Skill Memory File (Optional)
Create `skill_memory.md` in the Skill package to record execution experiences:
```markdown
# Execution Experiences

## 2024-05-27 - Successful Attempt
- Problem: XYZ didn't work
- Solution: Did ABC instead
- Result: Success!

## 2024-05-26 - Failed Attempt
- Problem: Something went wrong
- Root cause: Missing dependency
```

The `load_skill_memory` tool will retrieve this content, optionally filtered by query.

### Directory Convention
```
my_skill/                # Skill package directory (first-level subfolder)
├── SKILL.md             # Main document (preferred) or my_skill.md
├── skill_memory.md      # Optional: execution experiences
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
✅ **Memory Recording**: Record important lessons in skill_memory.md

---

## 🔍 Advanced Features

### Token Economy
- First turn only injects **Skill catalog summary** (lightweight)
- Full documents loaded only after `select_skill`
- Effectively controls context length and cost
- Token usage tracking optional

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

### Path Manager Architecture
```python
from resource_path import paths

paths.is_frozen              # True if running as bundled exe
paths.project_root           # Project root (dev) or exe dir (bundled)
paths.user_data_dir          # %APPDATA%/OpenPersonalAgent (bundled) or project root (dev)
paths.personal_data_dir      # PersonalData directory (always)
paths.get_skills_dir()       # Skills directory
paths.get_log_dir()          # Logs directory
paths.get_venv_dir()         # Virtual environment directory
paths.get_bundled_resource() # Read-only bundled resources
```

---

## ❓ FAQ

**Q: How to add new Skills?**
A: Create a new folder under `PersonalData/Skills/`, write an `.md` document. Restart or call `reload_skills()` to take effect.

**Q: What if dangerous commands are falsely blocked?**
A: Adjust via `.env` config using `DANGEROUS_COMMAND_PREFIXES` and `DANGEROUS_COMMAND_CONTAINS`, or modify `_is_dangerous_command()` in `skill_agent.py`.

**Q: Which LLM backends are supported?**
A: Any OpenAI API-compatible backend (configured via `OPENAI_BASE_URL`). Built-in support: GLM, Qwen, Gemma series.

**Q: How to export session records?**
A: Session data stored in SQLite database (`PersonalData/data/app.db`), can query directly or use export function in UI.

**Q: How to install Skill dependencies?**
A: When executing a Skill with missing dependencies, the system will automatically prompt user to confirm installation. Dependencies are installed in the isolated `PersonalData/venv`.

**Q: Where is my data when running the bundled exe?**
A: In `%APPDATA%/OpenPersonalAgent/`, including Skills, logs, database, and virtual environment. Config auto-copied from bundled resources on first run.

**Q: What's the difference between the legacy agent.py and skill_agent.py?**
A: `agent.py` is a screenshot-based desktop automation agent (legacy). `skill_agent.py` is the modern Skill-First architecture used by the main UI.

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

### v3.0.0 (Current Version)
- ✨ Added voice recording and transcription module (recorder.py) with Whisper integration
- ✨ Added floating ball widget for quick access and recording
- ✨ Added floating chat window for compact conversations
- ✨ Added text-to-speech (TTS) module with Piper engine
- ✨ Added two new built-in Skills: Meeting Minutes Generator and Scheduled Task Guide
- ✨ Added Skills/ directory for built-in Skills (version controlled)
- ✨ Added PersonalData/records/ directory for audio recordings
- ✨ Added PersonalData/models/ directory for local model files
- ✨ Added Whisper model download and management functionality
- ✨ Added TTS control UI component
- ✨ Enhanced recorder with faster-whisper support
- ✨ Added new configuration options for recording and TTS
- ✨ Added sounddevice, numpy, faster-whisper dependencies
- 🐛 Fixed multiple UI and stability issues

### v2.2.0
- ✨ Added WeChat Official Account Article Generation Skill (id: 100)
- ✨ Added token usage tracking with UI display
- ✨ Added memory compaction mechanism with configurable threshold
- ✨ Added duplicate tool call detection to prevent loops
- ✨ Added copy button for message types with configurable types
- ✨ Added jieba Chinese text segmentation for better FTS5 search
- ✨ Added configurable dangerous command detection rules via env
- ✨ Added memory migration system for seamless upgrades
- ✨ Enhanced memory search with score threshold configuration
- ✨ Added pygetwindow dependency for window management
- ✨ Enhanced path manager with unified dev/bundled handling
- ✨ Added comprehensive logging system with file rotation
- ✨ Added separate Skill visibility management (skill_agent_preferences.py)
- 🐛 Fixed multiple stability and UI issues

### v2.1.0
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
