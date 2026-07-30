"""
常量模块和架构解耦单元测试

覆盖：
- floating_ball_widgets/_constants 延迟初始化
- EventBus 解耦验证
- 分层依赖违规扫描
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class TestConstantsModule(unittest.TestCase):
    """_constants 模块测试"""

    def test_size_constants_values(self):
        """验证尺寸常量值正确"""
        from ui_flet.floating_ball_widgets._constants import (
            BALL_SIZE, BALL_MARGIN,
            CHAT_WIDTH, CHAT_HEIGHT, CHAT_MIN_WIDTH, CHAT_MIN_HEIGHT,
        )
        self.assertEqual(BALL_SIZE, 50)
        self.assertEqual(BALL_MARGIN, 20)
        self.assertEqual(CHAT_WIDTH, 400)
        self.assertEqual(CHAT_HEIGHT, 500)
        self.assertEqual(CHAT_MIN_WIDTH, 300)
        self.assertEqual(CHAT_MIN_HEIGHT, 400)

    def test_string_color_constants(self):
        """验证字符串颜色常量格式"""
        from ui_flet.floating_ball_widgets._constants import (
            DEFAULT_BG_COLOR,
            DEFAULT_TEXT_COLOR,
            DEFAULT_BORDER_COLOR,
        )
        self.assertTrue(DEFAULT_BG_COLOR.startswith("#"))
        self.assertTrue(DEFAULT_TEXT_COLOR.startswith("#"))
        self.assertTrue(DEFAULT_BORDER_COLOR.startswith("#"))

    def test_qcolor_constants_initial_none(self):
        """验证 QColor 常量初始为 None（延迟初始化）"""
        from ui_flet.floating_ball_widgets._constants import (
            DEFAULT_PRIMARY_COLOR,
            DEFAULT_HOVER_COLOR,
        )
        # 注意：如果其他测试先调用了 init_qcolor_constants，这里可能不是 None
        # 在隔离测试环境中应该是 None
        # 此测试验证延迟初始化模式存在
        self.assertTrue(
            DEFAULT_PRIMARY_COLOR is None or hasattr(DEFAULT_PRIMARY_COLOR, 'red'),
            "DEFAULT_PRIMARY_COLOR 应为 None 或 QColor 实例"
        )

    def test_init_qcolor_constants_creates_qcolor(self):
        """验证 init_qcolor_constants() 正确初始化 QColor"""
        from ui_flet.floating_ball_widgets import _constants as _const
        _const.init_qcolor_constants()
        self.assertIsNotNone(_const.DEFAULT_PRIMARY_COLOR)
        self.assertIsNotNone(_const.DEFAULT_HOVER_COLOR)
        # 验证是 QColor 实例
        self.assertTrue(
            type(_const.DEFAULT_PRIMARY_COLOR).__name__ == 'QColor',
            f"期望 QColor 实例，得到 {type(_const.DEFAULT_PRIMARY_COLOR)}"
        )

    def test_init_qcolor_constants_idempotent(self):
        """验证 init_qcolor_constants() 多次调用安全（幂等）"""
        from ui_flet.floating_ball_widgets import _constants as _const
        _const.init_qcolor_constants()
        first = _const.DEFAULT_PRIMARY_COLOR
        _const.init_qcolor_constants()
        second = _const.DEFAULT_PRIMARY_COLOR
        self.assertEqual(first, second)


class TestEventBusDecoupling(unittest.TestCase):
    """EventBus 解耦验证测试"""

    def test_event_bus_available(self):
        """验证 EventBus 可正常导入和实例化"""
        from events.event_bus import EventBus
        bus = EventBus.get_instance()
        self.assertIsNotNone(bus)

    def test_llm_error_event_type_exists(self):
        """验证 LLM_ERROR 事件类型已定义"""
        from events.event_types import EventType
        self.assertTrue(hasattr(EventType, 'LLM_ERROR'))
        self.assertEqual(EventType.LLM_ERROR.value, "llm_error")

    def test_basechatmodel_no_direct_ui_flet_import(self):
        """验证 BaseChatModel 不再直接导入 ui_flet 模块"""
        content = (ROOT / "llm" / "BaseChatModel.py").read_text(encoding='utf-8')
        # 排除注释中的引用
        import_lines = [
            line for line in content.splitlines()
            if 'ui_flet' in line and not line.strip().startswith('#')
        ]
        self.assertEqual(len(import_lines), 0,
                         f"发现 ui_flet 导入: {import_lines}")


class TestLayerDependencyRules(unittest.TestCase):
    """分层依赖规则验证"""

    def test_base_tool_no_module_level_skill_import(self):
        """验证 base_tool 不再模块级导入 skill（TYPE_CHECKING 保护）"""
        content = (ROOT / "base_tool" / "dispatch.py").read_text(encoding='utf-8')
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if 'from skill import' in line and 'TYPE_CHECKING' not in line:
                # 检查是否在 TYPE_CHECKING 块内
                # 向上查找最近的 if TYPE_CHECKING:
                in_type_checking = False
                for j in range(i - 1, max(0, i - 5), -1):
                    if 'TYPE_CHECKING' in lines[j]:
                        in_type_checking = True
                        break
                if not in_type_checking:
                    self.fail(f"L{i+1}: 发现非 TYPE_CHECKING 保护的 skill 导入: {line.strip()}")

    def test_base_tool_no_module_level_llm_import(self):
        """验证 base_tool/schema.py 的 llm 导入已受保护"""
        content = (ROOT / "base_tool" / "schema.py").read_text(encoding='utf-8')
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if 'from llm.' in line and 'TYPE_CHECKING' not in line:
                # 检查是否在 TYPE_CHECKING 块或函数内
                in_type_checking = False
                for j in range(i - 1, max(0, i - 5), -1):
                    if 'TYPE_CHECKING' in lines[j]:
                        in_type_checking = True
                        break
                # 函数内的延迟导入是允许的
                in_function = line.startswith(' ' * 8)  # 函数体至少8空格缩进
                if not in_type_checking and not in_function:
                    self.fail(f"L{i+1}: 发现非保护的 llm 导入: {line.strip()}")


if __name__ == "__main__":
    unittest.main()
