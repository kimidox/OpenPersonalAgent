# OpenPersonalAgent · SkillAgent

## 界面预览

下列截图为当前 SkillAgent 桌面端（`ui_skill_agent`）相关界面，资源位于仓库 `doc/` 目录。

![SkillAgent 界面截图 1](doc/img.png)

![SkillAgent 界面截图 2](doc/img_1.png)

![SkillAgent 界面截图 3](doc/img_2.png)

![SkillAgent 界面截图 4](doc/img_3.png)

---

基于大模型工具调用的 **SkillAgent**：把业务规范写成磁盘上的 Skill 文档，由 Agent **按需加载**、**组合多条 Skill** 约束，并通过 **原子工具** 在受限工作区内完成读写目录与桌面自动化等操作。

---

## 核心思路

| 层次 | 作用 |
|------|------|
| **Skill 目录与注册表** | 扫描 Skills 根目录，解析每个 Skill 的元数据与正文，供目录摘要与 `select_skill` 加载。 |
| **Skill 控制工具** | `select_skill` / `finish`：加载完整 Skill、结束回合并返回用户可见结果。 |
| **原子工具** | `read_text_file` / `write_text_file` / `list_directory` / `execute_desktop_action`：统一经 `ToolContext(work_dir)` 执行。 |

Agent 在系统提示中只看到 **Skill 列表摘要**；完整流程在模型调用 `select_skill` 后注入对话，再与原子工具交替执行，直到 `finish`。

---

## Skill 如何被加载

1. **目录约定**（`skill/loader.py`）  
   - Skills 根目录下每个 **一级子文件夹** 视为一个 Skill **包**。  
   - 包内主文档解析顺序：优先 `<文件夹名>.md`，否则取该目录下字典序第一个 `.md`。  
   - 兼容根目录平铺的独立 `.md` / `.markdown` / `.txt`。

2. **元数据**  
   - 支持可选的 `---` 包裹的简单前置块（无 PyYAML 依赖）：`id` / `skill_id`、`name`、`description` 等。  
   - 解析结果为 `SkillDefinition`（`skill/types.py`），由 `SkillRegistry` 索引（`skill/registry.py`）。

3. **运行时**  
   - `SkillAgent` 构造时创建 `SkillRegistry(skills_dir)`，可用 `reload_skills()` 热更新。  
   - 系统提示中的目录文本由 `build_skills_catalog_text` 生成，包含每个 Skill 的 `id`、`name`、`description` 及 **`dir`（相对路径提示）**，便于模型理解 Skill 包位置。

---

## Skill 如何被执行

- **主循环**（`skill_agent.py`）：`complete_with_tools` → 解析函数调用 → `_dispatch`。  
- **`select_skill` / `finish`** → `execute_skill_control_tool`（`skill/execution.py`）。  
- **其余名称** → `execute_atomic_tool`（`base_tool/dispatch.py`）。

成功 `select_skill` 后，会把 **当前会话已加载的全部 Skill 全文** 合并成一条用户侧消息追加进上下文，并约定：**多份 Skill 同时生效**；若有冲突，以更具体或 **后加载** 的说明为准（与系统提示文案一致）。

---

## Skill 之间的相互调用 / 组合

- **多次 `select_skill`**：同一轮任务可依次加载多个 `skill_id`；`active_skill_text` / `active_skill_ids` 累积，**不是后加载覆盖先加载**。  
- **去重**：同一 `skill_id` 再次 `select_skill` 时直接返回已缓存正文，不重复追加（`skill/execution.py`）。  
- **文档内协作**：Skill 的 Markdown 可写明「仍需其它 Skill」；系统提示引导模型再次 `select_skill`，实现 **流程 A + 约束 B** 的链式组合。  

这使复杂业务可以拆成多个小 Skill，由模型按任务动态组合，而不必把所有规则塞进单条超长 system prompt。

---

## Skill → 原子工具

原子工具在 `base_tool/definitions.py` 中声明，由同一套 `ToolContext` 执行：

- **文件与目录**：相对 `work_dir` 的路径；读写、列目录。  
- **桌面自动化**：`execute_desktop_action` 接收 **单个动作的 JSON 字符串**，交给可选的 `Executor`（例如 UI 中的 `Executor(self.work_dir)`）。

系统提示中约定：若 Skill 要求读取包内相对路径文件，应用原子工具读写，且 **路径需拼上当前 Skill 的 `dir`**，避免模型把工作区根目录与 Skill 包目录混淆。

---

## 操作空间与工作目录隔离（沙箱）

`base_tool/dispatch.py` 中 `_resolve_safe` 对所有文件类路径做校验：

- 解析为 **`Path(work_dir).resolve()` 下的真实路径**；  
- 若解析结果跳出工作区（如 `../`），抛出 **「路径必须位于工作目录内」**。

效果：

- Agent 的读写与列目录被限制在 **可配置的 `work_dir`**（例如 UI 里使用 `config.WORKER_DIR`），降低误删系统文件、乱写用户主目录的风险。  
- Skill **内容**与 **用户数据/产出** 在概念上分离：规范在 `SKILLS_DIR`（默认在 worker 目录下由配置指定），执行时的文件操作锚定在 `work_dir`。

此外，**每个 Skill 物理上独占一级子文件夹**，附件、模板与主 `.md` 同包，便于版本管理与复用。

---

## 其它设计上的优势（简要）

- **上下文经济**：首轮只注入目录摘要，长文档按需 `select_skill`，控制 token 与噪声。  
- **人机可读规范**：Skill 即 Markdown + 轻量 frontmatter，非程序员也可维护。  
- **工具面清晰**：控制面（Skill）与执行面（原子工具）分离，便于审计模型在「选规范」与「动手」上的行为。  
- **步数上限**：`SKILL_AGENT_MAX_STEPS`（默认来自环境配置）防止无限工具循环。  
- **可观测性**：`run(..., log_callback=...)` 可记录推理摘要、工具调用、Skill 全文加载与截断后的原子工具返回（Qt 界面按类型着色展示）。

---

## 会话持久化与 Skill 可见性

- **`Memory` 可选**：传入 `memory` 与 `conversation_id` 时，`run` 会在每轮前拼接历史消息（不含旧 system），并用当前 Skill 目录重新生成 system；工具轮次与「已加载 Skill」正文会写入持久化层，便于多轮对话与界面恢复。  
- **桌面端默认**：`ui_skill_agent` 使用 `SqliteMemory`（用户名为 `config.DEFAULT_SKILL_AGENT_USER`），支持多标签页会话（`start_new_conversation` / `set_conversation_id`）、从库中拉取历史消息等。  
- **禁用部分 Skill**：`skill_agent_preferences.load_disabled_skill_ids()` 读取项目根下的 `skill_agent_disabled_skills.json`；被禁用的 Skill 不会出现在目录摘要中，也无法被 `select_skill` 选中。设置界面可维护该列表。

---

## 配置与环境（示例）

通过 `.env.dev` 等（见 `config.py`）可配置例如：

- `WORKER_DIR`：Agent 工作区（原子工具路径锚点）。  
- `SKILLS_DIR`：相对 worker 的 Skills 根目录。  
- `SKILL_AGENT_MAX_STEPS`：单轮最大工具步数。  
- `OPENAI_*` / `MODEL_NAME`：模型与 API。

---

## 运行入口

主程序当前默认启动 SkillAgent 界面（`main.py` → `ui_skill_agent`）：内部构造 `SkillAgent(work_dir, executor=Executor(work_dir), memory=SqliteMemory(...), username=...)`，在独立线程中调用 `run` 并刷新聊天与日志视图。

**说明**：`skill/processing.py` 中的 `skills_auto_matched_for_query` 与配置项 `SKILL_AGENT_AUTO_LOAD` 已存在，但 **`SkillAgent.run` 当前未调用自动匹配**；自动按用户问题预注入 Skill 需在主循环中另行接线后再写入文档。

---


