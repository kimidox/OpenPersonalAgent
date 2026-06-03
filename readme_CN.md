# OpenPersonalAgent · SkillAgent

[English README](./readme.md)

## 项目简介

OpenPersonalAgent 是一个**基于大语言模型工具调用的智能代理系统（SkillAgent）**，采用创新的 **"Skill-First" 架构设计**：

- 📋 **业务规则即文档**：将业务规范写成磁盘上的 Markdown Skill 文档
- 🔧 **按需动态加载**：Agent 根据用户需求智能选择并加载相关 Skills
- 🧩 **多Skill组合执行**：支持在同一任务中组合多条 Skill 约束
- ⚡ **原子命令执行**：通过受限工作区中的工具完成文件操作和桌面自动化
- 🤖 **多模型支持**：支持 GLM、Qwen、Gemma 等多种大语言模型
- 🏗️ **虚拟环境隔离**：自动创建和管理 venv，安全处理依赖
- 📝 **长期记忆系统**：使用 jieba 中文分词的持久化用户记忆和语义搜索
- 📄 **文档解析**：支持解析多种文件格式（PDF、Word、Excel、Markdown、文本、JSON）
- 📅 **定时任务**：创建和管理定时任务，支持通知或触发智能体对话
- 🔔 **通知系统**：系统托盘通知和浮动提示窗口
- 🚀 **Windows自启动**：启用/禁用Windows登录时自动启动
- ⚙️ **多配置组管理**：管理多个LLM配置组，支持自动故障转移
- 📎 **文件上传与预览**：在聊天界面中直接上传和解析文档
- 🎨 **后台模式**：在后台运行，仅显示系统托盘图标
- 🛠️ **工具目录渐进式披露**：按需加载工具定义以节省token
- 💾 **内存优化**：智能内存管理，支持可配置的消息保留
- 🎙️ **语音录制与转写**：使用 sounddevice 录制音频，通过本地 Whisper 模型（faster-whisper）转写
- 🎭 **悬浮球**：桌面悬浮组件，用于快速访问、录制和后台操作
- 🔊 **文本转语音（TTS）**：使用 Piper 引擎的本地文本转语音合成
- 📋 **内置技能目录**：Skills/ 目录提供系统内置技能（受版本控制），用户技能在 PersonalData/Skills/

---

## ✨ 核心特性

### 1. 智能Skill系统

| 层次 | 功能 | 说明 |
|------|------|------|
| **Skill注册表** | 扫描Skills目录，解析元数据与正文 | 支持热更新 `reload_skills()` |
| **控制工具** | `select_skill` / `finish` / `ask_user` / `load_skill_memory` | 加载Skills、结束会话、询问用户、加载执行记忆 |
| **原子工具** | `run_command` / `file_operation` / `edit` / `read_memory` / `write_memory` | 统一通过 `ToolContext(work_dir)` 执行 |

### 2. 安全执行机制

- ✅ **工作目录隔离**：所有文件操作限制在 `work_dir` 内，防止路径穿越攻击
- ✅ **虚拟环境**：在 `PersonalData/venv` 自动创建 venv，所有 Python 命令隔离执行
- ✅ **危险命令检测**：自动识别 `del`、`rmdir`、`>` 等危险操作并要求用户确认
- ✅ **包安装确认**：检测到 pip/npm 等包安装命令时，需用户确认后执行
- ✅ **Skill依赖管理**：自动扫描 Skill 包的 requirements.txt，提示用户安装依赖
- ✅ **步数上限保护**：`SKILL_AGENT_MAX_STEPS`（默认50步）防止无限循环
- ✅ **写入操作监控**：自动检测重复写入并智能结束任务
- ✅ **重复调用检测**：通过检测重复工具调用防止无限循环

### 3. 多模型支持

项目支持多种大语言模型后端：

| 模型类型 | 模型名称示例 | 特点 |
|---------|-------------|------|
| **GLM系列** | glm-5, glm-4 | 智谱AI出品，支持深度思考 |
| **Qwen系列** | qwen3.5, qwen-turbo | 阿里云通义千问系列 |
| **Gemma系列** | gemma-2, gemma-7b | Google开源模型 |
| **其他兼容模型** | gpt-4, claude等 | 兼容OpenAI API格式 |

### 4. 智能记忆系统

- ✅ **Skill执行记忆**：记录执行过程中的经验教训（失败原因、修复方法、最佳实践），避免重复犯错
- ✅ **Skill记忆加载**：`load_skill_memory` 工具支持语义搜索相关经验
- ✅ **延迟加载**：Skill遇到困难时按需加载记忆内容
- ✅ **FTS5语义检索**：使用 jieba 中文分词的 SQLite FTS5 全文索引，优化中文搜索
- ✅ **异步总结**：后台线程执行经验总结，不阻塞主流程
- ✅ **长期记忆**：跨会话用户记忆，支持语义检索
- ✅ **记忆压缩**：达到阈值时自动压缩记忆
- ✅ **读写工具**：`read_memory` 和 `write_memory` 用于显式记忆管理

### 5. 动态系统提示词

- ✅ **占位符机制**：`{SKILL_CATALOG}`、`{ACTIVE_SKILLS}`、`{USER_MEMORY}` 等
- ✅ **动态构建**：每次LLM调用前重新构建系统提示词
- ✅ **Skill切换**：高效替换Skill内容，无需追加消息
- ✅ **记忆集成**：用户记忆和近期会话摘要自动注入

### 6. 模块化前端架构

- ✅ **组件化设计**：可复用UI组件（ChatBubble、MessageCard等）
- ✅ **状态管理**：集中管理会话状态、流式状态、UI状态
- ✅ **样式管理**：类型安全的样式常量，支持主题扩展
- ✅ **逻辑解耦**：消息处理和流式渲染独立模块
- ✅ **Token用量显示**：可选的UI Token使用量追踪

### 7. 路径与配置管理

- ✅ **统一路径管理器**：`resource_path.paths` 处理开发/打包环境路径
- ✅ **智能配置加载**：首次运行时 `.env` 自动复制到用户数据目录（打包模式）
- ✅ **数据目录隔离**：清晰分离打包资源和用户数据

### 8. 日志系统

- ✅ **双重输出**：控制台 + 滚动文件日志在 `PersonalData/logs/`
- ✅ **模块日志记录器**：每模块的日志适配器，更好的组织性
- ✅ **异常钩子**：全局异常处理和记录

### 9. 文档解析器

- ✅ **多种格式**：PDF、Word (DOCX)、Excel (XLSX)、Markdown、文本、JSON
- ✅ **工厂模式**：根据文件扩展名动态选择解析器
- ✅ **文件验证**：解析前验证文件
- ✅ **统一接口**：所有格式统一的 `ParseResult` 格式

### 10. 定时任务

- ✅ **灵活调度**：单次或重复（每天、每周、每月）
- ✅ **双执行模式**：仅通知或触发智能体对话
- ✅ **智能定时**：指定精确的触发时间
- ✅ **重复类型**：无、每天、每周、每月
- ✅ **历史追踪**：追踪已触发/待触发/已取消的任务状态

### 11. 通知系统

- ✅ **系统托盘通知**：原生 Windows 托盘通知
- ✅ **浮动提示窗口**：带有淡出动画的精美浮动提示
- ✅ **可配置时长**：自定义显示时长
- ✅ **点击关闭**：可提前关闭提示窗口
- ✅ **多种类型**：系统通知或浮动提示显示选项

### 12. 多配置组管理

- ✅ **多个配置组**：管理多个 LLM 配置组（模型、API Key、基础 URL 等）
- ✅ **自动故障转移**：失败时自动切换到下一配置
- ✅ **切换追踪**：配置切换事件历史记录
- ✅ **顺序调整**：上下移动配置组顺序
- ✅ **添加/删除**：创建新配置或删除未使用的配置
- ✅ **参数编辑**：编辑单个配置设置
- ✅ **重置默认**：从 .env 恢复默认配置

### 13. 文件上传与预览

- ✅ **拖放区域**：文件上传区域
- ✅ **多文件上传**：一次上传多个文件
- ✅ **进度条**：实时解析进度
- ✅ **文件预览**：快速预览已解析内容
- ✅ **数量限制**：可配置的最大上传文件数
- ✅ **解析器集成**：与文档解析器直接集成
- ✅ **错误处理**：解析错误显示和处理

### 14. 后台模式

- ✅ **托盘图标**：后台时显示系统托盘图标
- ✅ **自启动**：Windows 自启动使用后台模式
- ✅ **任务调度**：后台模式下定时任务仍然工作
- ✅ **窗口大小**：可配置的默认窗口尺寸

### 15. 内存优化

- ✅ **渐进式披露**：按需工具目录
- ✅ **后台保留**：后台模式下可配置的消息保留数量
- ✅ **延迟优化**：激活优化前的延迟
- ✅ **Token 经济**：仅加载必要工具，减少 token 消耗

### 16. Windows 自启动

- ✅ **基于注册表**：Windows 注册表自启动
- ✅ **启用/禁用**：在设置中切换自启动
- ✅ **命令行支持**：自启动时使用 --background 参数

### 17. 语音录制与转写

- ✅ **音频录制**：使用 sounddevice 录制音频
- ✅ **本地转写**：集成 faster-whisper 模型
- ✅ **模型管理**：下载/切换 Whisper 模型（tiny/base/small/medium/large）
- ✅ **录制管理**：保存录音到 PersonalData/records/
- ✅ **转写配置**：可配置语言、模型大小、设备、计算类型

### 18. 悬浮球组件

- ✅ **可拖动组件**：在桌面悬浮显示
- ✅ **悬浮聊天窗口**：可展开的迷你聊天界面
- ✅ **快速录制**：从悬浮球一键开始录制
- ✅ **上下文菜单**：访问主窗口、录制控制

### 19. 文本转语音（TTS）

- ✅ **本地合成**：Piper TTS 引擎
- ✅ **语音管理**：多种语音选项
- ✅ **音频播放**：集成音频播放器
- ✅ **合成配置**：可配置语速、音调、音量

---

## 📁 内置Skill示例

项目提供11个开箱即用的Skill示例，展示不同场景的应用：

### 1️⃣ 小说生成 (`id: 1`)
- **功能**：根据章节大纲自动生成小说内容
- **特性**：自动编号、剧情连贯性保持、字数控制（3000-5000字）
- **输出**：Markdown格式的章节文件

### 2️⃣ 聊天语气 (`id: 2`)
- **功能**：为AI回复添加个性化语气风格
- **特性**：音符符号、语气词、句式模板
- **场景**：角色扮演、个性化助手

### 3️⃣ 时间格式转换 (`id: 5`)
- **功能**：统一时间格式转换（日期时间 ↔ 时间戳）
- **特性**：支持时区配置、多种输入格式识别

### 4️⃣ Excel操作 (`id: 6`)
- **功能**：自动化Excel文件读取
- **集成**：Python脚本调用

### 5️⃣ DuckDuckGo搜索 (`id: 8`)
- **功能**：使用DuckDuckGo搜索引擎进行网页搜索
- **特性**：支持普通搜索、新闻搜索、图片搜索
- **输出**：自动获取搜索结果的详细网页内容

### 6️⃣ 百度搜索 (`id: 9`)
- **功能**：使用百度搜索引擎进行网页搜索
- **特性**：支持普通搜索、新闻搜索、图片搜索
- **输出**：自动获取搜索结果的详细网页内容
- **场景**：中文内容搜索

### 7️⃣ 基金查询 (`id: 88`)
- **功能**：使用akshare查询基金信息
- **特性**：基金基本信息、单位净值、历史数据、基金列表筛选
- **输出**：JSON格式的基金数据

### 8️⃣ 图片匹配测试 (`id: 7`)
- **功能**：屏幕截图、模板匹配、自动化点击
- **特性**：快捷键模拟、坐标点击、OpenCV模板匹配
- **场景**：桌面自动化测试

### 9️⃣ 微信公众号文章生成 (`id: 100`)
- **功能**：根据用户提供的主题生成微信公众号文章
- **特性**：结构化内容（标题、引言、正文章节、结论）、字数控制（1500-2000字）
- **输出**：Markdown格式的文章，可直接发布到微信平台

### 🔟 会议纪要生成 (`id: meeting_minutes_generator`)
- **功能**：将转写的音频/文本转换为结构清晰的会议纪要
- **特性**：会议概况、议题讨论、决策事项、带负责人和截止时间的行动项
- **输出**：格式良好的 Markdown 会议纪要

### 1️⃣1️⃣ 定时任务创建指南 (`id: scheduled_task_guide`)
- **功能**：指导用户创建定时任务，包含正确的执行类型和链路
- **特性**：执行类型判断（通知 vs 智能体对话）、执行链路生成、目标提取
- **场景**：创建重复提醒、自动化任务、定时智能体对话

---

## 🏗️ 技术架构

```
PersonalWindowGLM/
├── main.py                     # 程序入口
├── agent.py                    # 遗留桌面自动化代理（基于截图）
├── skill_agent.py              # 核心Agent逻辑
├── ui_skill_agent.py           # 桌面GUI界面（PySide6）
├── config.py                   # 配置管理
├── executor.py                 # 命令执行器
├── logger.py                   # 日志系统
├── resource_path.py            # 统一路径管理器（开发/打包）
├── skill_agent_preferences.py  # Skill可见性/禁用状态管理
├── scheduled_tasks.py          # 定时任务数据模型和管理
├── scheduler.py                # 任务调度引擎
├── notification.py             # 通知系统（系统托盘、浮动提示）
├── autostart.py                # Windows自启动管理
├── recorder.py                 # 语音录制与转写模块
├── PersonalWindowGLM.spec      # PyInstaller spec
├── PersonalWindowGLM_onefile.spec  # 单文件spec
├── build.bat                   # 构建脚本
├── base_tool/                  # 原子工具定义
│   ├── definitions.py          # 工具schema定义（所有控制/原子工具）
│   ├── dispatch.py             # 工具分发、安全验证、venv管理
│   └── context.py              # ToolContext实现
├── skill/                      # Skill加载与执行
│   ├── loader.py               # 文件扫描、解析、记忆加载
│   ├── registry.py             # Skill注册表
│   ├── execution.py            # 控制工具执行
│   ├── processing.py           # Skill处理工具
│   ├── memory_summarizer.py    # Skill记忆总结
│   └── types.py                # Skill类型定义
├── llm/                        # 大语言模型接口
│   ├── BaseChatModel.py        # 模型基类
│   ├── glm_chat_model.py       # GLM模型实现
│   ├── qwen_chat_model.py      # Qwen模型实现
│   ├── gemma_chat_model.py     # Gemma模型实现
│   ├── llm_config_manager.py   # 多LLM配置管理器，支持故障转移
│   └── token_usage.py          # Token使用量追踪
├── memory/                     # 会话持久化
│   ├── memory.py               # 内存管理接口
│   ├── sqlite_memory.py        # SQLite存储实现
│   ├── long_term_memory.py     # 长期记忆管理
│   ├── searcher.py             # 使用jieba的FTS5语义检索
│   ├── conversation.py         # 会话管理
│   ├── migration.py            # 记忆迁移系统
│   ├── message.py              # 消息模型
│   └── reindex_fts.py          # FTS索引重建
├── prompt/                     # 动态提示词管理
│   ├── dynamic_prompt.py       # 动态系统提示词构建
│   └── template.py             # 提示词模板定义
├── document_parser/            # 文档解析模块
│   ├── __init__.py             # 解析器导出和注册
│   ├── base_parser.py          # 抽象基解析器类
│   ├── models.py               # ParseResult数据模型
│   ├── parser_factory.py       # 解析器工厂，用于动态选择
│   ├── file_storage.py         # 文件存储工具
│   └── parsers/                # 格式特定解析器
│       ├── pdf_parser.py       # PDF文档解析器
│       ├── word_parser.py      # Word (DOCX) 解析器
│       ├── excel_parser.py     # Excel (XLSX) 解析器
│       ├── markdown_parser.py  # Markdown 解析器
│       ├── text_parser.py      # 纯文本解析器
│       └── json_parser.py      # JSON 解析器
├── tts/                        # 文本转语音模块
│   ├── __init__.py             # 模块导出
│   ├── tts_engine.py           # TTS引擎接口
│   ├── piper_engine.py         # Piper TTS引擎实现
│   ├── synthesizer.py          # 语音合成器
│   ├── audio_player.py         # 音频播放器
│   ├── voice_manager.py        # 语音管理器
│   └── tts_config.py           # TTS配置
├── ui/                         # 模块化前端
│   ├── components/             # 可复用UI组件
│   │   ├── chat_bubble.py      # 聊天气泡组件
│   │   ├── message_card.py     # 消息卡片组件
│   │   ├── chat_session_tab.py # 会话标签页
│   │   ├── await_user_card.py  # 等待用户确认卡片
│   │   ├── settings_dialog.py  # 设置对话框（含多配置组和任务）
│   │   ├── file_upload_area.py # 文件上传区域
│   │   ├── file_preview_card.py# 文件预览组件
│   │   ├── conversation_sidebar.py # 会话侧边栏
│   │   ├── conversation_list_item.py # 会话列表项
│   │   ├── tab_bar.py          # 标签栏组件
│   │   └── tts_control.py      # TTS控制组件
│   ├── views/                  # 页面视图
│   │   ├── main_window.py      # 主窗口
│   │   ├── floating_ball.py    # 悬浮球组件
│   │   ├── floating_chat_window.py # 悬浮聊天窗口
│   │   └── worker_thread.py    # 工作线程
│   ├── state/                  # 状态管理
│   │   ├── session_state.py    # 会话状态
│   │   ├── stream_state.py     # 流式状态
│   │   └── ui_state.py         # UI状态
│   ├── styles/                 # 样式管理
│   │   ├── color_scheme.py     # 配色方案
│   │   ├── style_manager.py    # 样式管理器
│   │   └── ui_skill_agent_styles.css # UI样式表
│   └── utils/                  # UI工具函数
│       ├── html_utils.py       # HTML工具
│       ├── markdown_utils.py   # Markdown工具
│       ├── message_handler.py  # 消息处理
│       ├── simple_stream_renderer.py # 简单流式渲染器
│       ├── text_utils.py       # 文本工具
│       ├── stream_renderer.py  # 流式渲染
│       ├── file_upload_manager.py # 文件上传管理器
│       └── file_upload_controller.py # 文件上传控制器
├── Skills/                     # 内置技能目录（受版本控制）
│   ├── meeting_minutes_generator/ # 会议纪要生成技能
│   └── scheduled_task_guide/   # 定时任务创建指南技能
└── PersonalData/               # 用户数据目录（gitignore）
    ├── Skills/                 # 用户Skill文档目录
    │   ├── DuckDuckGoSearch/
    │   ├── baiduSearch/
    │   ├── 基金查询/
    │   ├── excel操作/
    │   ├── 小说生成/
    │   ├── 时间格式转换/
    │   ├── 聊天语气/
    │   ├── 图片匹配测试/
    │   └── 微信公众号文章生成/
    ├── models/                 # 本地模型文件（Whisper、TTS）
    │   └── base/               # Whisper base模型示例
    ├── records/                # 录音文件目录
    ├── data/                   # 数据库文件（app.db）
    ├── logs/                   # 日志文件（app_YYYYMMDD.log）
    ├── venv/                   # 自动创建的虚拟环境
    ├── cache/                  # 缓存目录
    └── config/                 # 配置目录
```

---

## 🔄 Skill工作流程

### 加载机制
1. **目录扫描**：每个一级子文件夹视为一个Skill包
2. **主文档解析**：优先 `<文件夹名>.md` 或 `SKILL.md`，否则取首个 `.md`
3. **元数据提取**：解析 `---` 包裹的frontmatter（`id`、`name`、`description`）
4. **记忆文件检测**：查找 `skill_memory.md` 以获取执行经验
5. **运行时索引**：由 `SkillRegistry` 维护，支持热重载

### 执行流程
```
用户提问 → [系统提示: Skill目录摘要]
         ↓
    模型决策: select_skill(skill_id)
         ↓
    [强制6步加载流程]
    Step 1: 完整阅读主文档全部内容
    Step 2: 提取所有被反引号包裹的文件路径
    Step 3: 逐个读取引用文件（必须指定skill_id）
    Step 4: 执行scripts/下的脚本（如有）
    Step 5: 合并为最终上下文
    Step 6: 递归加载关联Skills
         ↓
    [上下文注入: 已加载的全部Skill全文]
         ↓
    [可选: load_skill_memory 获取过往经验]
         ↓
    执行原子工具 (run_command/file_operation/edit等)
         ↓
    finish(message) 返回结果
```

### 多Skill组合
- **累积加载**：多次 `select_skill` 不覆盖，而是合并
- **去重优化**：相同Skill不重复追加
- **冲突解决**：以更具体或后加载的规则为准
- **跨Skill协作**：文档内可声明依赖其他Skills

---

## 🛠️ 原子工具参考

### 控制工具
| 工具 | 用途 | 参数 |
|------|---------|-----------|
| `select_skill` | 加载Skill文档 | `skill_id`（必需） |
| `finish` | 完成任务 | `message`（必需） |
| `ask_user` | 询问用户信息/确认 | `question`（必需），`choices`（可选），`context`（可选） |
| `load_skill_memory` | 加载Skill执行记忆 | `skill_id`（必需），`query`（必需），`limit`（必需） |

### 文件操作
| 工具 | 用途 | 参数 |
|------|---------|-----------|
| `file_operation` | 读/写/删除/列出文件 | `action`（读/写/删除/列表，必需），`path`（必需），`content`（仅写模式），`skill_id`（可选） |
| `edit` | 精确文件编辑（搜索替换） | `path`（必需），`old_str`（必需），`new_str`（必需），`skill_id`（可选） |

### 命令执行
| 工具 | 用途 | 参数 |
|------|---------|-----------|
| `run_command` | 执行shell命令/脚本 | `command`（必需），`cwd`（必需），`skill_id`（可选），`timeout_sec`（可选，默认60，最大180） |

### 记忆操作
| 工具 | 用途 | 参数 |
|------|---------|-----------|
| `read_memory` | 读取长期记忆（语义搜索） | `query`（必需），`limit`（必需） |
| `write_memory` | 写入长期记忆 | `content`（必需），`mode`（可选，追加/覆盖，默认追加） |

---

## 🛡️ 安全设计详解

### 工作区沙箱
```python
# base_tool/dispatch.py - _resolve_safe()
- 所有路径解析为 Path(work_dir).resolve() 下的真实路径
- 禁止 ../ 路径穿越
- 错误提示："路径必须位于工作目录内"
```

### 虚拟环境隔离
```python
# base_tool/dispatch.py - _ensure_venv_exists()
- 首次使用时在 PersonalData/venv 自动创建venv
- 通过多种策略查找系统Python（跳过虚拟环境）
- 使用 get-pip.py 自动安装缺失的pip
- 所有Python命令使用venv的python.exe
- Skill依赖自动安装在venv中
```

### 危险命令拦截
```python
# skill_agent.py - _is_dangerous_command()
危险前缀: del, erase, rmdir, rd, copy, move, ren, rename, mkdir, md
危险特征: >, >>, set-content, remove-item, rm 等

触发动作:
→ 弹出确认对话框（"确认执行" / "取消"）
→ 用户取消则终止命令
→ 记录到会话历史
→ 通过 DANGEROUS_COMMAND_PREFIXES / DANGEROUS_COMMAND_CONTAINS 配置
```

### 包安装确认
```python
# skill_agent.py - _is_package_install_command()
支持的包管理器: pip, pip3, npm, yarn, pnpm, conda, cargo, gem, go, apt, choco, scoop, winget

触发动作:
→ 弹出确认对话框，显示即将安装的包名
→ 用户确认后执行安装
```

### Skill依赖自动检测
```python
# base_tool/dispatch.py - check_skill_dependencies()
- 自动扫描 Skill 包内的 requirements.txt
- 检测venv中是否已安装所需依赖
- 提示用户确认安装缺失的包
- 确认后自动安装
```

### 自动结束检测
- 监控最近N条命令（通过 REPEAT_DETECTION_WINDOW_SIZE 配置）
- 检测到重复成功写入 → 自动调用 `finish()`
- 防止无限写入循环
- 通过 MAX_CONSECUTIVE_REPEATS 配置

---

## 💾 会话持久化

### 多标签页支持
- **新建会话**：`start_new_conversation()` → 生成UUID
- **切换会话**：`set_conversation_id(id)`
- **历史列表**：`list_saved_conversations()`
- **自动标题**：第一条消息成为会话标题
- **DB存储**：SQLite `Conversations` 表

### 存储内容
- 完整对话历史（system/user/assistant/tool）
- 已加载的Skill ID列表
- 工具调用记录（含参数）
- 推理过程（reasoning_content）
- 消息元数据（时间戳、类型）

### Skill可见性控制
- **禁用机制**：`skill_agent_disabled_skills.json`
- **界面管理**：设置对话框可勾选启用/禁用
- **效果**：被禁用的Skill不在目录中显示，无法被选中
- **存储位置**：用户数据目录（打包模式）或项目根目录（开发模式）

---

## ⚙️ 配置说明

通过项目根目录（开发）或用户数据目录（打包）的 `.env` 文件配置：

```bash
# ===== LLM配置 =====
OPENAI_API_KEY=your-api-key
OPENAI_BASE_URL=https://api.example.com/v1
MODEL_NAME=gpt-4

# ===== 工作目录配置 =====
WORKER_DIR=PersonalData              # Agent工作区根目录
SKILLS_DIR=Skills                    # Skills相对路径

# ===== 执行限制 =====
SKILL_AGENT_MAX_STEPS=50             # 单轮最大工具调用次数
MAX_ITERATIONS=20                    # 遗留代理的最大迭代次数

# ===== UI选项 =====
SKILL_AGENT_UI_SHOW_TOOL_CALLS=true  # 是否显示工具调用详情
SKILL_AGENT_AUTO_LOAD=true           # 是否自动加载Skills
DEFAULT_SKILL_AGENT_USER=default_user
TOKEN_USAGE_ENABLED=true             # 启用Token使用量追踪
TOKEN_USAGE_SHOW_IN_UI=true          # 在UI中显示Token使用量
COPY_BUTTON_ENABLED_TYPES=user,assistant  # 为这些消息类型启用复制按钮

# ===== 截图配置 =====
SCREENSHOT_GRID_STEP_PX=32           # 截图网格步长

# ===== 记忆配置 =====
CONTEXT_WINDOW_SIZE=128000           # 上下文窗口大小限制
COMPACTION_THRESHOLD=0.8             # 记忆压缩阈值（0.0-1.0）
COMPACTION_KEEP_RECENT=10            # 压缩时保留N条最近消息
COMPACTION_ENABLED=true              # 启用记忆压缩
MEMORY_SEARCH_LIMIT=5                # 最大记忆搜索结果
MEMORY_MIN_SCORE=0.0                 # 最小记忆搜索分数（0.0-1.0）
MEMORY_SEARCH_ENABLED=true           # 启用记忆搜索

# ===== 工具调用去重 =====
TOOL_CALL_DEDUPLICATION_ENABLED=true # 启用重复工具调用检测
MAX_CONSECUTIVE_REPEATS=3            # 警告前的最大连续重复次数
REPEAT_DETECTION_WINDOW_SIZE=10      # 重复检测窗口大小

# ===== 危险命令检测 =====
DANGEROUS_COMMAND_CHECK_ENABLED=true # 启用危险命令检测
DANGEROUS_COMMAND_PREFIXES=del ,erase ,rmdir ,rd ,copy ,move ,ren ,rename ,mkdir ,md
DANGEROUS_COMMAND_CONTAINS= > , >> , >, >>, set-content , set-content-, add-content , add-content-, out-file , out-file-, new-item , new-item-, remove-item , remove-item-, rm

# ===== 窗口大小配置 =====
WINDOW_WIDTH=780                    # 默认窗口宽度
WINDOW_HEIGHT=620                   # 默认窗口高度

# ===== 定时任务配置 =====
SCHEDULED_TASK_SHOW_WINDOW=false    # 任务触发智能体对话时显示主窗口

# ===== 工具目录渐进式披露 =====
USE_TOOL_CATALOG=true               # 启用工具目录（渐进式披露）

# ===== 内存优化 =====
MEMORY_OPTIMIZATION_ENABLED=true    # 启用内存优化
MEMORY_OPTIMIZATION_DELAY_SECONDS=30 # 激活优化前的延迟（秒）
BACKGROUND_KEEP_MESSAGES_COUNT=50   # 后台模式下保留的消息数量

# ===== 录音配置 =====
RECORDING_SAMPLE_RATE=16000         # 录制采样率（Hz）
RECORDING_CHANNELS=1                # 录制通道数（1=单声道，2=立体声）
RECORDING_DTYPE=int16               # 录制数据类型
RECORDING_TRANSCRIPTION_LANGUAGE=zh # 转写语言代码
WHISPER_MODEL_SIZE=base             # Whisper 模型大小（tiny/base/small/medium/large）
WHISPER_DEVICE=cpu                  # Whisper 设备（cpu，cuda）
WHISPER_COMPUTE_TYPE=int8           # Whisper 计算类型（int8，float16，float32）

# ===== TTS配置 =====
TTS_ENABLED=true                    # 启用文本转语音
TTS_ENGINE=piper                    # 使用的TTS引擎
TTS_VOICE=default                   # 默认TTS语音
TTS_SPEED=1.0                       # TTS语速倍率
TTS_PITCH=1.0                       # TTS音调倍率
TTS_VOLUME=1.0                      # TTS音量倍率
```

---

## 🚀 快速开始

### 环境要求
- Python 3.11+
- Windows（主要支持，跨平台代码库）

### 安装依赖
```bash
pip install -r requirements.txt
```

主要依赖：
- PySide6 >= 6.5.0（GUI界面）
- openai >= 1.0.0（LLM调用）
- sqlalchemy >= 2.0.0（数据库）
- pydantic >= 2.0.0（数据验证）
- Pillow >= 9.0.0（图像处理）
- opencv-python >= 4.8.0（图像匹配）
- pyautogui >= 0.9.54（桌面自动化）
- pygetwindow >= 0.0.9（窗口管理）
- pandas ~= 3.0.1（数据处理）
- jieba >= 0.42.1（中文分词）
- sounddevice >= 0.4.6（音频录制）
- numpy >= 1.20.0（音频处理）
- faster-whisper >= 1.0.0（语音转写）

### 运行程序
```bash
# 方式1：直接运行
python main.py

# 方式2：打包为exe（见build.bat）
# 打包后的exe使用 %APPDATA%/OpenPersonalAgent/ 存储用户数据
```

### 首次使用
1. 复制 `.env.example` 为 `.env`（如不存在）
2. 填写API密钥和模型配置
3. 运行 `main.py` 启动界面
4. 虚拟环境自动创建在 `PersonalData/venv/`
5. 在左侧Skill列表查看可用技能
6. 输入问题开始对话

---

## 🎨 界面预览

![SkillAgent 主界面](doc/img_1.png)

![设置对话框](doc/img_2.png)

---

## 📝 开发自定义Skills

### Skill文档结构
```markdown
---
id: 100                          # 唯一标识（数字或字符串）
name: 我的自定义Skill            # 显示名称
description: 简短功能描述        # 目录中显示
---

## 功能说明
详细描述Skill的功能和使用场景...

## 执行流程
1. 第一步...
2. 第二步...

## 调用命令
`python scripts/my_script.py "{参数}"`

## 依赖（可选）
在 Skill 包内创建 requirements.txt：
```
ddgs
requests
```

## 注意事项
- 约束条件1
- 约束条件2
```

### Skill记忆文件（可选）
在Skill包内创建 `skill_memory.md` 记录执行经验：
```markdown
# 执行经验

## 2024-05-27 - 成功尝试
- 问题：XYZ无法工作
- 解决方案：改为ABC
- 结果：成功！

## 2024-05-26 - 失败尝试
- 问题：出现问题
- 根因：缺少依赖
```

`load_skill_memory` 工具将检索此内容，可选择按query筛选。

### 目录规范
```
my_skill/                # Skill包目录（一级子文件夹）
├── SKILL.md             # 主文档（优先）或 my_skill.md
├── skill_memory.md      # 可选：执行经验
├── scripts/             # 可选：脚本文件
│   └── my_script.py
├── example/             # 可选：示例文件
│   └── demo.md
├── output/              # 可选：输出目录
└── requirements.txt     # 可选：Python依赖
```

### 最佳实践
✅ **明确步骤**：使用有序列表定义清晰的执行流程  
✅ **参数说明**：详细描述输入参数和格式  
✅ **约束声明**：用【强制约束】标记必须遵守的规则  
✅ **错误处理**：说明异常情况的处理方式  
✅ **引用资源**：使用反引号标注包内文件路径 `` `./example/file.md` ``  
✅ **依赖声明**：在 requirements.txt 中声明所需的Python包
✅ **记忆记录**：在 skill_memory.md 中记录重要经验

---

## 🔍 高级特性

### Token经济性
- 首轮仅注入 **Skill目录摘要**（轻量）
- 完整文档仅在 `select_skill` 后加载
- 有效控制上下文长度和成本
- Token使用量追踪可选

### 可观测性
```python
# 日志回调接口
run(user_query, log_callback=lambda msg, type: print(f"[{type}] {msg}"))

# 消息类型:
# - "think": 模型推理过程
# - "tool": 工具调用
# - "doc": Skill文档加载
# - "base_tool": 命令执行结果
# - "assistant": 最终回复
# - "await_user": 等待用户确认
```

### 递归Skill加载
Skill文档可引用其他Skill文件：
- 主文档中的 `` `./path/to/file.md` `` 会被自动提取
- 每个提取到的文件都会被读取
- 如发现新的Skill引用，继续递归加载
- 直到无新文件为止

### 路径管理器架构
```python
from resource_path import paths

paths.is_frozen              # 如果作为打包exe运行为True
paths.project_root           # 项目根目录（开发）或exe目录（打包）
paths.user_data_dir          # %APPDATA%/OpenPersonalAgent（打包）或项目根目录（开发）
paths.personal_data_dir      # PersonalData目录（始终）
paths.get_skills_dir()       # Skills目录
paths.get_log_dir()          # 日志目录
paths.get_venv_dir()         # 虚拟环境目录
paths.get_bundled_resource() # 只读打包资源
```

---

## ❓ 常见问题

**Q: 如何添加新的Skill？**
A: 在 `PersonalData/Skills/` 下创建新文件夹，编写 `.md` 文档。重启或调用 `reload_skills()` 生效。

**Q: 危险命令被误拦怎么办？**
A: 通过 `.env` 配置的 `DANGEROUS_COMMAND_PREFIXES` 和 `DANGEROUS_COMMAND_CONTAINS` 调整，或修改 `skill_agent.py` 中的 `_is_dangerous_command()`。

**Q: 支持哪些LLM后端？**
A: 兼容OpenAI API格式即可（通过 `OPENAI_BASE_URL` 配置）。已内置支持：GLM、Qwen、Gemma系列。

**Q: 如何导出会话记录？**
A: 会话数据存储在SQLite数据库（`PersonalData/data/app.db`），可直接查询或通过UI的导出功能。

**Q: Skill的依赖包如何安装？**
A: 当执行Skill时检测到缺失依赖，系统会自动提示用户确认安装。依赖安装在隔离的 `PersonalData/venv` 中。

**Q: 运行打包的exe时我的数据在哪里？**
A: 在 `%APPDATA%/OpenPersonalAgent/` 中，包括Skills、日志、数据库和虚拟环境。首次运行时配置从打包资源自动复制。

**Q: 遗留的agent.py和skill_agent.py有什么区别？**
A: `agent.py` 是基于截图的桌面自动化代理（遗留）。`skill_agent.py` 是主UI使用的现代Skill-First架构。

---

## 📄 许可证

MIT License

---

## 🤝 贡献指南

欢迎提交Issue和Pull Request！

1. Fork本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启Pull Request

---

## 更新日志

### v3.0.0 (当前版本)
- ✨ 新增语音录制与转写模块（recorder.py），集成Whisper
- ✨ 新增悬浮球组件，用于快速访问和录制
- ✨ 新增悬浮聊天窗口，提供紧凑型会话
- ✨ 新增文本转语音（TTS）模块，集成Piper引擎
- ✨ 新增两个内置技能：会议纪要生成和定时任务创建指南
- ✨ 新增Skills/目录用于内置技能（受版本控制）
- ✨ 新增PersonalData/records/目录用于音频录制
- ✨ 新增PersonalData/models/目录用于本地模型文件
- ✨ 新增Whisper模型下载与管理功能
- ✨ 新增TTS控制UI组件
- ✨ 增强录制功能，支持faster-whisper
- ✨ 新增录制和TTS的新配置选项
- ✨ 新增sounddevice、numpy、faster-whisper依赖
- 🐛 修复多个UI和稳定性问题

### v2.2.0
- ✨ 新增微信公众号文章生成Skill（id: 100）
- ✨ 新增Token使用量追踪及UI显示
- ✨ 新增记忆压缩机制，支持可配置阈值
- ✨ 新增重复工具调用检测，防止循环
- ✨ 新增消息类型复制按钮，支持可配置类型
- ✨ 新增使用jieba中文分词，优化FTS5搜索
- ✨ 新增通过env配置的危险命令检测规则
- ✨ 新增记忆迁移系统，实现无缝升级
- ✨ 增强记忆搜索，支持分数阈值配置
- ✨ 新增pygetwindow依赖用于窗口管理
- ✨ 增强路径管理器，统一开发/打包处理
- ✨ 新增全面日志系统，带文件滚动
- ✨ 新增独立Skill可见性管理（skill_agent_preferences.py）
- 🐛 修复多个稳定性和UI问题

### v2.1.0
- ✨ 新增百度搜索Skill，支持中文内容搜索
- ✨ 新增基金查询Skill，集成akshare基金数据查询
- ✨ 新增Skill执行记忆系统，记录经验教训避免重复犯错
- ✨ 新增FTS5语义检索，支持记忆内容相关性搜索
- ✨ 新增动态系统提示词，支持占位符机制
- ✨ 新增Skill记忆延迟加载，按需获取经验内容
- ✨ 新增异步Skill总结，后台线程执行不阻塞主流程
- ✨ 重构前端架构，采用模块化设计
- 🔧 优化记忆系统，采用SQLite FTS5索引存储
- 🔧 改进长期记忆，支持语义检索

### v2.0.0
- ✨ 重构为Skill-First架构
- ✨ 新增多Skill组合执行
- ✨ 新增危险命令检测与确认机制
- ✨ 新增包安装确认机制
- ✨ 新增Skill依赖自动检测与安装
- ✨ 新增自动结束检测
- ✨ 新增会话持久化与多标签页
- ✨ 新增多模型支持（GLM、Qwen、Gemma）
- 🔧 优化工作区沙箱安全性
- 🐛 修复多个稳定性问题

---

**⭐ 如果这个项目对你有帮助，请给一个Star支持！**
