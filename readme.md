# OpenPersonalAgent · SkillAgent

[中文版readme](./readme_CN.md)

## Screenshots

The following images are from the SkillAgent desktop UI (`ui_skill_agent`). Source files live under `doc/` in this repository.

![SkillAgent UI screenshot 1](doc/img.png)

![SkillAgent UI screenshot 2](doc/img_1.png)

![SkillAgent UI screenshot 3](doc/img_2.png)

![SkillAgent UI screenshot 4](doc/img_3.png)

---

A **SkillAgent** built on LLM tool calling: business rules live as Skill documents on disk. The agent **loads them on demand**, **combines multiple Skills** as constraints, and uses **atomic tools** inside a bounded workspace for file I/O and optional desktop automation.

---

## Overview

| Layer | Role |
|--------|------|
| **Skill tree & registry** | Scan the Skills root, parse metadata and body for catalog text and `select_skill` loads. |
| **Skill control tools** | `select_skill` / `finish`: pull full Skill text, or end the turn with a user-facing message. |
| **Atomic tools** | `read_text_file` / `write_text_file` / `list_directory` / `execute_desktop_action`: all run through `ToolContext(work_dir)`. |

The system prompt only includes a **Skill catalog summary**; full instructions enter the conversation after `select_skill`, then alternate with atomic tools until `finish`.

---

## How Skills are loaded

1. **Layout** (`skill/loader.py`)  
   - Each **top-level subdirectory** under the Skills root is one Skill **package**.  
   - Main doc resolution: prefer `<folder_name>.md`, otherwise the first `.md` in that directory (lexicographic).  
   - Standalone `.md` / `.markdown` / `.txt` at the repo root of the Skills tree are still supported (legacy flat layout).

2. **Metadata**  
   - Optional simple front matter between `---` lines (no PyYAML): `id` / `skill_id`, `name`, `description`, etc.  
   - Parsed into `SkillDefinition` (`skill/types.py`), indexed by `SkillRegistry` (`skill/registry.py`).

3. **Runtime**  
   - `SkillAgent` constructs `SkillRegistry(skills_dir)`; `reload_skills()` refreshes from disk.  
   - Catalog text from `build_skills_catalog_text` includes each Skill’s id, name, description, and a **`dir`** hint (relative path) so the model knows where the package lives.

---

## How Skills are executed

- **Main loop** (`skill_agent.py`): `complete_with_tools` → parse tool call → `_dispatch`.  
- **`select_skill` / `finish`** → `execute_skill_control_tool` (`skill/execution.py`).  
- **Any other name** → `execute_atomic_tool` (`base_tool/dispatch.py`).

After a successful `select_skill`, **all Skill bodies loaded in this session** are merged into an extra user message. Convention: **multiple Skills apply together**; on conflict, prefer the more specific rule or **later-loaded** text (as stated in the system prompt).

---

## Composing and chaining Skills

- **Repeated `select_skill`**: load several `skill_id`s in one task; `active_skill_text` / `active_skill_ids` accumulate—**later loads do not replace earlier ones**.  
- **Deduplication**: selecting the same `skill_id` again returns the cached body without appending twice (`skill/execution.py`).  
- **Cross-Skill workflows**: Markdown can say “also need Skill X”; the system prompt nudges the model to `select_skill` again, e.g. **workflow A + policy B** without one giant prompt.

This keeps large policies modular and composable instead of a single monolithic system string.

---

## Skills → atomic tools

Atomic tools are declared in `base_tool/definitions.py` and executed with one `ToolContext`:

- **Files & dirs**: paths are **relative to `work_dir`**; read, write, list.  
- **Desktop**: `execute_desktop_action` takes a **JSON string for a single action**, passed to an optional `Executor` (e.g. `Executor(self.work_dir)` in the UI).

The system prompt states that if a Skill references files by paths relative to its package, atomic read/write should use paths **prefixed with that Skill’s `dir`**, so the model does not confuse workspace root with the Skill package folder.

---

## Workspace sandboxing

`base_tool/dispatch.py` uses `_resolve_safe` for all file paths:

- Resolve under **`Path(work_dir).resolve()`**.  
- If resolution escapes the workspace (e.g. `../`), it fails with **path must stay inside the working directory**.

Effects:

- Read/write/list are confined to a **configured `work_dir`** (e.g. `config.WORKER_DIR` in the UI), reducing risk of touching arbitrary system or home paths.  
- **Skill definitions** (`SKILLS_DIR` under the worker tree by config) stay conceptually separate from **runtime artifacts** the agent creates under `work_dir`.

Each Skill also lives in its **own top-level folder**, so attachments, templates, and the main `.md` stay together for versioning and reuse.

---

## Other benefits (short list)

- **Token-aware context**: long bodies load only after `select_skill`; the first turn stays a compact catalog.  
- **Human-editable rules**: Markdown + light front matter; low barrier for non-developers.  
- **Clear separation**: control plane (Skills) vs. execution plane (atomic tools), easier to trace what the model decided vs. what it did.  
- **Step cap**: `SKILL_AGENT_MAX_STEPS` (from env via `config.py`) bounds tool loops.  
- **Observability**: `run(..., log_callback=...)` can log reasoning snippets, tool calls, full Skill loads, and truncated atomic-tool output (the Qt UI styles these by message type).

---

## Conversation persistence and Skill visibility

- **Optional `Memory`**: when `memory` and `conversation_id` are set, `run` rebuilds history (without stale system rows), regenerates system from the current catalog, and persists tool turns and injected Skill bodies for follow-up turns and UI restore.  
- **Desktop default**: `ui_skill_agent` wires `SqliteMemory` (`config.DEFAULT_SKILL_AGENT_USER`), multi-tab conversations (`start_new_conversation` / `set_conversation_id`), and DB-backed history.  
- **Disabling Skills**: `skill_agent_preferences.load_disabled_skill_ids()` reads `skill_agent_disabled_skills.json` at the project root; disabled ids are omitted from the catalog and cannot be selected. The in-app settings dialog edits this set.

---

## Configuration (examples)

Via `.env.dev` and `config.py`, typical keys include:

- `WORKER_DIR` — workspace root for atomic tools.  
- `SKILLS_DIR` — Skills root relative to the worker directory.  
- `SKILL_AGENT_MAX_STEPS` — max tool steps per user turn.  
- `OPENAI_*` / `MODEL_NAME` — API and model.

## Entry point

`main.py` currently starts the SkillAgent UI (`ui_skill_agent`), which constructs `SkillAgent(work_dir, executor=Executor(work_dir), memory=SqliteMemory(...), username=...)` and runs `run` on a worker thread while updating the chat / log views.

**Note:** `skills_auto_matched_for_query` and `SKILL_AGENT_AUTO_LOAD` exist in `skill/processing.py` and `config.py`, but **`SkillAgent.run` does not call them yet**. Treat “auto-inject Skills from the user query” as future work until the main loop wires that in.

---

