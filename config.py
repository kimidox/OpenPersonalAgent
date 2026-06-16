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
BUILTIN_SKILLS_DIR = str(paths.get_builtin_skills_dir())

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

# ===== 输入规划分类配置 =====

# 是否启用输入规划分类（true/false，默认 True）
# 启用后：在工具执行前先判断输入是否需要规划，简单输入直接回复
# 禁用后：保持原有行为，所有输入直接进入工具执行循环
_ice = get_config("INPUT_CLASSIFICATION_ENABLED")
INPUT_CLASSIFICATION_ENABLED = _env_bool(_ice, True)

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

# ===== Skill 执行自动总结配置 =====

# 是否启用 Skill 执行自动总结（true/false，默认 false）
_sse = get_config("SKILL_SUMMARY_ENABLED")
SKILL_SUMMARY_ENABLED = _env_bool(_sse, False)

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

# ===== 定时任务配置 =====
# 定时任务触发智能体会话时，是否自动弹出主窗口并打开会话
_stsw = get_config("SCHEDULED_TASK_SHOW_WINDOW")
SCHEDULED_TASK_SHOW_WINDOW = _env_bool(_stsw, False)

# ===== 目录+补发 渐进披露机制配置 =====

# 是否启用工具目录机制（目录+补发）
# 启用后：初始只提供工具简要描述，完整定义按需获取
# 禁用后：初始提供所有工具的完整定义（传统方式）
_use_tc = get_config("USE_TOOL_CATALOG")
USE_TOOL_CATALOG = _env_bool(_use_tc, True)

# ===== 内存优化配置 =====

# 是否启用内存优化
_moe = get_config("MEMORY_OPTIMIZATION_ENABLED")
MEMORY_OPTIMIZATION_ENABLED = _env_bool(_moe, True)

# 内存优化延迟秒数
_mods = get_config("MEMORY_OPTIMIZATION_DELAY_SECONDS")
try:
    MEMORY_OPTIMIZATION_DELAY_SECONDS = int(_mods) if _mods not in (None, "") else 30
except (TypeError, ValueError):
    MEMORY_OPTIMIZATION_DELAY_SECONDS = 30
if MEMORY_OPTIMIZATION_DELAY_SECONDS < 1:
    MEMORY_OPTIMIZATION_DELAY_SECONDS = 30

# 后台模式保留的消息数量
_bkmc = get_config("BACKGROUND_KEEP_MESSAGES_COUNT")
try:
    BACKGROUND_KEEP_MESSAGES_COUNT = int(_bkmc) if _bkmc not in (None, "") else 50
except (TypeError, ValueError):
    BACKGROUND_KEEP_MESSAGES_COUNT = 50
if BACKGROUND_KEEP_MESSAGES_COUNT < 1:
    BACKGROUND_KEEP_MESSAGES_COUNT = 50

# ===== 录音配置 =====

RECORDING_SAMPLE_RATE = 16000
RECORDING_CHANNELS = 1
RECORDING_DTYPE = 'int16'

_stl = get_config("RECORDING_TRANSCRIPTION_LANGUAGE")
RECORDING_TRANSCRIPTION_LANGUAGE = _stl if _stl not in (None, "") else "zh"

# ===== ASR 语音识别模型配置 =====

# ONNX 模型目录路径
_asr_onnx = get_config("ASR_ONNX_MODEL_PATH")
ASR_ONNX_MODEL_PATH = _asr_onnx if _asr_onnx not in (None, "") else ""

# 程序启动自动加载 ASR 模型
_asr_auto_load = get_config("ASR_AUTO_LOAD")
ASR_AUTO_LOAD = _asr_auto_load.lower() in ("true", "1", "yes") if _asr_auto_load not in (None, "") else False

# 模型不存在时是否自动下载（默认 True）
_asr_auto_download = get_config("ASR_AUTO_DOWNLOAD")
ASR_AUTO_DOWNLOAD = _env_bool(_asr_auto_download, True)

# 最大音频处理时长（秒），默认 3600（1小时）
_asr_max_duration = get_config("ASR_MAX_AUDIO_DURATION")
try:
    ASR_MAX_AUDIO_DURATION = int(_asr_max_duration) if _asr_max_duration not in (None, "") else 3600
except (TypeError, ValueError):
    ASR_MAX_AUDIO_DURATION = 3600
if ASR_MAX_AUDIO_DURATION < 1:
    ASR_MAX_AUDIO_DURATION = 3600

# 是否显示时长警告提示（默认 True）
_asr_show_warning = get_config("ASR_SHOW_DURATION_WARNING")
ASR_SHOW_DURATION_WARNING = _env_bool(_asr_show_warning, True)

# GPU 处理的最大音频时长（秒），超过此时长强制使用 CPU，默认 300 秒（5分钟）
# 原因：长音频一次性加载到 GPU 可能导致显存溢出和系统崩溃
_asr_gpu_max_duration = get_config("ASR_GPU_MAX_DURATION")
try:
    ASR_GPU_MAX_DURATION = int(_asr_gpu_max_duration) if _asr_gpu_max_duration not in (None, "") else 300
except (TypeError, ValueError):
    ASR_GPU_MAX_DURATION = 300
if ASR_GPU_MAX_DURATION < 1:
    ASR_GPU_MAX_DURATION = 300

# ===== 文件上传配置 =====

# 文件上传大小限制（MB），默认 10 MB
_file_upload_max_size = get_config("FILE_UPLOAD_MAX_SIZE_MB")
try:
    FILE_UPLOAD_MAX_SIZE_MB = int(_file_upload_max_size) if _file_upload_max_size not in (None, "") else 200
except (TypeError, ValueError):
    FILE_UPLOAD_MAX_SIZE_MB = 200
if FILE_UPLOAD_MAX_SIZE_MB < 1:
    FILE_UPLOAD_MAX_SIZE_MB = 200

# ===== TTS 文本转语音模型配置 =====

# TTS 模型类型（zh=中文，zh_en=中英文）
_tts_model_type = get_config("TTS_MODEL_TYPE")
TTS_MODEL_TYPE = _tts_model_type if _tts_model_type in ("zh", "zh_en") else "zh"

# TTS 模型目录路径
_tts_model = get_config("TTS_MODEL_PATH")
TTS_MODEL_PATH = _tts_model if _tts_model not in (None, "") else ""

# TTS 说话人 ID（默认 0）
_tts_speaker = get_config("TTS_SPEAKER_ID")
TTS_SPEAKER_ID = int(_tts_speaker) if _tts_speaker not in (None, "") else 0

# TTS 语速（默认 1.0，范围 0.5-2.0）
_tts_speed = get_config("TTS_SPEED")
TTS_SPEED = float(_tts_speed) if _tts_speed not in (None, "") else 1.0

# 程序启动自动加载 TTS 模型
_tts_auto_load = get_config("TTS_AUTO_LOAD")
TTS_AUTO_LOAD = _tts_auto_load.lower() in ("true", "1", "yes") if _tts_auto_load not in (None, "") else False

# 模型不存在时是否自动下载（默认 True）
_tts_auto_download = get_config("TTS_AUTO_DOWNLOAD")
TTS_AUTO_DOWNLOAD = _env_bool(_tts_auto_download, True)

# ===== UI Automation 配置 =====

# 是否启用 UI Automation 功能
_uia_enabled = get_config("UIA_ENABLED")
UIA_ENABLED = _env_bool(_uia_enabled, True)

# UI Automation 操作超时时间（毫秒）
_uia_timeout = get_config("UIA_TIMEOUT_MS")
try:
    UIA_TIMEOUT_MS = int(_uia_timeout) if _uia_timeout not in (None, "") else 5000
except (TypeError, ValueError):
    UIA_TIMEOUT_MS = 5000
if UIA_TIMEOUT_MS < 100:
    UIA_TIMEOUT_MS = 5000

# 是否启用 OmniParser V2 视觉 fallback
_omniparser_enabled = get_config("OMNIPARSER_ENABLED")
OMNIPARSER_ENABLED = _env_bool(_omniparser_enabled, False)

# OmniParser 模型路径
_omniparser_path = get_config("OMNIPARSER_MODEL_PATH")
OMNIPARSER_MODEL_PATH = _omniparser_path if _omniparser_path not in (None, "") else ""
