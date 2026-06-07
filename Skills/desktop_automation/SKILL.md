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

### 与传统方案对比

| 方案 | 精度 | 稳定性 | 适用场景 |
|------|------|--------|---------|
| **LLM图片识别+pyautogui** | 低 | 低 | 通用但不可靠 |
| **CLI/API方案** | 高 | 高 | 需要API支持 |
| **Accessibility Tree** | 100% | 高 | 支持UIA的应用 |

## 使用场景

- 自动填写表单（Excel、Word、浏览器等）
- 操作Windows应用程序（Notepad、计算器等）
- 执行重复性桌面任务
- 自动化软件测试

## 执行流程

### 重要：执行前必须先规划

**执行本Skill时，必须遵循以下步骤顺序**：

1. **查询系统信息**：先了解当前系统状态
2. **任务拆分规划**：将用户任务分解为可执行的步骤
3. **按计划执行**：逐步执行每个步骤

---

### 第一步：查询系统信息

在执行任何自动化操作前，**必须先调用以下工具获取系统信息**：

```
# 1. 获取当前系统所有活跃窗口列表（窗口句柄、标题、进程ID）
get_accessibility_tree()
# 返回：当前系统活跃窗口列表，包含窗口名称、进程ID、窗口句柄等

# 2. 如果需要操作特定窗口，获取该窗口的详细UI结构
get_accessibility_tree(window_title="窗口名称")
# 或
get_accessibility_tree(process_id=进程ID)

# 3. 查询系统已安装的应用程序（如果需要启动程序）
list_installed_apps(filter="关键词")  # 可选：使用关键词过滤
```

**目的**：
- 了解当前系统有哪些活跃窗口（窗口句柄列表）
- 了解用户当前在哪个应用（焦点窗口）
- 确认目标应用是否已打开
- 了解系统有哪些可启动的程序
- 避免误操作其他应用

---

### 第二步：任务拆分规划

根据用户任务和系统信息，**必须先制定执行计划**：

**规划模板**：
```
任务：[用户任务描述]
当前状态：[系统信息摘要]
执行计划：
  步骤1：[具体操作]
  步骤2：[具体操作]
  步骤3：[具体操作]
  ...
预期结果：[任务完成后的状态]
```

**规划示例**：
```
任务：在记事本中输入"Hello World"并保存
当前状态：记事本未运行，桌面有Chrome和Excel窗口
执行计划：
  步骤1：启动记事本 (start_application)
  步骤2：等待窗口加载 (wait_time=2)
  步骤3：获取记事本窗口结构 (get_accessibility_tree)
  步骤4：定位编辑框 (find_element)
  步骤5：输入文本 (type_text)
  步骤6：点击"文件"菜单 (click_element)
  步骤7：点击"保存" (click_element)
预期结果：记事本中包含"Hello World"文本，文件已保存
```

---

### 第三步：按计划执行

**执行原则**：
- 按规划的步骤顺序执行
- 每步执行后验证结果
- 遇到错误时调整计划
- 使用 `finish` 工具标记任务完成

---

### 完整执行流程示例

**用户任务**："帮我打开Excel并输入数据"

**正确执行顺序**：

```
# ===== 第一步：查询系统信息 =====
get_accessibility_tree()
# 返回：当前焦点在Chrome窗口

get_accessibility_tree(max_depth=1)
# 返回：桌面窗口列表 [Chrome, Explorer, Outlook]

# ===== 第二步：任务拆分规划 =====
# 任务：打开Excel并输入数据
# 当前状态：Excel未运行，Chrome是焦点窗口
# 执行计划：
#   步骤1：启动Excel
#   步骤2：等待Excel窗口加载
#   步骤3：获取Excel窗口结构
#   步骤4：定位单元格编辑框
#   步骤5：输入数据

# ===== 第三步：按计划执行 =====

# 步骤1：启动Excel
start_application(app="excel", wait_time=3)

# 步骤2：获取Excel窗口结构
get_accessibility_tree(window_title="Excel")

# 步骤3：定位单元格
find_element(method="by_name", query="单元格")

# 步骤4：输入数据
type_text(element="单元格", text="测试数据")

# 步骤5：完成任务
finish()
```

---

## 工具详解

### start_application

启动应用程序。

**【重要】启动程序前应先查询已安装程序列表**：
```
# 先查询系统有哪些程序
list_installed_apps(filter="office")  # 过滤关键词

# 根据查询结果选择合适的程序启动
start_application(app="excel")
```

**参数**：
- `app`（必需）：程序名称、完整路径或URL
- `method`（可选）：启动方式
  - `by_name`：通过程序名称（如 notepad、chrome）
  - `by_path`：通过完整路径（如 C:\Program Files\app.exe）
  - `by_url`：通过URL（打开默认浏览器）
- `wait_time`（可选）：启动后等待时间，默认2秒
- `args`（可选）：启动参数

**示例**：
```
# 启动记事本
start_application(app="notepad")

# 启动Excel并打开特定文件
start_application(app="excel", args="C:\\data.xlsx")

# 启动Chrome浏览器
start_application(app="chrome")

# 通过路径启动程序
start_application(app="C:\\Program Files\\MyApp\\app.exe", method="by_path")

# 打开网页
start_application(app="https://www.example.com", method="by_url")
```

### list_installed_apps

查询系统已安装的应用程序列表。

**【使用时机】在调用 start_application 启动程序前，应先调用本工具查询系统已有的程序，让大模型根据用户意图选择合适的程序。**

**参数**：
- `filter`（可选）：过滤关键词（如 'office'、'browser'、'editor'）
- `max_results`（可选）：最大返回数量，默认50

**示例**：
```
# 查询所有已安装程序
list_installed_apps()

# 查询Office相关程序
list_installed_apps(filter="office")

# 查询浏览器
list_installed_apps(filter="browser")

# 查询编辑器
list_installed_apps(filter="editor")
```

**返回信息**：
- 程序名称
- 安装路径/可执行文件路径
- 程序类型（快捷方式/可执行文件/已安装）

### get_accessibility_tree

获取窗口的UI元素结构树。

**参数**：
- `window_title`（可选）：窗口标题，支持部分匹配
- `process_id`（可选）：进程ID
- `max_depth`（可选）：最大遍历深度，默认5
- `max_elements`（可选）：最大元素数量，默认500

**示例**：
```
# 获取记事本窗口的Accessibility Tree
get_accessibility_tree(window_title="记事本")

# 获取当前焦点窗口
get_accessibility_tree()
```

### find_element

查找UI元素。

**参数**：
- `method`（必需）：查找方法
  - `by_name`：按元素名称查找
  - `by_automation_id`：按AutomationId查找
  - `by_control_type`：按控件类型查找
  - `by_coordinates`：按坐标查找
  - `by_pattern`：按支持的Pattern查找
- `query`（必需）：查找条件
- `window_title`（可选）：限制搜索范围
- `max_results`（可选）：最大结果数

**示例**：
```
# 查找名为"保存"的按钮
find_element(method="by_name", query="保存")

# 查找所有Edit控件
find_element(method="by_control_type", query="Edit", max_results=20)

# 查找坐标(100,200)处的元素
find_element(method="by_coordinates", query="100,200")

# 查找所有可点击的元素（支持InvokePattern）
find_element(method="by_pattern", query="InvokePattern")
```

### click_element

点击UI元素。

**参数**：
- `element`（必需）：元素定位条件
- `method`（可选）：点击方式
  - `invoke`：使用InvokePattern（推荐）
  - `mouse`：鼠标点击
- `wait_time`（可选）：点击后等待时间，默认0.1秒

**示例**：
```
# 点击名为"确定"的按钮
click_element(element="确定")

# 使用鼠标点击
click_element(element="关闭", method="mouse")
```

### type_text

在UI元素中输入文本。

**参数**：
- `element`（必需）：元素定位条件
- `text`（必需）：要输入的文本
- `method`（可选）：输入方式
  - `value`：使用ValuePattern（推荐）
  - `sendkeys`：使用SendKeys
- `clear_first`（可选）：是否先清空，默认true
- `wait_time`（可选）：输入后等待时间

**示例**：
```
# 在文本框中输入内容
type_text(element="文本框", text="Hello World")

# 不清空现有内容，追加输入
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
# 向下滚动列表
scroll_element(element="列表", direction="down")

# 大步滚动3次
scroll_element(element="页面", direction="down", amount="large", count=3)
```

### get_element_state

获取元素状态。

**参数**：
- `element`（必需）：元素定位条件

**示例**：
```
# 检查元素状态
get_element_state(element="CheckBox")
```

## 实战示例

### 示例1：完整的自动化流程（启动+操作）

```
# ===== 第一步：查询系统信息 =====
get_accessibility_tree()
# 返回：当前焦点在Chrome窗口

get_accessibility_tree(max_depth=1)
# 返回：桌面窗口列表 [Chrome, Explorer, Outlook]

list_installed_apps(filter="editor")
# 返回：找到 5 个编辑器程序：
# - 记事本 (可执行文件: C:\Windows\notepad.exe)
# - Notepad++ (可执行文件: C:\Program Files\Notepad++\notepad++.exe)
# - VS Code (可执行文件: C:\Program Files\VS Code\code.exe)
# ...

# ===== 第二步：任务拆分规划 =====
# 任务：打开记事本并输入文本
# 当前状态：记事本未运行，系统有记事本程序
# 执行计划：
#   步骤1：启动记事本 (start_application)
#   步骤2：等待窗口加载 (wait_time=2)
#   步骤3：获取记事本窗口结构 (get_accessibility_tree)
#   步骤4：定位编辑框 (find_element)
#   步骤5：输入文本 (type_text)

# ===== 第三步：按计划执行 =====

# 步骤1：启动记事本
start_application(app="notepad", wait_time=2)

# 步骤2：获取记事本窗口结构
get_accessibility_tree(window_title="记事本")

# 步骤3：查找编辑框
find_element(method="by_control_type", query="Edit")

# 步骤4：输入文本
type_text(element="Edit", text="这是自动输入的文本")

# 步骤5：保存文件（点击菜单）
click_element(element="文件")
click_element(element="保存")
```

### 示例2：自动填写记事本（已打开窗口）

```
# 1. 获取记事本窗口结构
get_accessibility_tree(window_title="记事本")

# 2. 查找编辑框
find_element(method="by_control_type", query="Edit")

# 3. 输入文本
type_text(element="Edit", text="这是自动输入的文本")

# 4. 保存文件（点击菜单）
click_element(element="文件")
click_element(element="保存")
```

### 示例3：启动Excel并操作

```
# 1. 获取Excel窗口结构
get_accessibility_tree(window_title="Excel")

# 2. 查找单元格编辑框
find_element(method="by_name", query="单元格")

# 3. 输入数据
type_text(element="单元格", text="数据值")
```

### 示例4：浏览器自动化

```
# 1. 打开网页
start_application(app="https://example.com/login", method="by_url", wait_time=3)

# 2. 获取浏览器窗口结构
get_accessibility_tree(window_title="Chrome")

# 3. 查找输入框
find_element(method="by_control_type", query="Edit")

# 4. 填写表单
type_text(element="用户名", text="admin")
type_text(element="密码", text="password123")

# 5. 点击登录按钮
click_element(element="登录")
```

## 注意事项

1. **窗口标题匹配**：支持部分匹配，但建议使用完整标题以提高准确性
2. **元素定位优先级**：
   - AutomationId（最稳定）
   - 名称（较稳定）
   - 控件类型（需要结合其他条件）
   - 坐标（不稳定，仅作为fallback）
3. **操作等待**：某些操作后需要等待界面响应，可适当增加wait_time
4. **错误处理**：如果操作失败，先检查元素是否存在、是否可操作

## 技术原理

本Skill基于Windows UI Automation API，这是Windows操作系统原生提供的辅助功能API，用于支持屏幕阅读器等辅助技术。

### Accessibility Tree

Accessibility Tree是操作系统暴露的UI结构化视图，包含：
- 元素名称（Name）
- 控件类型（ControlType）
- AutomationId（开发者定义的唯一标识）
- 边界矩形（BoundingRectangle）
- 状态（IsEnabled、IsVisible等）
- 支持的Pattern（InvokePattern、ValuePattern等）

### Control Patterns

Control Patterns定义了元素支持的操作：
- InvokePattern：可点击
- ValuePattern：可设置值
- TextPattern：文本操作
- ScrollPattern：可滚动
- ExpandCollapsePattern：可展开/折叠
- TogglePattern：可切换状态