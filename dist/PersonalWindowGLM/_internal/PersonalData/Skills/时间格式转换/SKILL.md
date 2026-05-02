---
id: 5
name: 时间格式转换
description: 将回答的时间格式进行统一的转换
---

## 功能
自动识别时间输入，统一转换为：
- 标准日期时间：YYYY-MM-DD HH:MM:SS
- 时间戳（秒级）
支持时区，默认东八区（北京时间）

## 输入参数
- time_input：时间字符串/时间戳
- target_format：datetime / timestamp
- timezone：时区偏移，默认 +08:00

## 调用命令
`scripts/time_format.py "{time_input}" "{target_format}" "{timezone}"`