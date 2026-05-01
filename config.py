import os


def get_config(key:str):
    import dotenv

    dotenv.load_dotenv()
    return dotenv.get_key(dotenv_path=".env",key_to_get=key)

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


# 为 False 时：SkillAgent 界面不显示「工具」行，也不显示 select_skill / 自动加载 的「Skill 文档」块。
_show_tools = get_config("SKILL_AGENT_UI_SHOW_TOOL_CALLS")
SKILL_AGENT_UI_SHOW_TOOL_CALLS = _env_bool(_show_tools, True)
WORKER_DIR=os.path.join(os.path.dirname(os.path.abspath(__file__)),str(get_config("WORKER_DIR")))
SKILLS_DIR=os.path.join(WORKER_DIR,str(get_config("SKILLS_DIR")))
# 为 False 时：不在每轮开头按 auto_load / description 匹配自动注入 Skill（仅依赖模型 select_skill）。
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

