---
id: scheduled_task_guide
name: 定时任务创建指南
description: 指导如何创建定时任务，包括执行类型判断、执行链路生成等
---

# 定时任务创建指南

【定时任务创建指南】（create_scheduled_task）

**一、执行类型判断规则**

根据用户意图判断应使用的执行类型：

| 用户意图关键词 | 执行类型 | 说明 |
|--------------|--------|------|
| "提醒我..."、"记得..."、"别忘了..." | notification | 简单提醒类任务，仅发送通知 |
| "帮我..."、"自动..."、"执行..."、"定时..." | agent_conversation | 执行任务类任务，需要执行具体操作 |

**重要：任务目标提取规则**

当用户表述中包含"创建会话"、"新建会话"、"开个会话"等词汇时，这些只是**触发方式**，不是**任务目标**。必须提取真正的任务目标作为 execution_chain 的 goal。

| 用户表述 | 错误的 goal | 正确的 goal |
|---------|------------|------------|
| "10分钟后创建会话询问天气" | "创建会话询问天气" | "询问天气情况" |
| "明天早上新建会话帮我查询基金净值" | "新建会话帮我查询基金净值" | "查询基金净值" |
| "定时创建会话提醒我吃药" | "创建会话提醒我吃药" | "提醒用户吃药" |
| "下午3点开个会话分析数据" | "开个会话分析数据" | "分析数据" |

**核心原则**：
- `goal` 字段应该是定时触发后 Agent 要执行的**实际任务内容**
- "创建会话"是系统自动完成的（agent_conversation 类型会自动创建新会话），不应写入 goal
- 如果 goal 中包含"创建会话"等词汇，Agent 可能会再次创建定时任务，导致无限循环

**二、两种类型的区别**

1. **notification 类型**：
   - 仅在指定时间发送系统通知提醒用户
   - 不执行任何自动化操作
   - 适用于：会议提醒、吃药提醒、日程提醒等

2. **agent_conversation 类型**：
   - 在指定时间触发 Agent 自动执行任务
   - 需要提供完整的执行链路（execution_chain）
   - 适用于：定时查询数据、自动生成报告、定时执行脚本等

**三、执行链路 JSON 格式**

对于 agent_conversation 类型，必须提供 execution_chain 字段：
```json
{
  "goal": "任务目标描述（清晰说明要完成什么）",
  "skills": ["skill_id_1", "skill_id_2"],
  "steps": ["步骤1：具体操作描述", "步骤2：具体操作描述", "步骤3：具体操作描述"],
  "parameters": {"key": "value"}
}
```

- `goal`：任务的整体目标，用于 Agent 理解任务意图
- `skills`：需要加载的 Skill ID 列表（可为空数组）
- `steps`：执行步骤的详细描述列表
- `parameters`：任务所需的参数（可为空对象）

**四、示例场景**

**示例1：简单提醒类**
用户说："提醒我明天下午3点开会"
→ 使用 notification 类型
→ 参数示例：
```json
{
  "task_name": "会议提醒",
  "execution_type": "notification",
  "notification_message": "您有一个会议，请准时参加",
  "scheduled_time": "2026-05-29 15:00:00"
}
```

**示例2：执行任务类**
用户说："每天早上9点帮我查询基金净值并保存到Excel"
→ 使用 agent_conversation 类型
→ 参数示例：
```json
{
  "task_name": "每日基金净值查询",
  "execution_type": "agent_conversation",
  "scheduled_time": "2026-05-29 09:00:00",
  "repeat_config": {
    "enabled": true,
    "frequency": "daily",
    "interval": 1
  },
  "execution_chain": {
    "goal": "查询指定基金的净值信息并保存到Excel文件",
    "skills": ["fund_query"],
    "steps": [
      "获取用户关注的基金代码列表",
      "调用基金查询接口获取最新净值",
      "将净值数据整理为表格格式",
      "追加保存到指定的Excel文件中"
    ],
    "parameters": {
      "fund_codes": ["000001", "110022"],
      "output_file": "基金净值记录.xlsx"
    }
  }
}
```

**示例3：定时执行脚本**
用户说："每周一早上8点自动执行数据备份脚本"
→ 使用 agent_conversation 类型
→ 参数示例：
```json
{
  "task_name": "每周数据备份",
  "execution_type": "agent_conversation",
  "scheduled_time": "2026-06-01 08:00:00",
  "repeat_config": {
    "enabled": true,
    "frequency": "weekly",
    "interval": 1,
    "day_of_week": ["monday"]
  },
  "execution_chain": {
    "goal": "执行数据备份脚本，将重要数据备份到指定目录",
    "skills": [],
    "steps": [
      "检查备份脚本是否存在",
      "执行备份脚本",
      "验证备份文件是否生成成功",
      "记录备份日志"
    ],
    "parameters": {
      "script_path": "scripts/backup.py",
      "backup_dir": "D:/Backups"
    }
  }
}
```

**示例4：创建会话执行任务（重点示例）**
用户说："10分钟后创建会话询问今天的天气情况"
→ 使用 agent_conversation 类型
→ **关键点**：goal 是"询问天气情况"，不是"创建会话询问天气情况"
→ 参数示例：
```json
{
  "task_name": "询问天气",
  "execution_type": "agent_conversation",
  "scheduled_time": "2026-05-28 14:30:00",
  "execution_chain": {
    "goal": "询问今天的天气情况",
    "skills": [],
    "steps": [
      "获取用户所在城市",
      "查询该城市的天气信息",
      "向用户报告天气情况"
    ],
    "parameters": {}
  }
}
```

**错误示例（会导致无限循环）**：
```json
{
  "execution_chain": {
    "goal": "创建会话询问天气情况",  // ❌ 错误！包含"创建会话"
    ...
  }
}
```
当任务触发时，Agent 收到"创建会话询问天气情况"的指令，可能会再次调用 create_scheduled_task，导致无限循环创建任务。

**五、创建定时任务的流程**

1. 先调用工具获取当前系统时间
2. 解析用户指定的时间（相对时间转换为绝对时间）
3. 判断任务类型（notification 或 agent_conversation）
4. 对于 agent_conversation 类型，生成完整的 execution_chain
5. 在创建任务之前，要先询问用户是否确认创建任务，询问内容要展示当前的任务详情。
6. 调用 create_scheduled_task 工具创建任务
7. 向用户确认任务创建成功