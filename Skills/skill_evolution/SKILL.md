---
id: skill_evolution
name: skill进化
description: 优化skill、进化skill、改进skill、升级skill、skill优化、skill进化、skill改进、skill升级、经验总结、经验优化、根据经验改进skill
auto_load: false
---

## 功能说明

本 Skill 用于根据非内置 Skill 的历史执行经验，自动总结问题模式、成功率、改进建议，并优化修改对应的 Skill 文档（SKILL.md）。

### 核心能力

1. **经验检索**：从数据库中检索目标 Skill 的所有历史执行经验
2. **模式分析**：分析错误模式、成功率和改进建议
3. **文档优化**：根据分析结果优化 Skill 文档，改进执行步骤、错误处理策略和注意事项
4. **安全保护**：内置 Skill 不可修改，仅优化用户自定义 Skill

---

## 关键约束

**【重要】执行 skill 进化时，必须遵守以下约束！**

### 1. 仅限用户自定义 Skill

- **内置 Skill（skill_type=builtin）不可修改**：如果目标 Skill 是内置 Skill，必须拒绝并提示用户
- **仅优化 skill_type=user 的 Skill**：只有用户自定义的 Skill 才可以被进化

### 2. 优化前必须备份

- **修改前先读取当前内容**：确保了解当前 Skill 的完整内容
- **优化是增量改进**：在原有内容基础上添加/修改，不要重写整个文档
- **保留原有结构**：YAML front matter 和核心执行流程必须保留

### 3. 经验不足时拒绝优化

- **无历史经验时不优化**：如果目标 Skill 没有执行经验记录，提示用户先多次执行该 Skill 积累经验
- **经验过少时谨慎优化**：少于 2 条经验时，仅提供建议而不自动修改

---

## 执行流程

### 步骤 1：确认目标 Skill

使用 `ask_user` 工具询问用户要优化哪个 Skill：

```
ask_user(question="请提供要优化的 Skill 的 ID 或名称：")
```

如果用户已在输入中指定了 Skill ID，跳过此步骤。

如果用户不清楚有哪些 Skill，可使用 `manage_skill` 列出所有用户自定义 Skill：

```
manage_skill(action="list")
```

### 步骤 2：检查 Skill 类型

使用 `manage_skill` 工具获取目标 Skill 的元信息：

```
manage_skill(action="get_info", skill_id="TARGET_SKILL_ID")
```

返回结果示例：
```json
{
  "id": "xxx",
  "name": "示例 Skill",
  "description": "这是一个示例",
  "skill_type": "user",
  "file_path": "PersonalData/Skills/xxx/SKILL.md"
}
```

- 如果 `skill_type` 为 `builtin`：调用 `finish` 返回"内置 Skill 不可修改，仅支持优化用户自定义 Skill"
- 如果返回"未找到 Skill"：调用 `finish` 返回"未找到指定 Skill"
- 如果 `skill_type` 为 `user`：继续下一步

### 步骤 3：检索历史执行经验

使用 `manage_skill` 工具检索目标 Skill 的所有执行经验：

```
manage_skill(action="get_memory", skill_id="TARGET_SKILL_ID", limit=20)
```

返回结果示例：
```json
[
  {
    "timestamp": "2026-07-23 10:00:00",
    "success": true,
    "error": null,
    "tips": "执行成功，建议添加超时处理"
  },
  {
    "timestamp": "2026-07-23 10:05:00",
    "success": false,
    "error": "路径不存在",
    "tips": "需要检查路径是否存在"
  }
]
```

分析返回的经验数据：
- 统计成功/失败次数
- 提取常见错误模式和修复方案
- 收集改进建议（tips）

### 步骤 4：读取当前 Skill 文档

使用 `select_skill` 加载目标 Skill 的当前内容：

```
select_skill(skill_id="TARGET_SKILL_ID")
```

返回结果为完整的 SKILL.md 内容（含 YAML front matter）。

### 步骤 5：生成优化方案

基于历史经验分析，生成结构化的优化方案：

1. **错误处理增强**：根据常见错误，在注意事项中添加预防措施
2. **执行步骤改进**：根据成功经验和失败教训，优化执行流程
3. **约束条件补充**：根据踩过的坑，添加新的约束条件
4. **最佳实践提炼**：将 tips 中的高价值建议融入文档

### 步骤 6：修改 Skill 文档

使用 `manage_skill` 工具的 edit 操作修改目标 Skill：

```
manage_skill(action="edit", skill_id="TARGET_SKILL_ID", content="OPTIMIZED_CONTENT")
```

**重要**：`content` 参数必须包含完整的 Skill 文档内容，包括 YAML front matter。

### 步骤 7：报告优化结果

调用 `finish` 返回优化结果摘要，包括：
- 优化了哪些内容
- 基于多少条经验记录
- 成功率统计
- 新增/修改了哪些章节

---

## 工具使用指南

### manage_skill（核心工具）

Skill 管理工具，支持以下操作：

| action | 说明 | 必需参数 |
|--------|------|----------|
| `list` | 列出所有用户自定义 Skill | 无 |
| `get_info` | 获取 Skill 元信息 | `skill_id` |
| `get_memory` | 检索历史执行经验 | `skill_id`, `limit`(可选) |
| `edit` | 编辑 Skill 文档 | `skill_id`, `content` |

**示例**：
```
# 列出所有用户自定义 Skill
manage_skill(action="list")

# 获取 Skill 信息
manage_skill(action="get_info", skill_id="my_skill")

# 检索执行经验
manage_skill(action="get_memory", skill_id="my_skill", limit=20)

# 编辑 Skill 文档
manage_skill(action="edit", skill_id="my_skill", content="---\nid: my_skill\n...")
```

### select_skill

加载指定 Skill 的完整文档。

**参数**：
- `skill_id`（必需）：要加载的 Skill 的 ID

**示例**：
```
select_skill(skill_id="TARGET_SKILL_ID")
```

### ask_user

向用户确认目标 Skill。

**参数**：
- `question`（必需）：要问的问题

**示例**：
```
ask_user(question="请提供要优化的 Skill 的 ID 或名称：")
```

### finish

完成优化后返回结果。

**参数**：
- `message`（必需）：优化结果摘要

**示例**：
```
finish(message="已完成 Skill「xxx」的优化，基于 N 条经验记录...")
```

---

## 完整执行示例

**用户任务**："优化工作周报生成 skill"

```
# 步骤 1：用户已指定目标，无需确认

# 步骤 2：检查 Skill 类型
manage_skill(action="get_info", skill_id="weekly_report")
# 返回：skill_type=user → 继续

# 步骤 3：检索历史执行经验
manage_skill(action="get_memory", skill_id="weekly_report", limit=20)
# 返回：5 条经验记录，3 条成功 2 条失败

# 步骤 4：读取当前 Skill 文档
select_skill(skill_id="weekly_report")
# 返回：当前 SKILL.md 内容

# 步骤 5：分析并生成优化方案
# 发现：常见错误是模板路径不存在 → 添加路径检查步骤
# 发现：用户经常忘记指定周报范围 → 添加默认值说明
# 发现：格式化偶尔失败 → 添加错误处理策略

# 步骤 6：修改 Skill 文档
manage_skill(action="edit", skill_id="weekly_report", content="完整的优化后内容...")
# 返回：✓ Skill 'weekly_report' 文档已更新

# 步骤 7：报告结果
finish(message="已完成 Skill「工作周报生成」的优化：基于 5 条经验记录（成功率 60%），新增路径检查步骤、添加默认值说明、补充错误处理策略")
```

---

## 注意事项

1. **仅优化用户自定义 Skill**：内置 Skill（如桌面自动化、会议纪要生成等）不可修改
2. **增量优化**：在原有内容基础上改进，不要重写整个文档
3. **保留 YAML front matter**：id、name 等元数据不可修改
4. **经验不足时不优化**：无经验或少于 2 条经验时，仅提供建议
5. **优化后需验证**：建议用户执行一次优化后的 Skill，验证改进效果
6. **多次进化**：Skill 可以多次进化，每次基于最新的执行经验