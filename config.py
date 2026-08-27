import functools
from typing import Optional, List, Dict, Any

import dotenv

from resource_path import paths
from logger import get_module_logger

logger = get_module_logger("config")


env_file='.env'


def _resolve_env_path():
    """解析 .env 文件路径（frozen 模式下含首启默认配置复制逻辑）"""
    import shutil

    if paths.is_frozen:
        # 用户配置路径
        user_env = paths.user_data_dir / env_file
        # 默认配置路径（打包内部）
        default_env = paths.get_bundled_resource(env_file)

        # 首次运行：复制默认配置到用户目录
        if not user_env.exists() and default_env.exists():
            shutil.copy(default_env, user_env)

        # 优先读取用户配置
        return user_env if user_env.exists() else default_env
    return paths.project_root / env_file


@functools.lru_cache(maxsize=1)
def _load_env() -> dict:
    """一次性解析 .env 文件并缓存（模块级 40+ 次 get_config 调用只触发 1 次磁盘读取）。

    与原实现（load_dotenv + get_key）的差异：
    - 不再把键值写入 os.environ（项目中无代码通过 os.environ 读取这些配置，
      OpenAI 客户端均显式传 api_key）
    - 缺失键不再逐条打印 dotenv 的 verbose warning
    """
    env_path = _resolve_env_path()
    if env_path.is_file():
        return dict(dotenv.dotenv_values(dotenv_path=str(env_path)))
    return {}


def get_config(key: str):
    return _load_env().get(key)


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
    # 写入后清空缓存，保证后续 get_config 读到新值
    _load_env.cache_clear()
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

# Token 消耗上限：当 Agent 累计消耗 token 超过此阈值时自动终止循环
# 替代 max_steps 硬性步数限制，支持复杂任务的灵活执行
_mtb = get_config("MAX_TOKEN_BUDGET")
try:
    MAX_TOKEN_BUDGET = int(_mtb) if _mtb not in (None, "") else 1000000
except (TypeError, ValueError):
    MAX_TOKEN_BUDGET = 1000000
if MAX_TOKEN_BUDGET < 1000:
    MAX_TOKEN_BUDGET = 1000000

# LLM API 调用重试配置
_llm_max_retries = get_config("LLM_MAX_RETRIES")
try:
    LLM_MAX_RETRIES = int(_llm_max_retries) if _llm_max_retries not in (None, "") else 3
except (TypeError, ValueError):
    LLM_MAX_RETRIES = 3
if LLM_MAX_RETRIES < 0:
    LLM_MAX_RETRIES = 3

# Agent 主循环连续 LLM 通信错误上限：超过后终止 run（避免 LLM 服务不可用时无限重试）
_llm_consecutive_error_limit = get_config("LLM_CONSECUTIVE_ERROR_LIMIT")
try:
    LLM_CONSECUTIVE_ERROR_LIMIT = (
        int(_llm_consecutive_error_limit)
        if _llm_consecutive_error_limit not in (None, "")
        else 3
    )
except (TypeError, ValueError):
    LLM_CONSECUTIVE_ERROR_LIMIT = 3
if LLM_CONSECUTIVE_ERROR_LIMIT < 1:
    LLM_CONSECUTIVE_ERROR_LIMIT = 3


def _env_bool(raw, default: bool) -> bool:
    if raw is None or str(raw).strip() == "":
        return default
    s = str(raw).strip().lower()
    # 去除值两端的引号（处理 'true' 或 "true" 等情况）
    if (s.startswith("'") and s.endswith("'")) or (s.startswith('"') and s.endswith('"')):
        s = s[1:-1].strip().lower()
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

# 是否启用复杂任务计划确认环节（true/false，默认 True）
# 启用后：复杂任务生成执行计划后，会先让用户确认（确认执行/取消/调整计划）再逐步执行
# 禁用后：计划生成后直接执行（保持原有行为）
_pce = get_config("PLAN_CONFIRMATION_ENABLED")
PLAN_CONFIRMATION_ENABLED = _env_bool(_pce, True)

_tusiu = get_config("TOKEN_USAGE_SHOW_IN_UI")
TOKEN_USAGE_SHOW_IN_UI = _env_bool(_tusiu, True)



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

# ===== ASR 实时识别配置 =====

# 是否启用实时语音识别（默认 True）
_asr_realtime_enabled = get_config("ASR_REALTIME_ENABLED")
ASR_REALTIME_ENABLED = _env_bool(_asr_realtime_enabled, True)

# 实时识别模型路径（默认为空，使用默认模型）
_asr_realtime_model = get_config("ASR_REALTIME_MODEL_PATH")
ASR_REALTIME_MODEL_PATH = _asr_realtime_model if _asr_realtime_model not in (None, "") else ""

# 实时识别结果更新间隔（毫秒），默认 200ms
_asr_realtime_interval = get_config("ASR_REALTIME_UPDATE_INTERVAL")
try:
    ASR_REALTIME_UPDATE_INTERVAL = int(_asr_realtime_interval) if _asr_realtime_interval not in (None, "") else 200
except (TypeError, ValueError):
    ASR_REALTIME_UPDATE_INTERVAL = 200
if ASR_REALTIME_UPDATE_INTERVAL < 50:
    ASR_REALTIME_UPDATE_INTERVAL = 200

# 是否程序启动自动加载流式模型（默认 False）
_asr_realtime_auto_load = get_config("ASR_REALTIME_AUTO_LOAD")
ASR_REALTIME_AUTO_LOAD = _env_bool(_asr_realtime_auto_load, False)

# ===== 文件上传配置 =====

# 文件上传大小限制（MB），默认 10 MB
_file_upload_max_size = get_config("FILE_UPLOAD_MAX_SIZE_MB")
try:
    FILE_UPLOAD_MAX_SIZE_MB = int(_file_upload_max_size) if _file_upload_max_size not in (None, "") else 200
except (TypeError, ValueError):
    FILE_UPLOAD_MAX_SIZE_MB = 200
if FILE_UPLOAD_MAX_SIZE_MB < 1:
    FILE_UPLOAD_MAX_SIZE_MB = 200

# ===== 图片存储配置 =====

# 图片文件临时存储目录
# 用于存储用户上传的图片文件，包括 base64 编码后的图片数据
# 默认路径：PersonalData/images/ （相对于 WORKER_DIR）
_image_storage_dir = get_config("IMAGE_STORAGE_DIR")
if _image_storage_dir not in (None, ""):
    IMAGE_STORAGE_DIR = str(_image_storage_dir)
else:
    # 默认路径：PersonalData/images/
    IMAGE_STORAGE_DIR = str(paths.personal_data_dir / "images")

# 图片文件清理周期（天）
# 超过此天数的图片文件将被自动清理
# 默认：7 天
_image_cleanup_days = get_config("IMAGE_CLEANUP_DAYS")
try:
    IMAGE_CLEANUP_DAYS = int(_image_cleanup_days) if _image_cleanup_days not in (None, "") else 7
except (TypeError, ValueError):
    IMAGE_CLEANUP_DAYS = 7
if IMAGE_CLEANUP_DAYS < 1:
    IMAGE_CLEANUP_DAYS = 7

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

# ===== 工具输出截断配置 =====

# 工具输出最大长度（字符数），超过此长度将被截断
# 默认值：12000（与原有硬编码值保持一致）
# 注意：设置为 0 或负数将使用默认值 12000
_tool_output_max_length = get_config("TOOL_OUTPUT_MAX_LENGTH")
try:
    TOOL_OUTPUT_MAX_LENGTH = int(_tool_output_max_length) if _tool_output_max_length not in (None, "") else 12000
except (TypeError, ValueError):
    TOOL_OUTPUT_MAX_LENGTH = 12000
if TOOL_OUTPUT_MAX_LENGTH <= 0:
    TOOL_OUTPUT_MAX_LENGTH = 12000

# 是否在截断时显示详细信息（原始长度、截断后长度）
_tool_truncate_show_details = get_config("TOOL_TRUNCATE_SHOW_DETAILS")
TOOL_TRUNCATE_SHOW_DETAILS = _env_bool(_tool_truncate_show_details, True)

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

# ===== Live2D 悬浮球配置 =====

# 是否启用 Live2D 悬浮球模式
_live2d_enabled = get_config("LIVE2D_ENABLED")
LIVE2D_ENABLED = _env_bool(_live2d_enabled, False)

# 是否在应用启动时自动加载 Live2D 模型（关闭后悬浮球以默认圆形启动，
# 可在设置页点击"加载模型"手动加载）
_live2d_auto_load = get_config("LIVE2D_AUTO_LOAD")
LIVE2D_AUTO_LOAD = _env_bool(_live2d_auto_load, True)

# Live2D 模型名称（对应 PersonalData/2DLiveFiles 下的模型目录名）
_live2d_model = get_config("LIVE2D_MODEL_NAME")
LIVE2D_MODEL_NAME = _live2d_model if _live2d_model not in (None, "") else ""

# Live2D 悬浮球宽度（像素）
_live2d_width = get_config("LIVE2D_BALL_WIDTH")
try:
    LIVE2D_BALL_WIDTH = int(_live2d_width) if _live2d_width not in (None, "") else 400
except (TypeError, ValueError):
    LIVE2D_BALL_WIDTH = 400
if LIVE2D_BALL_WIDTH < 50:
    LIVE2D_BALL_WIDTH = 400

# Live2D 悬浮球高度（像素）
_live2d_height = get_config("LIVE2D_BALL_HEIGHT")
try:
    LIVE2D_BALL_HEIGHT = int(_live2d_height) if _live2d_height not in (None, "") else 600
except (TypeError, ValueError):
    LIVE2D_BALL_HEIGHT = 600
if LIVE2D_BALL_HEIGHT < 50:
    LIVE2D_BALL_HEIGHT = 600

# ===== 音频输入设备配置 =====

def get_audio_input_device() -> Optional[int]:
    """
    获取音频输入设备ID
    
    从配置文件读取 AUDIO_INPUT_DEVICE 配置项，返回设备ID。
    
    Returns:
        设备ID（int），如果未配置或配置无效则返回 None（使用系统默认设备）
    """
    _device_id = get_config("AUDIO_INPUT_DEVICE")
    
    if _device_id is None or str(_device_id).strip() == "":
        logger.debug("音频输入设备未配置，将使用系统默认设备")
        return None
    
    try:
        device_id = int(_device_id)
        logger.info(f"读取音频输入设备配置: ID={device_id}")
        return device_id
    except (TypeError, ValueError):
        logger.warning(f"音频输入设备配置无效: '{_device_id}'，将使用系统默认设备")
        return None


def set_audio_input_device(device_id: Optional[int]) -> bool:
    """
    设置音频输入设备ID
    
    将设备ID保存到配置文件。如果 device_id 为 None，则清除配置项。
    
    Args:
        device_id: 设备ID（int），如果为 None 则清除配置
        
    Returns:
        是否设置成功
    """
    if device_id is None:
        # 清除配置项（设置为空字符串）
        logger.info("清除音频输入设备配置，将使用系统默认设备")
        # 注意：dotenv 不支持删除键，设置为空字符串表示未配置
        return set_config("AUDIO_INPUT_DEVICE", "")
    else:
        logger.info(f"设置音频输入设备: ID={device_id}")
        return set_config("AUDIO_INPUT_DEVICE", str(device_id))


def get_audio_devices() -> List[Dict[str, Any]]:
    """
    获取系统可用的音频输入设备列表
    
    使用 sounddevice.query_devices() 获取所有设备，
    过滤出输入设备（max_input_channels > 0）。
    
    Returns:
        设备列表，每个设备包含：
        - id: 设备ID（int）
        - name: 设备名称（str）
        - max_input_channels: 最大输入声道数（int）
        - default_samplerate: 默认采样率（float）
        
        如果 sounddevice 不可用或获取失败，返回空列表
    """
    try:
        import sounddevice as sd
        logger.debug("开始获取音频输入设备列表...")
        
        devices = sd.query_devices()
        input_devices = []
        
        # devices 可能是列表或单个设备字典
        if isinstance(devices, dict):
            # 单设备情况，包装成列表
            devices = [devices]
        
        for idx, device in enumerate(devices):
            # 过滤出输入设备（max_input_channels > 0）
            max_input_channels = device.get('max_input_channels', 0)
            if max_input_channels > 0:
                device_info = {
                    'id': idx,
                    'name': device.get('name', 'Unknown'),
                    'max_input_channels': max_input_channels,
                    'default_samplerate': device.get('default_samplerate', 0.0),
                }
                input_devices.append(device_info)
                logger.debug(f"发现输入设备: ID={idx}, 名称='{device_info['name']}', 声道数={max_input_channels}")
        
        logger.info(f"获取到 {len(input_devices)} 个音频输入设备")
        return input_devices
        
    except ImportError:
        logger.warning("sounddevice 库未安装，无法获取音频设备列表")
        return []
    except Exception as e:
        logger.error(f"获取音频设备列表时发生错误: {e}")
        return []
