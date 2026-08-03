"""
Handler 注册表与自动注册机制

通过全局注册表将工具名映射到 ToolHandler 实例，
替代 execute_atomic_tool 中的巨型 if/elif 链。

Business purpose:
    提供 Handler 注册、查询和自动发现机制。

Modification notes:
    新增 Handler 模块后，在 _auto_register_all() 中添加导入行即可。
    每个 Handler 模块在导入时自动调用 register_handler() 完成注册。

Related tests:
    tests/test_dispatch_handlers.py (待补充)
"""
from __future__ import annotations

from typing import Dict, Optional, TYPE_CHECKING

from .base import ToolHandler

if TYPE_CHECKING:
    pass

# 全局 Handler 注册表：工具名 -> Handler 实例
_HANDLER_REGISTRY: Dict[str, ToolHandler] = {}


def register_handler(handler: ToolHandler) -> None:
    """注册一个工具处理器到全局注册表。

    Args:
        handler: ToolHandler 实例，其 name 属性作为注册键

    Side effects:
        修改全局 _HANDLER_REGISTRY 字典

    Related tests:
        tests/test_dispatch_handlers.py (待补充)
    """
    _HANDLER_REGISTRY[handler.name] = handler


def get_handler(name: str) -> Optional[ToolHandler]:
    """根据工具名获取处理器。

    Args:
        name: 工具名称，对应 execute_atomic_tool 的 name 参数

    Returns:
        对应的 ToolHandler 实例，未找到时返回 None
    """
    return _HANDLER_REGISTRY.get(name)


def get_all_handlers() -> Dict[str, ToolHandler]:
    """获取所有已注册的处理器的副本。"""
    return dict(_HANDLER_REGISTRY)


def _auto_register_all() -> None:
    """自动导入并注册所有 handler 模块。

    每个模块在导入时自动调用 register_handler()，将自身注册到全局注册表。
    此函数在首次调用 get_handler() 时触发，避免模块加载时的循环导入。

    Side effects:
        修改全局 _HANDLER_REGISTRY，导入所有 handler 子模块
    """
    from . import (
        file_operation,
        edit,
        run_command,
        scheduled_tasks,
        uploaded_files,
        hotkey,
        skill_management,
    )


# 标记是否已执行自动注册
_AUTO_REGISTERED = False


def ensure_registered() -> None:
    """确保所有 Handler 已注册（幂等）。

    首次调用时触发 _auto_register_all()，后续调用为空操作。
    """
    global _AUTO_REGISTERED
    if not _AUTO_REGISTERED:
        _auto_register_all()
        _AUTO_REGISTERED = True
