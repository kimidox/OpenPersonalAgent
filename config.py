import os

import dotenv

from resource_path import paths


env_file='.env'

def get_config(key: str):
    import shutil

    if paths.is_frozen:
        # 用户配置路径
        user_env = paths.user_data_dir /env_file
        # 默认配置路径（打包内部）
        default_env = paths.get_bundled_resource(env_file)

        # 首次运行：复制默认配置到用户目录
        if not user_env.exists() and default_env.exists():
            shutil.copy(default_env, user_env)

        # 优先读取用户配置
        env_path = user_env if user_env.exists() else default_env
    else:
        env_path = paths.project_root / env_file

    if env_path.is_file():
        dotenv.load_dotenv(str(env_path))
        return dotenv.get_key(dotenv_path=str(env_path), key_to_get=key)
    return None


def set_config(key: str, value: str):
    import shutil

    if paths.is_frozen:
        # 用户配置路径
        user_env = paths.user_data_dir / env_file
        # 默认配置路径（打包内部）
        default_env = paths.get_bundled_resource(env_file)

        # 确保用户配置存在
        if not user_env.exists() and default_env.exists():
            shutil.copy(default_env, user_env)

        env_path = user_env
    else:
        env_path = paths.project_root / env_file

    # 确保目录存在
    env_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 使用 dotenv 设置键值
    success = dotenv.set_key(dotenv_path=str(env_path), key_to_set=key, value_to_set=str(value))
    return success
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

# ===== 重复工具调用检测配置 =====

_tde = get_config("TOOL_CALL_DEDUPLICATION_ENABLED")
TOOL_CALL_DEDUPLICATION_ENABLED = _env_bool(_tde, True)

_mcr = get_config("MAX_CONSECUTIVE_REPEATS")
try:
    MAX_CONSECUTIVE_REPEATS = int(_mcr) if _mcr not in (None, "") else 3
except (TypeError, ValueError):
    MAX_CONSECUTIVE_REPEATS = 3
if MAX_CONSECUTIVE_REPEATS < 1:
    MAX_CONSECUTIVE_REPEATS = 3

_rdsw = get_config("REPEAT_DETECTION_WINDOW_SIZE")
try:
    REPEAT_DETECTION_WINDOW_SIZE = int(_rdsw) if _rdsw not in (None, "") else 10
except (TypeError, ValueError):
    REPEAT_DETECTION_WINDOW_SIZE = 10
if REPEAT_DETECTION_WINDOW_SIZE < 1:
    REPEAT_DETECTION_WINDOW_SIZE = 10

_tusiu = get_config("TOKEN_USAGE_SHOW_IN_UI")
TOKEN_USAGE_SHOW_IN_UI = _env_bool(_tusiu, True)

_msl = get_config("MEMORY_SEARCH_LIMIT")
try:
    MEMORY_SEARCH_LIMIT = int(_msl) if _msl not in (None, "") else 5
except (TypeError, ValueError):
    MEMORY_SEARCH_LIMIT = 5
if MEMORY_SEARCH_LIMIT < 1:
    MEMORY_SEARCH_LIMIT = 5

_mms = get_config("MEMORY_MIN_SCORE")
try:
    MEMORY_MIN_SCORE = float(_mms) if _mms not in (None, "") else 0.0
except (TypeError, ValueError):
    MEMORY_MIN_SCORE = 0.0
if MEMORY_MIN_SCORE < 0:
    MEMORY_MIN_SCORE = 0.0

_msr = get_config("MEMORY_SEARCH_ENABLED")
MEMORY_SEARCH_ENABLED = _env_bool(_msr, True)

_ww = get_config("WINDOW_WIDTH")
try:
    WINDOW_WIDTH = int(_ww) if _ww not in (None, "") else 780
except (TypeError, ValueError):
    WINDOW_WIDTH = 780
if WINDOW_WIDTH < 400:
    WINDOW_WIDTH = 780

_wh = get_config("WINDOW_HEIGHT")
try:
    WINDOW_HEIGHT = int(_wh) if _wh not in (None, "") else 620
except (TypeError, ValueError):
    WINDOW_HEIGHT = 620
if WINDOW_HEIGHT < 300:
    WINDOW_HEIGHT = 620

_cbet = get_config("COPY_BUTTON_ENABLED_TYPES")
if _cbet is None or str(_cbet).strip() == "":
    # COPY_BUTTON_ENABLED_TYPES = {"user", "assistant", "tool", "think", "tool_call"}
    COPY_BUTTON_ENABLED_TYPES = {"user", "assistant"}
else:
    COPY_BUTTON_ENABLED_TYPES = set(t.strip().lower() for t in str(_cbet).split(",") if t.strip())

# ===== 危险命令检测配置 =====

# 是否启用危险命令检测（true/false）
_dce = get_config("DANGEROUS_COMMAND_CHECK_ENABLED")
DANGEROUS_COMMAND_CHECK_ENABLED = _env_bool(_dce, True)

# 危险命令前缀列表（匹配命令开头），每行一个
_dcp = get_config("DANGEROUS_COMMAND_PREFIXES")
if _dcp is None or str(_dcp).strip() == "":
    DANGEROUS_COMMAND_PREFIXES = [
        "del ", "erase ", "rmdir ", "rd ", "copy ", "move ", "ren ", "rename ", "mkdir ", "md ",
    ]
else:
    DANGEROUS_COMMAND_PREFIXES = [p.strip() for p in str(_dcp).split("\n") if p.strip()]

# 危险命令包含模式列表（匹配命令任意位置），每行一个
_dcc = get_config("DANGEROUS_COMMAND_CONTAINS")
if _dcc is None or str(_dcc).strip() == "":
    DANGEROUS_COMMAND_CONTAINS = [
        " > ", " >> ", " >", " >>", " set-content ", " set-content-",
        " add-content ", " add-content-", " out-file ", " out-file-",
        " new-item ", " new-item-", " remove-item ", " remove-item-", " rm ",
    ]
else:
    DANGEROUS_COMMAND_CONTAINS = [p.strip() for p in str(_dcc).split("\n") if p.strip()]
