---
id: 8
name: DuckDuckGoSearch
description: 使用DuckDuckGo搜索引擎进行网页搜索，支持普通搜索、新闻搜索、图片搜索等多种搜索类型
---

## 功能
使用ddgs库进行网页搜索，返回搜索结果

## 输入参数
- query: 搜索关键词
- search_type: 搜索类型，可选值：text(普通搜索)、news(新闻搜索)、images(图片搜索)，默认为text
- max_results: 最大返回结果数，默认为5

## 调用命令
**注意：参数之间用空格分隔，不要给参数加引号**
```
python scripts/search.py {query} {search_type} {max_results}
```

示例：
- 搜索"崩坏三爱莉"：`python scripts/search.py 崩坏三爱莉 text 5`
- 搜索新闻：`python scripts/search.py 科技新闻 news 3`

## 执行流程
1. 使用 run_command 执行上述命令
2. **必须**指定 skill_id 参数
3. 脚本返回JSON格式的搜索结果
4. **执行完成后必须调用 finish 工具，将搜索结果整理后返回给用户**

## 依赖
本技能包包含 requirements.txt：
- ddgs
