---
id: 88
name: 基金查询
description: 当用户需要查询基金相关的内容时调用，支持查询基金基本信息、单位净值、历史净值、指定时间范围内的基金列表及净值变化
---

## 功能
使用akshare查询基金信息，支持以下查询类型：
- 基金基本信息（基金代码、名称、类型）
- 单位净值（最新净值和日增长率）
- 历史净值（最近30天的净值走势）
- 基金列表（指定时间范围内新成立的基金列表及基本信息）
- 时间段净值（指定时间段内的净值数据，支持按涨跌过滤）
- 基金净值变化列表（指定时间段内基金净值总体变化、涨跌变化的基金列表）

## 输入参数
- fund_code: 基金代码（6位数字），查询类型为list或list_growth时不需要
- query_type: 查询类型，可选值：info(基本信息)、net(单位净值)、history(历史净值)、list(基金列表)、list_growth(净值变化列表)、period(时间段净值)，默认为info
- start_date: 起始日期（YYYY-MM-DD格式），查询类型为list、list_growth或period时必填
- end_date: 结束日期（YYYY-MM-DD格式），查询类型为list、list_growth或period时必填
- filter_type: 涨跌过滤类型，可选值：up(上涨)、down(下跌)、up_down(涨跌)，仅在query_type为period或list_growth时有效
- threshold: 涨跌阈值（百分比），当filter_type不为空时使用，默认0
- limit: 返回基金数量限制，仅在query_type为list_growth时有效，默认50

## 调用命令
**注意：参数之间用空格分隔，不要给参数加引号**

查询单个基金基本信息：
```
python scripts/fund_query.py {query_type} {fund_code}
```

查询基金列表：
```
python scripts/fund_query.py list {start_date} {end_date}
```

查询基金净值变化列表（可带过滤条件）：
```
python scripts/fund_query.py list_growth {start_date} {end_date} [filter_type] [threshold] [limit]
```

查询时间段净值（可带过滤条件）：
```
python scripts/fund_query.py period {fund_code} {start_date} {end_date} [filter_type] [threshold]
```

## 示例
- 查询基金基本信息：`python scripts/fund_query.py info 161725`
- 查询单位净值：`python scripts/fund_query.py net 161725`
- 查询历史净值：`python scripts/fund_query.py history 161725`
- 查询指定时间范围的基金列表：`python scripts/fund_query.py list 2024-01-01 2024-12-31`
- 查询指定时间段净值：`python scripts/fund_query.py period 161725 2024-01-01 2024-01-31`
- 查询指定时间段内涨幅超过2%的记录：`python scripts/fund_query.py period 161725 2024-01-01 2024-01-31 up 2`
- 查询基金净值变化列表：`python scripts/fund_query.py list_growth 2024-01-01 2024-01-31`
- 查询涨幅超过10%的基金列表：`python scripts/fund_query.py list_growth 2024-01-01 2024-01-31 up 10`
- 查询跌幅超过10%的基金列表：`python scripts/fund_query.py list_growth 2024-01-01 2024-01-31 down 10`
- 查询涨跌幅超过10%的基金列表：`python scripts/fund_query.py list_growth 2024-01-01 2024-01-31 up_down 10 20`

## 执行流程
1. 使用 run_command 执行上述命令
2. **必须**指定 skill_id 参数
3. 脚本返回JSON格式的基金数据
4. **执行完成后必须调用 finish 工具，将查询结果整理后返回给用户**

## 依赖
本技能包包含 requirements.txt：
- requests
- akshare