---
id: desktop_automation
name: 桌面自动化
description: 自动操作、自动化、桌面自动化、窗口操作、自动点击、自动输入、自动填写、表单填写、启动程序、打开程序、UI自动化、Windows自动化、自动控制、桌面操作、窗口控制、应用自动化
auto_load: false
---

## 功能说明

本Skill提供基于Windows UI Automation API的桌面自动化能力，可以精确、稳定地操作Windows桌面应用程序。

### 核心能力

1. **启动应用程序**：通过程序名、路径或URL启动应用
2. **Accessibility Tree解析**：获取窗口中所有UI元素的结构化信息
3. **元素查找**：按名称、ID、类型、坐标等方式定位UI元素
4. **动作执行**：点击、输入、滚动等操作
5. **状态查询**：获取元素的当前状态

---

## 关键约束

**【重要】执行自动化任务时，必须遵守以下约束，否则任务将被强制终止！**

### 1. 失败计数和重试限制

- **单步操作最多重试3次**：超过限制后跳过该步骤或尝试备选方案
- **任务整体最多失败5次**：超过限制后强制终止任务
- **执行时间最多60秒**：超过时间限制后强制终止任务
- **返回结果包含失败计数提示**：告知剩余重试机会

**当达到停止条件后，不要继续尝试相同操作，应重新规划任务或放弃。**

### 2. 幻觉检测机制

- **必须先验证元素存在**：操作前系统会验证元素真实存在
- **必须验证操作可行性**：确认元素支持目标操作（如是否支持点击）
- **幻觉操作将被拒绝**：系统会拒绝不存在的元素或不可行的操作

**如果收到"幻觉检测"警告，请重新查询UI树或尝试其他定位方法。**

### 3. 停止条件

当出现以下情况时，任务将被强制终止：
- 单步失败超过3次
- 整体失败超过5次
- 执行时间超过60秒

**达到停止条件后不要继续尝试，应重新规划任务或放弃。**

---

## 执行流程（简化版）

### 步骤1：查询系统信息

在执行任何自动化操作前，**必须先调用以下工具获取系统信息**：

```
# 1. 获取当前系统所有活跃窗口列表
get_accessibility_tree()

# 2. 查询系统已安装的应用程序（如果需要启动程序）
list_installed_apps(filter="关键词")
```

### 步骤2：任务拆分规划

根据用户任务和系统信息，制定执行计划：

```
任务：[用户任务描述]
当前状态：[系统信息摘要]
执行计划：
  步骤1：[具体操作]
  步骤2：[具体操作]
  ...
预期结果：[任务完成后的状态]
```

### 步骤3：按计划执行

**执行原则**：
1. 按规划的步骤顺序执行
2. 等待工具返回结果
3. 根据结果继续执行或调整计划
4. 只有任务完成才能调用finish

---

## 工具使用指南

### start_application

启动应用程序。

**参数**：
- `app`（必需）：程序名称、完整路径或URL
- `method`（可选）：启动方式（by_name/by_path/by_url）
- `wait_time`（可选）：启动后等待时间，默认2秒

**示例**：
```
start_application(app="chrome", wait_time=3)
start_application(app="C:\\Program Files\\app.exe", method="by_path")
start_application(app="https://example.com", method="by_url")
```

### get_accessibility_tree

获取窗口的UI元素结构树。

**参数**：
- `process_id`（推荐）：进程ID
- `window_title`（可选）：窗口标题
- `max_depth`（可选）：最大遍历深度，默认5

**示例**：
```
# 获取所有活跃窗口列表
get_accessibility_tree()

# 获取特定窗口的详细UI结构
get_accessibility_tree(process_id=1234)
get_accessibility_tree(window_title="记事本")
```

### find_element

查找UI元素。

**参数**：
- `method`（必需）：查找方法（by_name/by_automation_id/by_control_type/by_coordinates）
- `query`（必需）：查找条件
- `window_title`（可选）：限制搜索范围

**示例**：
```
find_element(method="by_name", query="保存")
find_element(method="by_control_type", query="Edit")
find_element(method="by_coordinates", query="100,200")
```

### click_element

点击UI元素。

**参数**：
- `element`（必需）：元素定位条件
- `method`（可选）：点击方式（invoke/mouse）

**示例**：
```
click_element(element="确定")
click_element(element="关闭", method="mouse")
```

### type_text

在UI元素中输入文本。

**参数**：
- `element`（必需）：元素定位条件
- `text`（必需）：要输入的文本
- `method`（可选）：输入方式（value/sendkeys）
- `clear_first`（可选）：是否先清空，默认true

**示例**：
```
type_text(element="文本框", text="Hello World")
type_text(element="搜索框", text="关键词", clear_first=false)
```

### scroll_element

滚动UI元素。

**参数**：
- `element`（必需）：元素定位条件
- `direction`（必需）：滚动方向（up/down/left/right）
- `amount`（可选）：滚动量（small/large）
- `count`（可选）：滚动次数

**示例**：
```
scroll_element(element="列表", direction="down")
scroll_element(element="页面", direction="down", amount="large", count=3)
```

### get_element_state

获取元素状态。

**参数**：
- `element`（必需）：元素定位条件

**示例**：
```
get_element_state(element="CheckBox")
```

### send_hotkey

发送热键。

**参数**：
- `keys`（必需）：热键组合，用+连接
- `target_window`（可选）：目标窗口标题

**示例**：
```
send_hotkey(keys="ctrl+c")
send_hotkey(keys="ctrl+s")
send_hotkey(keys="alt+f4")
```

---

## 完整执行示例

**用户任务**："帮我打开记事本并输入文本"

```
# 步骤1：查询系统信息
get_accessibility_tree()
# 返回：当前系统活跃窗口列表...

# 步骤2：启动记事本
start_application(app="notepad", wait_time=2)
# 返回：已启动程序: notepad

# 步骤3：获取记事本窗口结构
get_accessibility_tree(window_title="记事本")
# 返回：窗口UI结构...

# 步骤4：查找编辑框
find_element(method="by_control_type", query="Edit")
# 返回：找到元素...

# 步骤5：输入文本
type_text(element="文本编辑器", text="这是自动输入的文本")
# 返回：输入成功...

# 步骤6：任务完成
finish(message="已成功打开记事本并输入文本")
```

---

## 附录：详细说明

### 元素定位优先级

1. **AutomationId（最稳定）**：开发者定义的唯一标识符
2. **名称（较稳定）**：元素的显示名称
3. **控件类型（需结合其他条件）**：如Button、Edit等
4. **坐标（不稳定，仅作为fallback）**：基于屏幕坐标定位

### 常见问题解答

**Q1: 元素未找到怎么办？**
- 检查窗口是否已完全加载（增加wait_time）
- 尝试不同的定位方法
- 检查元素是否在滚动区域内

**Q2: 操作失败怎么办？**
- 检查元素是否可用和可见
- 尝试不同的操作方式
- 查看失败统计信息，了解剩余重试机会

**Q3: 收到"幻觉检测"警告怎么办？**
- 重新调用get_accessibility_tree获取最新UI结构
- 确认元素名称和类型是否正确
- 尝试使用其他定位方法

### 技术原理

本Skill基于Windows UI Automation API，这是Windows操作系统原生提供的辅助功能API。

**Accessibility Tree**包含：
- 元素名称（Name）
- 控件类型（ControlType）
- AutomationId
- 边界矩形（BoundingRectangle）
- 状态（IsEnabled、IsVisible等）
- 支持的Pattern（InvokePattern、ValuePattern等）

**Control Patterns**定义了元素支持的操作：
- InvokePattern：可点击
- ValuePattern：可设置值
- ScrollPattern：可滚动
- TogglePattern：可切换状态

---

## 注意事项

1. **窗口标题匹配**：支持部分匹配，建议使用process_id以提高准确性
2. **元素定位优先级**：AutomationId > 名称 > 控件类型 > 坐标
3. **操作等待**：某些操作后需要等待界面响应
4. **错误处理**：如果操作失败，先检查元素是否存在、是否可操作
5. **停止条件**：达到停止条件后不要继续尝试，应重新规划任务