---
id: 9
name: baiduSearch
description: 使用百度搜索引擎进行网页搜索，采用两阶段模式：先搜索获取摘要，再加载指定网页的详细内容
---

## 功能
本技能包含两个独立脚本：
- **`do_search.py`**：专注搜索，返回摘要列表并缓存结果
- **`fetch_page.py`**：专注加载，根据搜索缓存或直接 URL 获取网页详细内容

## 调用命令
**注意：参数之间用空格分隔**

### 搜索脚本（do_search.py）

**执行搜索，返回摘要列表和 session_id**
```
python scripts/do_search.py search {query} {max_results}
```

**查看所有有效会话**
```
python scripts/do_search.py list
```

### 加载脚本（fetch_page.py）

**根据 session 和索引加载指定网页详情**
```
python scripts/fetch_page.py fetch {session_id} {result_index}
```

**自动加载下一个未详查的网页**
```
python scripts/fetch_page.py next {session_id}
```

**直接加载任意 URL 的详情**
```
python scripts/fetch_page.py url {网址}
```

## 标准使用流程（大模型必读）

**第1步：搜索获取摘要**
```
python scripts/do_search.py search AI发展趋势 5
```
返回：摘要列表 + `session_id`（如 `a1b2c3d4-...`）

**第2步：浏览摘要，判断有价值的结果**
根据标题和摘要，决定需要加载哪些网页的详细内容

**第3步：逐个加载详情，逐个总结**
```
# 方式A：指定索引加载（从0开始）
python scripts/fetch_page.py fetch a1b2c3d4-... 2

# 方式B：自动加载下一个未详查的
python scripts/fetch_page.py next a1b2c3d4-...

# 方式C：直接加载任意 URL（不依赖搜索缓存）
python scripts/fetch_page.py url https://example.com/article
```

**第4步：总结后再加载下一个**
每次获取到网页内容后，先阅读理解并总结关键信息，然后再加载下一个

**第5步：重复直到信息充分**
根据需要加载多个网页，综合所有信息完成用户请求

## 信息不足时的补救策略（大模型必读）

加载网页时可能遇到以下情况，需要采取补救措施：

### 情况A：网页加载失败（403、超时、内容为空）
当 `full_content` 返回以下任意一种失败信息时：
- `[无法获取内容: ...]`（如 403 禁止访问、超时等）
- `[页面内容为空]`
- `[无有效链接]`
- 内容极短（少于 50 字）

**应对方案：**
1. **尝试同 session 中的下一个结果**：`python scripts/fetch_page.py next {session_id}`
2. **换一组关键词重新搜索**：比如 `python scripts/do_search.py search {更具体的关键词} 5`，获取新的 session_id，再加载新结果
3. **使用更广泛的关键词**：比如从 "Agent发展历史" 改为 "AI Agent 演进" 或 "智能体技术发展"

### 情况B：搜索结果质量低（标题/摘要不相关）
当搜索返回的结果标题和摘要与需求不匹配时：
1. **换关键词重新搜索**：使用更精准或更宽泛的关键词
2. **直接加载已知优质 URL**：`python scripts/fetch_page.py url {网址}`

### 示例流程
```
# 搜索
python scripts/do_search.py search AI Agent发展历史 5
# 返回 session: abc123

# 尝试加载索引 2，返回 [无法获取内容: 403]
python scripts/fetch_page.py fetch abc123 2
# → 加载失败！

# 尝试加载索引 3
python scripts/fetch_page.py fetch abc123 3
# → 也失败！

# 换关键词重新搜索
python scripts/do_search.py search 智能体Agent技术演进 5
# → 返回新 session: def456，继续加载新结果
```

## 搜索结果说明
- **搜索返回**：标题（title）、链接（href）、摘要（body）
- **加载返回**：在搜索结果基础上增加 `full_content` 字段（网页正文，最长15000字符）
- 网页内容会自动清理 HTML 标签、脚本、样式、导航栏等，只保留正文
- 如果无法获取网页内容，`full_content` 字段会显示错误信息

## 注意事项
- 搜索缓存有效期为30分钟，超时后 session_id 失效，需要重新搜索
- result_index 从0开始，不能超过结果总数减1
- 使用 run_command 执行命令时**必须**指定 skill_id 参数
- **执行完成后必须调用 finish 工具，将搜索结果整理后返回给用户**
- **重要：不要一次性加载所有网页，应该逐个加载、逐个理解总结**

## 依赖
- requests
- baidusearch
- trafilatura
