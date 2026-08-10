"""设置路由：覆盖 9 个设置页对应的配置域。

按域分模块（settings 模块调研结论）：
- /api/settings/config/{key}      通用 .env 键值（config.py get_config/set_config）
- /api/settings/llm                LLM 配置（llm/llm_config_manager.py）
- /api/settings/prompt-templates   提示词模板（prompt_template_config.py）
- /api/settings/scheduled-tasks    计划任务（scheduled_tasks.py）
- /api/settings/autostart          开机自启（autostart.py）
- /api/settings/skills/disabled    禁用技能（skill_agent_preferences.py）
- /api/settings/hotkey             热键（config.py hotkey_* 键）
- /api/settings/live2d             Live2D（config.py LIVE2D_* 键）
- /api/settings/voice              语音（ASR/TTS/Audio，config.py 键）
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

import config
import scheduled_tasks as tasks_module
from scheduled_tasks import ScheduledTask

router = APIRouter(prefix="/api/settings", tags=["settings"])


# =====================================================================
# 通用 .env 配置
# =====================================================================

class ConfigItem(BaseModel):
    key: str
    value: str | None = None


class ConfigValueResponse(BaseModel):
    key: str
    value: str | None


@router.get("/config/{key}", response_model=ConfigValueResponse)
def get_config_value(key: str) -> ConfigValueResponse:
    return ConfigValueResponse(key=key, value=config.get_config(key))


@router.put("/config/{key}", response_model=ConfigValueResponse)
def set_config_value(key: str, body: ConfigItem) -> ConfigValueResponse:
    config.set_config(key, body.value or "")
    return ConfigValueResponse(key=key, value=body.value)


# =====================================================================
# LLM 配置（llm_config_manager）
# =====================================================================

class LLMConfigItem(BaseModel):
    id: str | None = None
    name: str = ""
    model_name: str = ""
    api_key: str = ""
    base_url: str = ""
    temperature: float = 0.7
    top_p: float = 0.95
    frequency_penalty: float = 0.6
    enable_thinking: bool = False
    enable_vision: bool = True


class LLMConfigListResponse(BaseModel):
    configs: list[LLMConfigItem]
    active_id: str | None = None
    auto_switch_on_failure: bool = True


class SetActiveLLMRequest(BaseModel):
    config_id: str


@router.get("/llm", response_model=LLMConfigListResponse)
def list_llm_configs() -> LLMConfigListResponse:
    from llm.llm_config_manager import list_configs, get_active_config_item, is_auto_switch_enabled
    items = list_configs()
    active = get_active_config_item()
    return LLMConfigListResponse(
        configs=[LLMConfigItem(**_llm_item_to_dict(i)) for i in items],
        active_id=active.id if active else None,
        auto_switch_on_failure=is_auto_switch_enabled(),
    )


@router.post("/llm", response_model=LLMConfigItem, status_code=status.HTTP_201_CREATED)
def add_llm_config(body: LLMConfigItem) -> LLMConfigItem:
    from llm.llm_config_manager import add_config, LLMConfigItem as DomainItem
    item = DomainItem(
        id=body.id or "",
        name=body.name,
        model_name=body.model_name,
        api_key=body.api_key,
        base_url=body.base_url,
        temperature=body.temperature,
        top_p=body.top_p,
        frequency_penalty=body.frequency_penalty,
        enable_thinking=body.enable_thinking,
        enable_vision=body.enable_vision,
    )
    new_id = add_config(item)
    body.id = new_id
    return body


@router.put("/llm/{config_id}", response_model=LLMConfigItem)
def update_llm_config(config_id: str, body: LLMConfigItem) -> LLMConfigItem:
    from llm.llm_config_manager import update_config, LLMConfigItem as DomainItem
    item = DomainItem(
        id=config_id,
        name=body.name,
        model_name=body.model_name,
        api_key=body.api_key,
        base_url=body.base_url,
        temperature=body.temperature,
        top_p=body.top_p,
        frequency_penalty=body.frequency_penalty,
        enable_thinking=body.enable_thinking,
        enable_vision=body.enable_vision,
    )
    ok = update_config(config_id, item)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="配置不存在")
    body.id = config_id
    return body


@router.delete("/llm/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_llm_config(config_id: str) -> None:
    from llm.llm_config_manager import delete_config
    ok = delete_config(config_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="配置不存在")


@router.put("/llm/active", response_model=dict)
def set_active_llm(body: SetActiveLLMRequest) -> dict:
    from llm.llm_config_manager import set_active_config
    ok = set_active_config(body.config_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="配置不存在")
    return {"active_id": body.config_id}


def _llm_item_to_dict(item: Any) -> dict:
    return {
        "id": getattr(item, "id", None),
        "name": getattr(item, "name", ""),
        "model_name": getattr(item, "model_name", ""),
        "api_key": getattr(item, "api_key", ""),
        "base_url": getattr(item, "base_url", ""),
        "temperature": getattr(item, "temperature", 0.7),
        "top_p": getattr(item, "top_p", 0.95),
        "frequency_penalty": getattr(item, "frequency_penalty", 0.6),
        "enable_thinking": getattr(item, "enable_thinking", False),
        "enable_vision": getattr(item, "enable_vision", True),
    }


# =====================================================================
# 提示词模板
# =====================================================================

class PromptTemplatesResponse(BaseModel):
    templates: dict[str, str]


class PromptTemplateUpdate(BaseModel):
    template: str


@router.get("/prompt-templates", response_model=PromptTemplatesResponse)
def list_prompt_templates() -> PromptTemplatesResponse:
    from prompt_template_config import load_template_config
    return PromptTemplatesResponse(templates=load_template_config())


@router.put("/prompt-templates/{conversation_type}", response_model=dict)
def update_prompt_template(conversation_type: str, body: PromptTemplateUpdate) -> dict:
    from prompt_template_config import update_template_for_conversation_type
    update_template_for_conversation_type(conversation_type, body.template)
    return {"updated": conversation_type}


@router.delete("/prompt-templates/{conversation_type}", response_model=dict)
def reset_prompt_template(conversation_type: str) -> dict:
    from prompt_template_config import reset_template_for_conversation_type
    reset_template_for_conversation_type(conversation_type)
    return {"reset": conversation_type}


@router.post("/prompt-templates/reset", response_model=dict)
def reset_all_prompt_templates() -> dict:
    from prompt_template_config import reset_all_templates
    reset_all_templates()
    return {"reset_all": True}


# =====================================================================
# 计划任务
# =====================================================================

class ScheduledTaskCreate(BaseModel):
    title: str
    content: str
    trigger_time: datetime
    repeat_type: str = "none"
    notification_type: str = "system"
    execution_type: str = "notification"
    execution_chain: str | None = None
    source_conversation_id: str | None = None
    skill_ids: list[str] | None = None


class ScheduledTaskUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    trigger_time: datetime | None = None
    repeat_type: str | None = None
    notification_type: str | None = None
    status: str | None = None
    execution_type: str | None = None
    execution_chain: str | None = None
    source_conversation_id: str | None = None
    skill_ids: list[str] | None = None


class ScheduledTaskResponse(BaseModel):
    task_id: str
    user_id: str
    title: str
    content: str
    trigger_time: datetime
    repeat_type: str
    notification_type: str
    status: str
    execution_type: str = "notification"
    execution_chain: str | None = None
    source_conversation_id: str | None = None
    skill_ids: list[str] = []
    created_at: datetime | None = None
    updated_at: datetime | None = None


def _task_to_response(t: ScheduledTask) -> ScheduledTaskResponse:
    return ScheduledTaskResponse(
        task_id=t.task_id,
        user_id=t.user_id,
        title=t.title,
        content=t.content,
        trigger_time=t.trigger_time,
        repeat_type=t.repeat_type,
        notification_type=t.notification_type,
        status=t.status,
        execution_type=getattr(t, "execution_type", "notification"),
        execution_chain=getattr(t, "execution_chain", None),
        source_conversation_id=getattr(t, "source_conversation_id", None),
        skill_ids=list(getattr(t, "skill_ids", []) or []),
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


@router.get("/scheduled-tasks", response_model=list[ScheduledTaskResponse])
def list_scheduled_tasks(
    status_filter: str | None = None,
    user_id: str | None = None,
) -> list[ScheduledTaskResponse]:
    tasks = tasks_module.list_tasks(user_id=user_id, status=status_filter)
    return [_task_to_response(t) for t in tasks]


@router.post("/scheduled-tasks", response_model=ScheduledTaskResponse, status_code=status.HTTP_201_CREATED)
def create_scheduled_task(body: ScheduledTaskCreate) -> ScheduledTaskResponse:
    task = tasks_module.add_task(
        user_id=config.DEFAULT_SKILL_AGENT_USER,
        title=body.title,
        content=body.content,
        trigger_time=body.trigger_time,
        repeat_type=body.repeat_type,
        notification_type=body.notification_type,
        execution_type=body.execution_type,
        execution_chain=body.execution_chain,
        source_conversation_id=body.source_conversation_id,
        skill_ids=body.skill_ids,
    )
    return _task_to_response(task)


@router.get("/scheduled-tasks/{task_id}", response_model=ScheduledTaskResponse)
def get_scheduled_task(task_id: str) -> ScheduledTaskResponse:
    try:
        return _task_to_response(tasks_module.get_task(task_id))
    except tasks_module.TaskNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")


@router.put("/scheduled-tasks/{task_id}", response_model=ScheduledTaskResponse)
def update_scheduled_task(task_id: str, body: ScheduledTaskUpdate) -> ScheduledTaskResponse:
    kwargs = body.model_dump(exclude_none=True)
    try:
        task = tasks_module.update_task(task_id, **kwargs)
        return _task_to_response(task)
    except tasks_module.TaskNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")


@router.delete("/scheduled-tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_scheduled_task(task_id: str) -> None:
    ok = tasks_module.delete_task(task_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")


# =====================================================================
# 开机自启
# =====================================================================

class AutostartResponse(BaseModel):
    enabled: bool
    detail: dict | None = None


@router.get("/autostart", response_model=AutostartResponse)
def get_autostart() -> AutostartResponse:
    from autostart import is_autostart_enabled, get_autostart_status
    return AutostartResponse(
        enabled=is_autostart_enabled(),
        detail=get_autostart_status(),
    )


@router.post("/autostart/enable", response_model=AutostartResponse)
def enable_autostart() -> AutostartResponse:
    from autostart import enable_autostart, get_autostart_status
    ok = enable_autostart()
    return AutostartResponse(enabled=ok, detail=get_autostart_status())


@router.post("/autostart/disable", response_model=AutostartResponse)
def disable_autostart() -> AutostartResponse:
    from autostart import disable_autostart, get_autostart_status
    ok = disable_autostart()
    return AutostartResponse(enabled=not ok if ok else True, detail=get_autostart_status())


# =====================================================================
# 批量配置（语音 / Live2D / 热键）—— 复用 /config/{key} 即可，
# 这里仅提供按域批量读取的便捷端点
# =====================================================================

class VoiceSettingsResponse(BaseModel):
    asr: dict[str, Any]
    tts: dict[str, Any]
    audio: dict[str, Any]


@router.get("/voice", response_model=VoiceSettingsResponse)
def get_voice_settings() -> VoiceSettingsResponse:
    """批量读取语音相关配置。"""
    asr_keys = [
        "ASR_REALTIME_MODEL_PATH", "ASR_REALTIME_AUTO_LOAD",
        "ASR_REALTIME_ENABLED", "ASR_REALTIME_UPDATE_INTERVAL",
    ]
    tts_keys = [
        "TTS_AUTO_LOAD", "TTS_AUTO_DOWNLOAD", "TTS_MODEL_TYPE",
        "TTS_MODEL_PATH", "TTS_SPEED", "TTS_SPEAKER_ID",
    ]
    audio_keys = ["AUDIO_INPUT_DEVICE", "AUDIO_OUTPUT_DEVICE"]
    return VoiceSettingsResponse(
        asr={k: config.get_config(k) for k in asr_keys},
        tts={k: config.get_config(k) for k in tts_keys},
        audio={k: config.get_config(k) for k in audio_keys},
    )


class Live2DSettingsResponse(BaseModel):
    enabled: bool
    model_name: str
    width: int
    height: int


@router.get("/live2d", response_model=Live2DSettingsResponse)
def get_live2d_settings() -> Live2DSettingsResponse:
    return Live2DSettingsResponse(
        enabled=bool(getattr(config, "LIVE2D_ENABLED", False)),
        model_name=getattr(config, "LIVE2D_MODEL_NAME", ""),
        width=int(getattr(config, "LIVE2D_BALL_WIDTH", 200)),
        height=int(getattr(config, "LIVE2D_BALL_HEIGHT", 200)),
    )
