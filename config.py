import os

import dotenv

from resource_path import paths


def get_config(key: str):
    import shutil

    if paths.is_frozen:
        # 用户配置路径
        user_env = paths.user_data_dir / ".env"
        # 默认配置路径（打包内部）
        default_env = paths.get_bundled_resource(".env")

        # 首次运行：复制默认配置到用户目录
        if not user_env.exists() and default_env.exists():
            shutil.copy(default_env, user_env)

        # 优先读取用户配置
        env_path = user_env if user_env.exists() else default_env
    else:
        env_path = paths.project_root / ".env"

    if env_path.is_file():
        dotenv.load_dotenv(str(env_path))
        return dotenv.get_key(dotenv_path=str(env_path), key_to_get=key)
    return None
OPENAI_API_KEY = get_config("OPENAI_API_KEY")
OPENAI_BASE_URL = get_config("OPENAI_BASE_URL")
MODEL_NAME = get_config("MODEL_NAME")
MAX_ITERATIONS = 20

_ms = get_config("SKILL_AGENT_MAX_STEPS")
try:
    SKILL_AGENT_MAX_STEPS = int(_ms) if _ms not in (None, "") else 50
except (TypeError, ValueError):
    SKILL_AGENT_MAX_STEPS = 50
if SKILL_AGENT_MAX_STEPS < 1:
    SKILL_AGENT_MAX_STEPS = 50


def _env_bool(raw, default: bool) -> bool:
    if raw is None or str(raw).strip() == "":
        return default
    s = str(raw).strip().lower()
    if s in ("0", "false", "no", "off"):
        return False
    if s in ("1", "true", "yes", "on"):
        return True
    try:
        return bool(int(s))
    except ValueError:
        return default


_show_tools = get_config("SKILL_AGENT_UI_SHOW_TOOL_CALLS")
SKILL_AGENT_UI_SHOW_TOOL_CALLS = _env_bool(_show_tools, True)

WORKER_DIR = str(paths.personal_data_dir)
SKILLS_DIR = str(paths.get_skills_dir())

_auto_load = get_config("SKILL_AGENT_AUTO_LOAD")
SKILL_AGENT_AUTO_LOAD = _env_bool(_auto_load, True)
DEFAULT_SKILL_AGENT_USER = get_config("DEFAULT_SKILL_AGENT_USER")


_gs = get_config("SCREENSHOT_GRID_STEP_PX")
try:
    SCREENSHOT_GRID_STEP_PX = int(_gs) if _gs not in (None, "") else 32
except (TypeError, ValueError):
    SCREENSHOT_GRID_STEP_PX = 32
if SCREENSHOT_GRID_STEP_PX < 1:
    SCREENSHOT_GRID_STEP_PX = 32

_cws = get_config("CONTEXT_WINDOW_SIZE")
try:
    CONTEXT_WINDOW_SIZE = int(_cws) if _cws not in (None, "") else 128000
except (TypeError, ValueError):
    CONTEXT_WINDOW_SIZE = 128000
if CONTEXT_WINDOW_SIZE < 1:
    CONTEXT_WINDOW_SIZE = 128000

_ct = get_config("COMPACTION_THRESHOLD")
try:
    COMPACTION_THRESHOLD = float(_ct) if _ct not in (None, "") else 0.8
except (TypeError, ValueError):
    COMPACTION_THRESHOLD = 0.8
if COMPACTION_THRESHOLD <= 0 or COMPACTION_THRESHOLD > 1:
    COMPACTION_THRESHOLD = 0.8

_ckr = get_config("COMPACTION_KEEP_RECENT")
try:
    COMPACTION_KEEP_RECENT = int(_ckr) if _ckr not in (None, "") else 10
except (TypeError, ValueError):
    COMPACTION_KEEP_RECENT = 10
if COMPACTION_KEEP_RECENT < 0:
    COMPACTION_KEEP_RECENT = 10

_ce = get_config("COMPACTION_ENABLED")
COMPACTION_ENABLED = _env_bool(_ce, True)

_tue = get_config("TOKEN_USAGE_ENABLED")
TOKEN_USAGE_ENABLED = _env_bool(_tue, True)

_tusiu = get_config("TOKEN_USAGE_SHOW_IN_UI")
TOKEN_USAGE_SHOW_IN_UI = _env_bool(_tusiu, True)
