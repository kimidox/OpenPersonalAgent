from __future__ import annotations

"""
【统一工具注册表模块】

本模块提供统一的工具注册和管理机制，用于：
1. 管理所有工具定义和实现
2. 提供工具注册、查询、删除方法
3. 支持按类别查询工具（atomic、control、locator、executor等）

工具定义格式：
- name: 工具名称
- category: 工具类别（atomic、control等）
- description: 工具描述
- parameters: 参数定义（OpenAI function calling格式）
- implementation: 工具实现函数（可选）

使用示例：
    registry = get_tool_registry()
    
    # 注册工具
    registry.register_from_definition(
        tool_name="my_tool",
        tool_definition={
            "name": "my_tool",
            "category": "atomic",
            "description": "我的自定义工具",
            "parameters": {...}
        },
        implementation=my_tool_function
    )
    
    # 查询工具
    tool = registry.get_tool_by_name("my_tool")
    all_tools = registry.get_all_tools()
    atomic_tools = registry.get_tools_by_category("atomic")
"""

from typing import Optional

# 从 decorators.py 导入统一的 ToolRegistry 类和单例
from .decorators import ToolRegistry


def get_tool_registry() -> ToolRegistry:
    """
    获取工具注册表单例实例（委托给 decorators.py 中的单例）。

    Returns:
        ToolRegistry: 工具注册表实例
    """
    from .decorators import get_tool_registry as _get
    return _get()


def reset_tool_registry() -> None:
    """
    重置工具注册表（主要用于测试）。

    注意：此操作会清除所有已注册的工具，包括内置工具。
    """
    from . import decorators as _dec_module
    _dec_module._registry = None


# 向后兼容别名
ToolRegistryClass = ToolRegistry

__all__ = [
    "ToolRegistry",
    "ToolRegistryClass",
    "get_tool_registry",
    "reset_tool_registry",
]