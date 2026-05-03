---
id: 8
name: DuckDuckGoSearch
description: 使用DuckDuckGo搜索引擎进行网页搜索，支持普通搜索、新闻搜索、图片搜索等多种搜索类型
---

## 功能
使用ddgs库进行网页搜索，返回搜索结果，并自动获取每个结果链接的详细内容

## 输入参数
- query: 搜索关键词
- search_type: 搜索类型，可选值：text(普通搜索)、news(新闻搜索)、images(图片搜索)，默认为text
- max_results: 最大返回结果数，默认为5
- fetch_content: 是否获取详细内容，可选值：true(默认)、false。设为false时只返回搜索摘要

## 调用命令
**注意：参数之间用空格分隔，不要给参数加引号**
```
python scripts/search.py {query} {search_type} {max_results} {fetch_content}
```

示例：
- 搜索"崩坏三爱莉"并获取详细内容：`python scripts/search.py 崩坏三爱莉 text 5 true`
- 搜索新闻：`python scripts/search.py 科技新闻 news 5`
- 只获取摘要不获取详细内容：`python scripts/search.py Python教程 text 5 false`

## 搜索结果说明
- 每个搜索结果会包含 `full_content` 字段，存储从链接获取的完整网页内容
- 网页内容会自动清理HTML标签、脚本、样式等，只保留纯文本
- 内容最大长度限制为5000字符，超出部分会被截断
- 如果无法获取网页内容，`full_content` 字段会显示错误信息
- 图片搜索不支持获取详细内容

## 执行流程
1. 使用 run_command 执行上述命令
2. **必须**指定 skill_id 参数
3. 脚本返回JSON格式的搜索结果
4. **执行完成后必须调用 finish 工具，将搜索结果整理后返回给用户**

## 依赖
本技能包包含 requirements.txt：
- ddgs
- requests
