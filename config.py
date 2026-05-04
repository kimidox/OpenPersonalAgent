import os

from resource_path import paths


def get_config(key: str):
    import dotenv

    if paths.is_frozen:
        env_path = paths.project_root / ".env"
        if not env_path.is_file():
            env_path = paths.get_bundled_resource(".env")
        if env_path.is_file():
            dotenv.load_dotenv(str(env_path))
        return dotenv.get_key(dotenv_path=str(env_path), key_to_get=key)
    dotenv.load_dotenv()
    return dotenv.get_key(dotenv_path=".env", key_to_get=key)

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
