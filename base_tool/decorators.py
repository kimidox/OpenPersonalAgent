"""
工具装饰器模块

提供 @atomic_tool 和 @control_tool 装饰器，用于自动注册工具定义和实现。
支持从函数签名自动提取参数定义，生成符合 OpenAI function calling 格式的 schema。
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Callable, Optional, Union, get_origin, get_args


# Python 类型到 JSON Schema类型的映射
TYPE_MAPPING = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
    Any: "object",
}

# 类型名称到 JSON Schema类型的映射（用于处理字符串形式的类型注解）
TYPE_NAME_MAPPING = {
    "str": "string",
    "string": "string",
    "int": "integer",
    "integer": "integer",
    "float": "number",
    "number": "number",
    "bool": "boolean",
    "boolean": "boolean",
    "list": "array",
    "array": "array",
    "dict": "object",
    "object": "object",
    "Any": "object",
}


@dataclass
class ToolMetadata:
    """工具元数据"""
    name: str
    description: str
    tool_type: str  # "atomic" 或 "control"
    parameters: dict  # OpenAI function calling 格式的参数定义
    required: list[str]  # 必需参数列表
    implementation: Optional[Callable] = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_definition(self) -> dict:
        """转换为工具定义格式"""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": self.parameters,
                "required": self.required,
            },
        }


class ToolRegistry:
    """统一工具注册表，管理所有工具定义和实现。

    支持两种注册方式：
    1. 装饰器注册：@atomic_tool / @control_tool
    2. 编程注册：register_from_definition
    """

    def __init__(self) -> None:
        # 主存储：{tool_name: {"definition": dict, "implementation": Callable | None}}
        self._tools: dict[str, dict] = {}
        # 向后兼容：ToolMetadata 缓存（惰性构建）
        self._atomic_tools: dict[str, ToolMetadata] = {}
        self._control_tools: dict[str, ToolMetadata] = {}
        self._implementations: dict[str, Callable] = {}
        # 加载内置工具
        self._load_builtin_tools()

    # ------------------------------------------------------------------
    # 内置工具加载
    # ------------------------------------------------------------------

    def _load_builtin_tools(self) -> None:
        """加载内置工具定义（atomic 和 control 类别）。"""
        from .definitions import ATOMIC_TOOL_DEFINITIONS, CONTROL_TOOL_DEFINITIONS

        for tool_def in ATOMIC_TOOL_DEFINITIONS:
            tool_name = tool_def.get("name", "")
            if tool_name and tool_name not in self._tools:
                self._tools[tool_name] = {
                    "definition": {
                        "name": tool_name,
                        "category": "atomic",
                        "description": tool_def.get("description", ""),
                        "parameters": tool_def.get("parameters", {}),
                    },
                    "implementation": None,
                }

        for tool_def in CONTROL_TOOL_DEFINITIONS:
            tool_name = tool_def.get("name", "")
            if tool_name and tool_name not in self._tools:
                self._tools[tool_name] = {
                    "definition": {
                        "name": tool_name,
                        "category": "control",
                        "description": tool_def.get("description", ""),
                        "parameters": tool_def.get("parameters", {}),
                    },
                    "implementation": None,
                }

    # ------------------------------------------------------------------
    # 通用注册方法（registry.py 兼容接口）
    # ------------------------------------------------------------------

    def register_tool(
        self,
        name: str | None = None,
        description: str | None = None,
        tool_type: str | None = None,
        parameters: dict | None = None,
        required: list[str] | None = None,
        implementation: Callable | None = None,
        extra: dict | None = None,
        *,
        tool_name: str | None = None,
        tool_definition: dict | None = None,
        overwrite: bool = False,
    ) -> bool | None:
        """注册工具（统一入口，兼容两种调用风格）。

        风格 A（装饰器内部使用）：
            register_tool(name, description, tool_type, parameters, required, implementation, extra)

        风格 B（registry.py 兼容）：
            register_tool(tool_name, tool_definition, implementation, overwrite)
        """
        # ---- 风格 B：tool_definition 字典 ----
        if tool_definition is not None:
            return self._register_from_definition(
                tool_name=tool_name or name or "",
                tool_definition=tool_definition,
                implementation=implementation,
                overwrite=overwrite,
            )

        # ---- 风格 A：分散参数 ----
        if name is None:
            raise ValueError("name 或 tool_name 不能为空")

        # 如果传入了 tool_type，走装饰器路径
        if tool_type is not None:
            self._register_tool_metadata(
                name=name,
                description=description or "",
                tool_type=tool_type,
                parameters=parameters or {},
                required=required or [],
                implementation=implementation,
                extra=extra or {},
            )
            return None

        # 兜底：从 tool_definition 注册（tool_name 风格）
        return self._register_from_definition(
            tool_name=name,
            tool_definition={"name": name, "description": description or "", "parameters": parameters or {}},
            implementation=implementation,
            overwrite=overwrite,
        )

    def _register_tool_metadata(
        self,
        name: str,
        description: str,
        tool_type: str,
        parameters: dict,
        required: list[str],
        implementation: Callable | None = None,
        extra: dict | None = None,
    ) -> None:
        """通过 ToolMetadata 注册工具（装饰器路径）。"""
        metadata = ToolMetadata(
            name=name,
            description=description,
            tool_type=tool_type,
            parameters=parameters,
            required=required,
            implementation=implementation,
            extra=extra or {},
        )

        # 同步到 _tools 主存储
        category = tool_type  # "atomic" or "control"
        self._tools[name] = {
            "definition": {
                "name": name,
                "category": category,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": parameters,
                    "required": required,
                },
            },
            "implementation": implementation,
        }

        # 同步到 ToolMetadata 缓存
        if tool_type == "atomic":
            self._atomic_tools[name] = metadata
        elif tool_type == "control":
            self._control_tools[name] = metadata
        else:
            raise ValueError(f"未知的工具类型: {tool_type}")

        if implementation is not None:
            self._implementations[name] = implementation

    def _register_from_definition(
        self,
        tool_name: str,
        tool_definition: dict,
        implementation: Callable | None = None,
        overwrite: bool = False,
    ) -> bool:
        """从定义字典注册工具（内部实现）。"""
        import warnings as _w

        required_fields = ["name", "category", "description"]
        for f in required_fields:
            if f not in tool_definition:
                raise ValueError(f"工具定义缺少必需字段: {f}")

        if tool_definition.get("name") != tool_name:
            raise ValueError(
                f"工具定义的 name ({tool_definition.get('name')}) 与 tool_name ({tool_name}) 不一致"
            )

        if tool_name in self._tools and not overwrite:
            _w.warn(
                f"工具 '{tool_name}' 已存在，如需覆盖请设置 overwrite=True",
                UserWarning,
            )
            return False

        # overwrite=True 时静默覆盖（不警告），因为这是正常的实现绑定流程

        self._tools[tool_name] = {
            "definition": {
                "name": tool_name,
                "category": tool_definition.get("category", "atomic"),
                "description": tool_definition.get("description", ""),
                "parameters": tool_definition.get("parameters", {}),
            },
            "implementation": implementation,
        }

        # 同步到 ToolMetadata 缓存
        category = tool_definition.get("category", "atomic")
        params = tool_definition.get("parameters", {})
        if isinstance(params, dict) and "properties" in params:
            properties = params["properties"]
            req = params.get("required", [])
        else:
            properties = params
            req = []

        metadata = ToolMetadata(
            name=tool_name,
            description=tool_definition.get("description", ""),
            tool_type=category,
            parameters=properties if isinstance(properties, dict) else {},
            required=req if isinstance(req, list) else [],
            implementation=implementation,
        )
        if category == "atomic":
            self._atomic_tools[tool_name] = metadata
        elif category == "control":
            self._control_tools[tool_name] = metadata

        if implementation is not None:
            self._implementations[tool_name] = implementation

        return True

    # ------------------------------------------------------------------
    # 公共注册方法
    # ------------------------------------------------------------------

    def register_from_definition(
        self,
        tool_name: str,
        tool_definition: dict,
        implementation: Callable | None = None,
        overwrite: bool = False,
    ) -> bool:
        """从定义字典注册工具（不通过装饰器）。

        Args:
            tool_name: 工具名称
            tool_definition: 工具定义字典，包含 name、category、description、parameters
            implementation: 工具实现函数（可选）
            overwrite: 是否覆盖已存在的工具

        Returns:
            bool: 注册是否成功
        """
        return self._register_from_definition(tool_name, tool_definition, implementation, overwrite)

    # ------------------------------------------------------------------
    # 查询方法（装饰器 API）
    # ------------------------------------------------------------------

    def get_atomic_tool(self, name: str) -> Optional[ToolMetadata]:
        """获取原子工具（ToolMetadata）。"""
        self._sync_metadata_cache()
        return self._atomic_tools.get(name)

    def get_control_tool(self, name: str) -> Optional[ToolMetadata]:
        """获取控制工具（ToolMetadata）。"""
        self._sync_metadata_cache()
        return self._control_tools.get(name)

    def get_tool(self, name: str) -> Optional[ToolMetadata]:
        """获取工具（不限类型，返回 ToolMetadata）。"""
        self._sync_metadata_cache()
        return self._atomic_tools.get(name) or self._control_tools.get(name)

    def get_implementation(self, name: str) -> Optional[Callable]:
        """获取工具实现。"""
        return self._implementations.get(name)

    def get_all_atomic_tools(self) -> list[ToolMetadata]:
        """获取所有原子工具（ToolMetadata 列表）。"""
        self._sync_metadata_cache()
        return list(self._atomic_tools.values())

    def get_all_control_tools(self) -> list[ToolMetadata]:
        """获取所有控制工具（ToolMetadata 列表）。"""
        self._sync_metadata_cache()
        return list(self._control_tools.values())

    def get_atomic_definitions(self) -> list[dict]:
        """获取所有原子工具定义。"""
        return [t.to_definition() for t in self.get_all_atomic_tools()]

    def get_control_definitions(self) -> list[dict]:
        """获取所有控制工具定义。"""
        return [t.to_definition() for t in self.get_all_control_tools()]

    def get_catalog(self) -> dict[str, str]:
        """获取工具目录（简要描述）。"""
        catalog = {}
        for tool in self.get_all_atomic_tools():
            catalog[tool.name] = tool.description.split("\n")[0]
        for tool in self.get_all_control_tools():
            catalog[tool.name] = tool.description.split("\n")[0]
        return catalog

    # ------------------------------------------------------------------
    # 查询方法（registry.py 兼容 API）
    # ------------------------------------------------------------------

    def unregister_tool(self, tool_name: str) -> bool:
        """从注册表中删除工具。"""
        import warnings as _w

        if tool_name not in self._tools:
            _w.warn(f"工具 '{tool_name}' 不存在", UserWarning)
            return False

        builtin_names = self._get_builtin_tool_names()
        if tool_name in builtin_names:
            _w.warn(f"工具 '{tool_name}' 是内置工具，不允许删除", UserWarning)
            return False

        del self._tools[tool_name]
        self._atomic_tools.pop(tool_name, None)
        self._control_tools.pop(tool_name, None)
        self._implementations.pop(tool_name, None)
        return True

    def _get_builtin_tool_names(self) -> set[str]:
        """获取内置工具名称集合。"""
        from .definitions import ATOMIC_TOOL_DEFINITIONS, CONTROL_TOOL_DEFINITIONS

        names: set[str] = set()
        for td in ATOMIC_TOOL_DEFINITIONS:
            names.add(td.get("name", ""))
        for td in CONTROL_TOOL_DEFINITIONS:
            names.add(td.get("name", ""))
        return names

    def get_tool_by_name(self, tool_name: str) -> Optional[dict]:
        """根据名称获取工具定义和实现（返回 {definition, implementation} 字典）。"""
        return self._tools.get(tool_name)

    def get_tool_definition(self, tool_name: str) -> Optional[dict]:
        """根据名称获取工具定义（不含实现）。"""
        info = self._tools.get(tool_name)
        if info:
            return info.get("definition")
        return None

    def get_tool_implementation(self, tool_name: str) -> Optional[Callable]:
        """根据名称获取工具实现函数。"""
        info = self._tools.get(tool_name)
        if info:
            return info.get("implementation")
        return None

    def get_all_tools(self) -> list[dict]:
        """获取所有工具信息列表（{definition, implementation} 格式）。"""
        return list(self._tools.values())

    def get_all_tool_definitions(self) -> list[dict]:
        """获取所有工具定义列表（不含实现）。"""
        return [info.get("definition") for info in self._tools.values()]

    def get_all_tools_flat(self) -> list[dict]:
        """返回所有工具的扁平列表（包括 atomic、control 类别）。

        每个元素为扁平化字典，包含 name、category、description、parameters、implementation。
        """
        result = []
        for info in self._tools.values():
            defn = info.get("definition", {})
            flat = {
                "name": defn.get("name", ""),
                "category": defn.get("category", ""),
                "description": defn.get("description", ""),
                "parameters": defn.get("parameters", {}),
                "implementation": info.get("implementation"),
            }
            result.append(flat)
        return result

    def get_tools_by_category(self, category: str) -> list[dict]:
        """根据类别获取工具信息列表。"""
        result = []
        for info in self._tools.values():
            if info.get("definition", {}).get("category") == category:
                result.append(info)
        return result

    def get_tool_definitions_by_category(self, category: str) -> list[dict]:
        """根据类别获取工具定义列表（不含实现）。"""
        result = []
        for info in self._tools.values():
            defn = info.get("definition", {})
            if defn.get("category") == category:
                result.append(defn)
        return result

    def get_tool_categories(self) -> list[str]:
        """获取所有工具类别列表。"""
        categories: set[str] = set()
        for info in self._tools.values():
            cat = info.get("definition", {}).get("category")
            if cat:
                categories.add(cat)
        return sorted(categories)

    def has_tool(self, tool_name: str) -> bool:
        """检查工具是否已注册。"""
        return tool_name in self._tools

    def get_tool_names(self) -> list[str]:
        """获取所有工具名称列表。"""
        return list(self._tools.keys())

    def get_tool_count(self) -> int:
        """获取已注册工具数量。"""
        return len(self._tools)

    def clear_custom_tools(self) -> int:
        """清除所有自定义工具（保留内置工具）。"""
        builtin_names = self._get_builtin_tool_names()
        custom = [n for n in self._tools if n not in builtin_names]
        count = len(custom)
        for n in custom:
            del self._tools[n]
            self._atomic_tools.pop(n, None)
            self._control_tools.pop(n, None)
            self._implementations.pop(n, None)
        return count

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    def _sync_metadata_cache(self) -> None:
        """将 _tools 主存储同步到 _atomic_tools / _control_tools ToolMetadata 缓存。"""
        for name, info in self._tools.items():
            defn = info.get("definition", {})
            category = defn.get("category", "")
            if category in ("atomic", "control") and name not in (
                self._atomic_tools if category == "atomic" else self._control_tools
            ):
                params = defn.get("parameters", {})
                if isinstance(params, dict) and "properties" in params:
                    properties = params["properties"]
                    req = params.get("required", [])
                else:
                    properties = params
                    req = []
                metadata = ToolMetadata(
                    name=name,
                    description=defn.get("description", ""),
                    tool_type=category,
                    parameters=properties if isinstance(properties, dict) else {},
                    required=req if isinstance(req, list) else [],
                    implementation=info.get("implementation"),
                )
                if category == "atomic":
                    self._atomic_tools[name] = metadata
                else:
                    self._control_tools[name] = metadata


# 单例注册表
_registry: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    """获取工具注册表单例"""
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry


def _get_json_type(python_type: Any) -> str:
    """
    将 Python 类型转换为 JSON Schema 类型。

    Args:
        python_type: Python 类型注解

    Returns:
        JSON Schema 类型字符串
    """
    # 处理字符串形式的类型注解
    if isinstance(python_type, str):
        return TYPE_NAME_MAPPING.get(python_type, "object")

    # 处理 None 类型
    if python_type is None or python_type is type(None):
        return "object"

    # 处理 Optional 类型（Union[X, None]）
    origin = get_origin(python_type)
    if origin is Union:
        args = get_args(python_type)
        # 过滤掉 None，取第一个非 None 类型
        non_none_args = [a for a in args if a is not type(None)]
        if non_none_args:
            return _get_json_type(non_none_args[0])
        return "object"

    # 处理 List 类型
    if origin is list:
        args = get_args(python_type)
        if args:
            item_type = _get_json_type(args[0])
            return "array"
        return "array"

    # 处理 Dict 类型
    if origin is dict:
        return "object"

    # 直接类型映射
    if python_type in TYPE_MAPPING:
        return TYPE_MAPPING[python_type]

    # 尝试通过类型名称查找
    type_name = getattr(python_type, "__name__", None)
    if type_name:
        return TYPE_NAME_MAPPING.get(type_name, "object")

    return "object"


def extract_parameters_from_func(func: Callable) -> tuple[dict, list[str]]:
    """
    从函数签名提取参数定义。

    Args:
        func: 要提取参数的函数

    Returns:
        tuple: (参数定义字典, 必需参数列表)
        参数定义字典格式为 OpenAI function calling 格式：
        {
            "param_name": {
                "type": "string",
                "description": "参数描述"
            },
            ...
        }
    """
    sig = inspect.signature(func)
    parameters = {}
    required = []

    for param_name, param in sig.parameters.items():
        # 跳过 self 和 cls 参数
        if param_name in ("self", "cls"):
            continue

        # 获取参数类型
        param_type = _get_json_type(param.annotation)

        # 构建参数定义
        param_def = {
            "type": param_type,
            "description": f"参数: {param_name}",
        }

        # 处理 List 类型，添加 items 定义
        origin = get_origin(param.annotation)
        if origin is list:
            args = get_args(param.annotation)
            if args:
                item_type = _get_json_type(args[0])
                param_def["items"] = {"type": item_type}

        # 处理默认值
        if param.default is inspect.Parameter.empty:
            # 无默认值，是必需参数
            required.append(param_name)
        else:
            # 有默认值，记录默认值（可选）
            # 注意：OpenAI function calling 不支持 default 字段，
            # 但我们可以在 extra 中记录
            param_def["_default"] = param.default

        parameters[param_name] = param_def

    return parameters, required


def _create_tool_decorator(
    tool_type: str,
    name: str,
    description: str,
    extra: Optional[dict] = None,
) -> Callable:
    """
    创建工具装饰器的通用实现。

    Args:
        tool_type: 工具类型 ("atomic" 或 "control")
        name: 工具名称
        description: 工具描述
        extra: 额外元数据

    Returns:
        装饰器函数
    """
    def decorator(func: Callable) -> Callable:
        # 提取参数定义
        parameters, required = extract_parameters_from_func(func)

        # 创建工具元数据
        metadata = ToolMetadata(
            name=name,
            description=description,
            tool_type=tool_type,
            parameters=parameters,
            required=required,
            implementation=func,
            extra=extra or {},
        )

        # 注册到注册表
        registry = get_tool_registry()
        registry.register_tool(
            name=name,
            description=description,
            tool_type=tool_type,
            parameters=parameters,
            required=required,
            implementation=func,
            extra=extra or {},
        )

        # 在函数上添加元数据属性
        func._tool_metadata = metadata

        # 保持函数原有功能不变
        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        # 将元数据也复制到 wrapper 上
        wrapper._tool_metadata = metadata

        return wrapper

    return decorator


def atomic_tool(
    name: str,
    description: str,
    extra: Optional[dict] = None,
) -> Callable:
    """
    原子工具装饰器。

    用于注册原子工具（执行具体操作的工具）。
    从函数签名自动提取参数定义，生成符合 OpenAI function calling 格式的 schema。

    Args:
        name: 工具名称
        description: 工具描述
        extra: 额外元数据（可选）

    Returns:
        装饰器函数

    Example:
        @atomic_tool(
            name="read_file",
            description="读取文件内容。参数：path(必需)，文件路径。",
        )
        def read_file(path: str, encoding: str = "utf-8") -> str:
            with open(path, "r", encoding=encoding) as f:
                return f.read()

        # 自动生成的参数定义：
        # {
        #     "name": "read_file",
        #     "description": "读取文件内容...",
        #     "parameters": {
        #         "type": "object",
        #         "properties": {
        #             "path": {"type": "string", "description": "参数: path"},
        #             "encoding": {"type": "string", "description": "参数: encoding"}
        #         },
        #         "required": ["path"]
        #     }
        # }
    """
    return _create_tool_decorator("atomic", name, description, extra)


def control_tool(
    name: str,
    description: str,
    extra: Optional[dict] = None,
) -> Callable:
    """
    控制工具装饰器。

    用于注册控制工具（控制对话流程的工具，如 finish、ask_user 等）。
    从函数签名自动提取参数定义，生成符合 OpenAI function calling 格式的 schema。

    Args:
        name: 工具名称
        description: 工具描述
        extra: 额外元数据（可选）

    Returns:
        装饰器函数

    Example:
        @control_tool(
            name="finish",
            description="完成任务，向用户提供最终答复。",
        )
        def finish(message: str) -> dict:
            return {"status": "completed", "message": message}

        # 自动生成的参数定义：
        # {
        #     "name": "finish",
        #     "description": "完成任务...",
        #     "parameters": {
        #         "type": "object",
        #         "properties": {
        #             "message": {"type": "string", "description": "参数: message"}
        #         },
        #         "required": ["message"]
        #     }
        # }
    """
    return _create_tool_decorator("control", name, description, extra)


# 导出所有公共接口
__all__ = [
    "ToolRegistry",
    "ToolMetadata",
    "get_tool_registry",
    "extract_parameters_from_func",
    "atomic_tool",
    "control_tool",
]