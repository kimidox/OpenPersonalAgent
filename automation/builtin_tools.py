"""
内置工具定义和注册机制

定义自动化操作所需的各种工具类型，包括定位器、执行器、提取器和条件判断器。
支持工具注册、查询和参数验证。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Optional, TypedDict
from logger import get_module_logger

logger = get_module_logger("builtin_tools")


# 工具类别类型
ToolCategory = Literal["locator", "executor", "extractor", "condition"]


class ToolParameterDefinition(TypedDict):
    """工具参数定义"""
    type: str  # 参数类型：string, int, float, boolean, element, position
    required: bool  # 是否必需
    description: str  # 参数描述
    default: Optional[Any]  # 默认值


class ToolReturnDefinition(TypedDict):
    """工具返回值定义"""
    type: str  # 返回类型：element, position, boolean, string, dict
    description: str  # 返回值描述


@dataclass
class ToolDefinition:
    """工具定义"""
    name: str
    category: ToolCategory
    description: str
    parameters: dict[str, ToolParameterDefinition]
    returns: ToolReturnDefinition
    implementation: Optional[Callable] = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式"""
        return {
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "parameters": self.parameters,
            "returns": self.returns,
        }


# 内置工具定义
BUILTIN_TOOLS: dict[str, dict[str, ToolDefinition]] = {
    "locators": {
        "find_by_name": ToolDefinition(
            name="find_by_name",
            category="locator",
            description="按名称查找元素",
            parameters={
                "name": {
                    "type": "string",
                    "required": True,
                    "description": "元素名称",
                    "default": None,
                },
                "exact": {
                    "type": "boolean",
                    "required": False,
                    "description": "是否精确匹配",
                    "default": False,
                },
                "control_type": {
                    "type": "string",
                    "required": False,
                    "description": "控件类型过滤",
                    "default": None,
                },
                "window_title": {
                    "type": "string",
                    "required": False,
                    "description": "窗口标题（限制搜索范围）",
                    "default": None,
                },
            },
            returns={
                "type": "element",
                "description": "找到的元素信息",
            },
        ),
        "find_by_id": ToolDefinition(
            name="find_by_id",
            category="locator",
            description="按AutomationId查找元素",
            parameters={
                "automation_id": {
                    "type": "string",
                    "required": True,
                    "description": "AutomationId",
                    "default": None,
                },
                "window_title": {
                    "type": "string",
                    "required": False,
                    "description": "窗口标题",
                    "default": None,
                },
            },
            returns={
                "type": "element",
                "description": "找到的元素信息",
            },
        ),
        "find_by_template": ToolDefinition(
            name="find_by_template",
            category="locator",
            description="按图片模板匹配查找元素位置",
            parameters={
                "template_id": {
                    "type": "string",
                    "required": True,
                    "description": "模板图片ID",
                    "default": None,
                },
                "threshold": {
                    "type": "float",
                    "required": False,
                    "description": "匹配精度阈值（0-1）",
                    "default": 0.8,
                },
                "multi_match": {
                    "type": "boolean",
                    "required": False,
                    "description": "是否多模板匹配",
                    "default": False,
                },
            },
            returns={
                "type": "position",
                "description": "匹配的位置坐标列表",
            },
        ),
        "find_by_coordinates": ToolDefinition(
            name="find_by_coordinates",
            category="locator",
            description="按坐标查找元素",
            parameters={
                "x": {
                    "type": "int",
                    "required": True,
                    "description": "X坐标",
                    "default": None,
                },
                "y": {
                    "type": "int",
                    "required": True,
                    "description": "Y坐标",
                    "default": None,
                },
            },
            returns={
                "type": "element",
                "description": "该坐标处的元素信息",
            },
        ),
        "find_by_control_type": ToolDefinition(
            name="find_by_control_type",
            category="locator",
            description="按控件类型查找元素",
            parameters={
                "control_type": {
                    "type": "string",
                    "required": True,
                    "description": "控件类型（如Button、Edit等）",
                    "default": None,
                },
                "window_title": {
                    "type": "string",
                    "required": False,
                    "description": "窗口标题",
                    "default": None,
                },
                "max_results": {
                    "type": "int",
                    "required": False,
                    "description": "最大返回数量",
                    "default": 100,
                },
            },
            returns={
                "type": "element",
                "description": "找到的元素列表",
            },
        ),
    },
    
    "executors": {
        "click": ToolDefinition(
            name="click",
            category="executor",
            description="点击元素",
            parameters={
                "element": {
                    "type": "element",
                    "required": True,
                    "description": "要点击的元素",
                    "default": None,
                },
                "method": {
                    "type": "string",
                    "required": False,
                    "description": "点击方法（invoke/mouse）",
                    "default": "invoke",
                },
                "wait_time": {
                    "type": "float",
                    "required": False,
                    "description": "点击后等待时间（秒）",
                    "default": 0.1,
                },
            },
            returns={
                "type": "boolean",
                "description": "是否成功",
            },
        ),
        "type": ToolDefinition(
            name="type",
            category="executor",
            description="输入文本",
            parameters={
                "element": {
                    "type": "element",
                    "required": True,
                    "description": "输入框元素",
                    "default": None,
                },
                "text": {
                    "type": "string",
                    "required": True,
                    "description": "要输入的文本",
                    "default": None,
                },
                "method": {
                    "type": "string",
                    "required": False,
                    "description": "输入方法（value/sendkeys）",
                    "default": "value",
                },
                "clear_first": {
                    "type": "boolean",
                    "required": False,
                    "description": "是否先清空",
                    "default": True,
                },
            },
            returns={
                "type": "boolean",
                "description": "是否成功",
            },
        ),
        "start_application": ToolDefinition(
            name="start_application",
            category="executor",
            description="启动应用程序",
            parameters={
                "app": {
                    "type": "string",
                    "required": True,
                    "description": "程序名称或路径",
                    "default": None,
                },
                "wait_time": {
                    "type": "float",
                    "required": False,
                    "description": "等待时间（秒）",
                    "default": 2.0,
                },
                "arguments": {
                    "type": "string",
                    "required": False,
                    "description": "启动参数",
                    "default": None,
                },
            },
            returns={
                "type": "boolean",
                "description": "是否成功",
            },
        ),
        "scroll": ToolDefinition(
            name="scroll",
            category="executor",
            description="滚动元素",
            parameters={
                "element": {
                    "type": "element",
                    "required": True,
                    "description": "要滚动的元素",
                    "default": None,
                },
                "direction": {
                    "type": "string",
                    "required": False,
                    "description": "滚动方向（up/down/left/right）",
                    "default": "down",
                },
                "amount": {
                    "type": "string",
                    "required": False,
                    "description": "滚动量（small/large）",
                    "default": "small",
                },
                "count": {
                    "type": "int",
                    "required": False,
                    "description": "滚动次数",
                    "default": 1,
                },
            },
            returns={
                "type": "boolean",
                "description": "是否成功",
            },
        ),
        "expand_collapse": ToolDefinition(
            name="expand_collapse",
            category="executor",
            description="展开/折叠元素",
            parameters={
                "element": {
                    "type": "element",
                    "required": True,
                    "description": "要操作的元素",
                    "default": None,
                },
                "action": {
                    "type": "string",
                    "required": False,
                    "description": "动作（expand/collapse/toggle）",
                    "default": "toggle",
                },
            },
            returns={
                "type": "boolean",
                "description": "是否成功",
            },
        ),
        "toggle": ToolDefinition(
            name="toggle",
            category="executor",
            description="切换元素状态（CheckBox、RadioButton等）",
            parameters={
                "element": {
                    "type": "element",
                    "required": True,
                    "description": "要切换的元素",
                    "default": None,
                },
            },
            returns={
                "type": "boolean",
                "description": "是否成功",
            },
        ),
        "hotkey": ToolDefinition(
            name="hotkey",
            category="executor",
            description="发送快捷键",
            parameters={
                "keys": {
                    "type": "string",
                    "required": True,
                    "description": "快捷键组合（如Ctrl+C）",
                    "default": None,
                },
            },
            returns={
                "type": "boolean",
                "description": "是否成功",
            },
        ),
        "click_position": ToolDefinition(
            name="click_position",
            category="executor",
            description="点击指定坐标位置",
            parameters={
                "x": {
                    "type": "int",
                    "required": True,
                    "description": "X坐标",
                    "default": None,
                },
                "y": {
                    "type": "int",
                    "required": True,
                    "description": "Y坐标",
                    "default": None,
                },
                "button": {
                    "type": "string",
                    "required": False,
                    "description": "鼠标按钮（left/right/middle）",
                    "default": "left",
                },
            },
            returns={
                "type": "boolean",
                "description": "是否成功",
            },
        ),
    },
    
    "extractors": {
        "extract_text": ToolDefinition(
            name="extract_text",
            category="extractor",
            description="提取元素文本内容",
            parameters={
                "element": {
                    "type": "element",
                    "required": True,
                    "description": "元素",
                    "default": None,
                },
            },
            returns={
                "type": "string",
                "description": "提取的文本",
            },
        ),
        "extract_value": ToolDefinition(
            name="extract_value",
            category="extractor",
            description="提取元素值",
            parameters={
                "element": {
                    "type": "element",
                    "required": True,
                    "description": "元素",
                    "default": None,
                },
            },
            returns={
                "type": "string",
                "description": "提取的值",
            },
        ),
        "extract_state": ToolDefinition(
            name="extract_state",
            category="extractor",
            description="提取元素状态",
            parameters={
                "element": {
                    "type": "element",
                    "required": True,
                    "description": "元素",
                    "default": None,
                },
            },
            returns={
                "type": "dict",
                "description": "元素状态信息",
            },
        ),
        "capture_screen": ToolDefinition(
            name="capture_screen",
            category="extractor",
            description="截取屏幕",
            parameters={
                "region": {
                    "type": "string",
                    "required": False,
                    "description": "截图区域（x,y,width,height）",
                    "default": None,
                },
            },
            returns={
                "type": "string",
                "description": "截图保存路径",
            },
        ),
    },
    
    "conditions": {
        "if_exists": ToolDefinition(
            name="if_exists",
            category="condition",
            description="判断元素是否存在",
            parameters={
                "element": {
                    "type": "element",
                    "required": True,
                    "description": "元素",
                    "default": None,
                },
            },
            returns={
                "type": "boolean",
                "description": "是否存在",
            },
        ),
        "if_visible": ToolDefinition(
            name="if_visible",
            category="condition",
            description="判断元素是否可见",
            parameters={
                "element": {
                    "type": "element",
                    "required": True,
                    "description": "元素",
                    "default": None,
                },
            },
            returns={
                "type": "boolean",
                "description": "是否可见",
            },
        ),
        "if_enabled": ToolDefinition(
            name="if_enabled",
            category="condition",
            description="判断元素是否可用",
            parameters={
                "element": {
                    "type": "element",
                    "required": True,
                    "description": "元素",
                    "default": None,
                },
            },
            returns={
                "type": "boolean",
                "description": "是否可用",
            },
        ),
        "if_text_contains": ToolDefinition(
            name="if_text_contains",
            category="condition",
            description="判断元素文本是否包含指定内容",
            parameters={
                "element": {
                    "type": "element",
                    "required": True,
                    "description": "元素",
                    "default": None,
                },
                "text": {
                    "type": "string",
                    "required": True,
                    "description": "要检查的文本",
                    "default": None,
                },
            },
            returns={
                "type": "boolean",
                "description": "是否包含",
            },
        ),
        "wait_for_element": ToolDefinition(
            name="wait_for_element",
            category="condition",
            description="等待元素出现",
            parameters={
                "element": {
                    "type": "element",
                    "required": True,
                    "description": "元素信息",
                    "default": None,
                },
                "timeout": {
                    "type": "float",
                    "required": False,
                    "description": "超时时间（秒）",
                    "default": 5.0,
                },
            },
            returns={
                "type": "boolean",
                "description": "是否在超时前出现",
            },
        ),
    },
}


class BuiltinToolRegistry:
    """内置工具注册表"""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._implementations: dict[str, Callable] = {}
        self._load_builtin_tools()

    def _load_builtin_tools(self) -> None:
        """加载所有内置工具"""
        for category, tools in BUILTIN_TOOLS.items():
            for tool_name, tool_def in tools.items():
                self._tools[tool_name] = tool_def
        logger.info(f"已加载 {len(self._tools)} 个内置工具")

    def register_tool(self, tool_name: str, tool_definition: ToolDefinition) -> None:
        """注册新工具"""
        if tool_name in self._tools:
            logger.warning(f"工具 '{tool_name}' 已存在，将被覆盖")
        self._tools[tool_name] = tool_definition
        logger.info(f"已注册工具: {tool_name}")

    def register_implementation(self, tool_name: str, implementation: Callable) -> None:
        """注册工具实现"""
        self._implementations[tool_name] = implementation
        logger.debug(f"已注册工具实现: {tool_name}")

    def get_tool_by_name(self, tool_name: str) -> Optional[ToolDefinition]:
        """查询工具定义"""
        return self._tools.get(tool_name)

    def get_implementation(self, tool_name: str) -> Optional[Callable]:
        """获取工具实现"""
        return self._implementations.get(tool_name)

    def get_all_tools(self) -> list[ToolDefinition]:
        """查询所有工具"""
        return list(self._tools.values())

    def get_tools_by_category(self, category: ToolCategory) -> list[ToolDefinition]:
        """按类别查询工具"""
        return [t for t in self._tools.values() if t.category == category]

    def validate_parameters(self, tool_name: str, parameters: dict[str, Any]) -> tuple[bool, list[str]]:
        """验证工具参数"""
        tool = self.get_tool_by_name(tool_name)
        if tool is None:
            return False, [f"工具 '{tool_name}' 不存在"]

        errors = []
        for param_name, param_def in tool.parameters.items():
            if param_def["required"] and param_name not in parameters:
                errors.append(f"缺少必需参数: {param_name}")
            elif param_name in parameters:
                value = parameters[param_name]
                expected_type = param_def["type"]
                # 类型检查
                if not self._check_type(value, expected_type):
                    errors.append(f"参数 '{param_name}' 类型错误，期望 {expected_type}")

        return len(errors) == 0, errors

    def _check_type(self, value: Any, expected_type: str) -> bool:
        """检查值类型"""
        type_mapping = {
            "string": str,
            "int": int,
            "float": (int, float),
            "boolean": bool,
            "element": (dict, object),  # element可以是字典或对象
            "position": (dict, list, tuple),
            "dict": dict,
        }
        expected = type_mapping.get(expected_type, object)
        return isinstance(value, expected)

    def get_tool_categories(self) -> list[str]:
        """获取所有工具类别"""
        return ["locator", "executor", "extractor", "condition"]

    def get_tools_for_display(self) -> dict[str, list[dict[str, Any]]]:
        """获取用于UI显示的工具列表"""
        result = {}
        for category in self.get_tool_categories():
            tools = self.get_tools_by_category(category)
            result[category] = [t.to_dict() for t in tools]
        return result


# 单例注册表
_registry: Optional[BuiltinToolRegistry] = None


def get_registry() -> BuiltinToolRegistry:
    """获取注册表单例"""
    global _registry
    if _registry is None:
        _registry = BuiltinToolRegistry()
    return _registry


def get_all_builtin_tools() -> list[dict[str, Any]]:
    """获取所有内置工具（用于UI触发列表）"""
    registry = get_registry()
    return [t.to_dict() for t in registry.get_all_tools()]


def get_tool_by_name(tool_name: str) -> Optional[ToolDefinition]:
    """根据名称获取工具"""
    return get_registry().get_tool_by_name(tool_name)


def validate_tool_parameters(tool_name: str, parameters: dict[str, Any]) -> tuple[bool, list[str]]:
    """验证工具参数"""
    return get_registry().validate_parameters(tool_name, parameters)


def generate_tool_reference_template(tool_name: str) -> str:
    """根据工具名称生成Markdown引用模板"""
    tool = get_tool_by_name(tool_name)
    if tool is None:
        return f"/{tool_name}"

    template = f"使用 /{tool.name} 执行操作\n"

    if tool.parameters:
        for param_name, param_info in tool.parameters.items():
            required_str = "必需" if param_info["required"] else "可选"
            default_value = param_info.get("default", "")
            description = param_info.get("description", "")

            # 生成参数模板
            if param_info["required"]:
                param_value = f"{{user_input.{param_name}}}"
            elif default_value is not None:
                param_value = str(default_value)
            else:
                param_value = ""

            template += f"   - 参数：{param_name}=\"{param_value}\"\n"
            template += f"     # {description} ({required_str})\n"

    return template


def generate_all_tool_reference_templates() -> dict[str, str]:
    """生成所有工具的Markdown引用模板"""
    registry = get_registry()
    templates = {}

    for tool in registry.get_all_tools():
        templates[tool.name] = generate_tool_reference_template(tool.name)

    return templates


def get_tools_markdown_catalog() -> str:
    """生成工具列表的Markdown目录"""
    registry = get_registry()
    catalog = "# 内置工具列表\n\n"

    category_names = {
        "locator": "定位器",
        "executor": "执行器",
        "extractor": "提取器",
        "condition": "条件判断",
    }

    for category in registry.get_tool_categories():
        tools = registry.get_tools_by_category(category)
        if tools:
            catalog += f"## {category_names.get(category, category)}\n\n"

            for tool in tools:
                catalog += f"### /{tool.name}\n\n"
                catalog += f"{tool.description}\n\n"

                if tool.parameters:
                    catalog += "**参数：**\n\n"
                    for param_name, param_def in tool.parameters.items():
                        required_str = "必需" if param_def["required"] else "可选"
                        default_str = f", 默认: `{param_def['default']}`" if param_def["default"] is not None else ""
                        catalog += f"- `{param_name}` ({param_def['type']}, {required_str}{default_str})\n"
                        catalog += f"  - {param_def['description']}\n"

                catalog += f"\n**返回：** `{tool.returns['type']}` - {tool.returns['description']}\n\n"
                catalog += "---\n\n"

    return catalog


def _register_all_builtin_tools() -> None:
    """将所有内置自动化工具注册到统一工具注册表。"""
    from base_tool.registry import get_tool_registry

    registry = get_tool_registry()

    for category, tools in BUILTIN_TOOLS.items():
        for tool_name, tool_def in tools.items():
            registry.register_automation_tool(
                tool_name=tool_name,
                tool_definition={
                    "name": tool_name,
                    "category": category,
                    "description": tool_def.description,
                    "parameters": {
                        param_name: {
                            "type": param_info.get("type", "string"),
                            "description": param_info.get("description", ""),
                        }
                        for param_name, param_info in tool_def.parameters.items()
                    },
                },
                implementation=tool_def.implementation,
            )


_register_all_builtin_tools()