"""
ToolHandler 基类定义

每个原子工具分支从 execute_atomic_tool 拆出后，实现为 ToolHandler 子类。
子类只需实现 execute() 方法，内部逻辑与原 if 分支完全一致。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..context import ToolContext


class ToolHandler(ABC):
    """原子工具处理器基类。

    每个工具分支从 execute_atomic_tool 中拆出后，实现为 ToolHandler 子类。
    子类只需实现 name 属性和 execute() 方法，内部逻辑与原 if 分支完全一致。

    Business purpose:
        定义原子工具处理器的标准接口，支持注册表式分发替代巨型 if/elif 链。

    Modification notes:
        新增工具时，创建新的 ToolHandler 子类并在模块底部调用 register_handler() 即可。
        无需修改 dispatch.py 的分发逻辑。

    Related tests:
        tests/test_dispatch_handlers.py (待补充)
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """工具名称标识符，对应 dispatch 时的 name 参数。"""
        ...

    @abstractmethod
    def execute(self, args: dict, ctx: ToolContext, registry) -> str:
        """执行工具逻辑。

        Args:
            args: LLM 传入的工具参数字典
            ctx: 工具上下文（工作目录、权限、文件上传控制器等）
            registry: Skill 注册表（可选，部分工具需要用于路径解析和依赖安装）

        Returns:
            工具执行结果字符串（与原 execute_atomic_tool 分支返回值完全一致）

        Key branches:
            各子类内部可能按 action、method 等参数进一步分支

        Side effects:
            取决于具体工具：可能读写文件、执行命令、修改UI元素等

        Exceptions:
            各子类内部捕获异常并返回错误字符串，不向调用方抛出

        Related tests:
            tests/test_dispatch_handlers.py (待补充)
        """
        ...
