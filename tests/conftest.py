"""
测试基础设施：共享 fixture 和 sys.path 配置。

所有测试文件共享此 conftest.py，无需各自设置 sys.path。
"""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# 确保项目根目录在 sys.path 中
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ── 路径 fixture ──────────────────────────────────────────────

@pytest.fixture
def root_path() -> Path:
    """项目根目录 Path。"""
    return ROOT


# ── ToolContext fixture ───────────────────────────────────────

@pytest.fixture
def tool_ctx(tmp_path):
    """最小化 ToolContext，work_dir 指向临时目录。"""
    from base_tool.context import ToolContext
    return ToolContext(work_dir=str(tmp_path))


# ── SkillAgent fixture ────────────────────────────────────────

@pytest.fixture
def skill_agent_minimal(tmp_path):
    """最小化 SkillAgent 实例，不依赖真实 LLM / Memory / Executor。

    - work_dir 使用临时目录，避免真实文件系统写入
    - memory=None，不持久化消息
    - executor=None，不执行命令
    - skills_dir 指向临时空目录
    """
    from skill_agent import SkillAgent

    # 创建空的 skills 目录和 builtin skills 目录，避免 SkillRegistry 报错
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    builtin_dir = tmp_path / "builtin_skills"
    builtin_dir.mkdir()

    # patch config 中的路径配置
    with patch("config.SKILLS_DIR", str(skills_dir)), \
         patch("config.BUILTIN_SKILLS_DIR", str(builtin_dir)), \
         patch("config.SKILL_AGENT_MAX_STEPS", 5):
        agent = SkillAgent(
            work_dir=str(tmp_path),
            skills_dir=str(skills_dir),
            username="test_user",
        )
    return agent


# ── Config mock fixture ───────────────────────────────────────

@pytest.fixture
def dangerous_check_enabled():
    """config.DANGEROUS_COMMAND_CHECK_ENABLED = True。"""
    with patch("config.DANGEROUS_COMMAND_CHECK_ENABLED", True):
        yield


@pytest.fixture
def dangerous_check_disabled():
    """config.DANGEROUS_COMMAND_CHECK_ENABLED = False。"""
    with patch("config.DANGEROUS_COMMAND_CHECK_ENABLED", False):
        yield


@pytest.fixture
def dedup_enabled():
    """config.TOOL_CALL_DEDUPLICATION_ENABLED = True。"""
    with patch("config.TOOL_CALL_DEDUPLICATION_ENABLED", True):
        yield


@pytest.fixture
def dedup_disabled():
    """config.TOOL_CALL_DEDUPLICATION_ENABLED = False。"""
    with patch("config.TOOL_CALL_DEDUPLICATION_ENABLED", False):
        yield


@pytest.fixture
def repeat_settings():
    """config 重复检测设置：MAX_CONSECUTIVE_REPEATS=3, REPEAT_DETECTION_WINDOW_SIZE=10。"""
    with patch("config.MAX_CONSECUTIVE_REPEATS", 3), \
         patch("config.REPEAT_DETECTION_WINDOW_SIZE", 10):
        yield
