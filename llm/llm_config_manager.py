from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import config
from resource_path import paths


def _get_config_path() -> Path:
    if paths.is_frozen:
        return paths.user_data_dir / "llm_config.json"
    return paths.project_root / "llm_config.json"


_CONFIG_PATH = _get_config_path()


@dataclass
class LLMConfig:
    model_name: str
    api_key: str
    base_url: str
    temperature: float = 0.7
    top_p: float = 0.95
    frequency_penalty: float = 0.6
    enable_thinking: bool = True
    enable_vision: bool = True
    enable_deep_thinking: bool = True
    enable_tool_call: bool = True


@dataclass
class LLMConfigItem:
    id: str
    name: str
    model_name: str
    api_key: str
    base_url: str
    temperature: float = 0.7
    top_p: float = 0.95
    frequency_penalty: float = 0.6
    enable_thinking: bool = True
    enable_vision: bool = True
    enable_deep_thinking: bool = True
    enable_tool_call: bool = True

    @classmethod
    def from_llm_config(cls, llm_config: LLMConfig, name: str = "默认配置") -> LLMConfigItem:
        return cls(
            id=generate_config_id(),
            name=name,
            model_name=llm_config.model_name,
            api_key=llm_config.api_key,
            base_url=llm_config.base_url,
            temperature=llm_config.temperature,
            top_p=llm_config.top_p,
            frequency_penalty=llm_config.frequency_penalty,
            enable_thinking=llm_config.enable_thinking,
            enable_vision=llm_config.enable_vision,
            enable_deep_thinking=llm_config.enable_deep_thinking,
            enable_tool_call=llm_config.enable_tool_call,
        )

    def to_llm_config(self) -> LLMConfig:
        return LLMConfig(
            model_name=self.model_name,
            api_key=self.api_key,
            base_url=self.base_url,
            temperature=self.temperature,
            top_p=self.top_p,
            frequency_penalty=self.frequency_penalty,
            enable_thinking=self.enable_thinking,
            enable_vision=self.enable_vision,
            enable_deep_thinking=self.enable_deep_thinking,
            enable_tool_call=self.enable_tool_call,
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "model_name": self.model_name,
            "api_key": self.api_key,
            "base_url": self.base_url,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "frequency_penalty": self.frequency_penalty,
            "enable_thinking": self.enable_thinking,
            "enable_vision": self.enable_vision,
            "enable_deep_thinking": self.enable_deep_thinking,
            "enable_tool_call": self.enable_tool_call,
        }

    @classmethod
    def from_dict(cls, data: dict) -> LLMConfigItem:
        return cls(
            id=str(data.get("id", generate_config_id())),
            name=str(data.get("name", "未命名配置")),
            model_name=str(data.get("model_name", "")).strip(),
            api_key=str(data.get("api_key", "")).strip(),
            base_url=str(data.get("base_url", "")).strip(),
            temperature=float(data.get("temperature", 0.7)),
            top_p=float(data.get("top_p", 0.95)),
            frequency_penalty=float(data.get("frequency_penalty", 0.6)),
            enable_thinking=bool(data.get("enable_thinking", True)),
            enable_vision=bool(data.get("enable_vision", True)),
            enable_deep_thinking=bool(data.get("enable_deep_thinking", True)),
            enable_tool_call=bool(data.get("enable_tool_call", True)),
        )


@dataclass
class MultiLLMConfig:
    configs: list[LLMConfigItem] = field(default_factory=list)
    active_index: int = 0
    auto_switch_on_failure: bool = True

    def to_dict(self) -> dict:
        return {
            "configs": [c.to_dict() for c in self.configs],
            "active_index": self.active_index,
            "auto_switch_on_failure": self.auto_switch_on_failure,
        }

    @classmethod
    def from_dict(cls, data: dict) -> MultiLLMConfig:
        configs_data = data.get("configs", [])
        configs = [LLMConfigItem.from_dict(c) for c in configs_data if isinstance(c, dict)]
        active_index = int(data.get("active_index", 0))
        if active_index < 0 or active_index >= len(configs):
            active_index = 0
        return cls(
            configs=configs,
            active_index=active_index,
            auto_switch_on_failure=bool(data.get("auto_switch_on_failure", True)),
        )

    def get_active_config(self) -> Optional[LLMConfigItem]:
        if not self.configs:
            return None
        if self.active_index < 0 or self.active_index >= len(self.configs):
            return self.configs[0] if self.configs else None
        return self.configs[self.active_index]


def generate_config_id() -> str:
    return uuid.uuid4().hex[:12]


_multi_llm_config: Optional[MultiLLMConfig] = None
_llm_config: Optional[LLMConfig] = None


def _is_old_format(data: dict) -> bool:
    if "configs" in data and isinstance(data.get("configs"), list):
        return False
    if "model_name" in data or "api_key" in data or "base_url" in data:
        return True
    return False


def _migrate_old_format(data: dict) -> MultiLLMConfig:
    config_item = LLMConfigItem(
        id=generate_config_id(),
        name="主配置",
        model_name=str(data.get("model_name", "")).strip(),
        api_key=str(data.get("api_key", "")).strip(),
        base_url=str(data.get("base_url", "")).strip(),
        temperature=float(data.get("temperature", 0.7)),
        top_p=float(data.get("top_p", 0.95)),
        frequency_penalty=float(data.get("frequency_penalty", 0.6)),
        enable_thinking=bool(data.get("enable_thinking", True)),
        enable_vision=bool(data.get("enable_vision", True)),
        enable_deep_thinking=bool(data.get("enable_deep_thinking", True)),
        enable_tool_call=bool(data.get("enable_tool_call", True)),
    )
    return MultiLLMConfig(
        configs=[config_item],
        active_index=0,
        auto_switch_on_failure=True,
    )


def _create_default_multi_config() -> MultiLLMConfig:
    default_config = LLMConfigItem(
        id=generate_config_id(),
        name="默认配置",
        model_name=str(config.MODEL_NAME or "").strip(),
        api_key=str(config.OPENAI_API_KEY or "").strip(),
        base_url=str(config.OPENAI_BASE_URL or "").strip(),
        temperature=0.7,
        top_p=0.95,
        frequency_penalty=0.6,
        enable_thinking=True,
        enable_vision=True,
        enable_deep_thinking=True,
        enable_tool_call=True,
    )
    return MultiLLMConfig(
        configs=[default_config],
        active_index=0,
        auto_switch_on_failure=True,
    )


def _load_multi_config_from_file() -> MultiLLMConfig:
    if not _CONFIG_PATH.is_file():
        return _create_default_multi_config()
    try:
        raw = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _create_default_multi_config()
    if not isinstance(raw, dict):
        return _create_default_multi_config()
    if _is_old_format(raw):
        multi_config = _migrate_old_format(raw)
        _save_multi_config_to_file(multi_config)
        return multi_config
    return MultiLLMConfig.from_dict(raw)


def _save_multi_config_to_file(multi_config: MultiLLMConfig) -> None:
    data = multi_config.to_dict()
    text = json.dumps(data, ensure_ascii=False, indent=2)
    _CONFIG_PATH.write_text(text + "\n", encoding="utf-8")


def get_current_multi_config() -> MultiLLMConfig:
    global _multi_llm_config
    if _multi_llm_config is None:
        _multi_llm_config = _load_multi_config_from_file()
    return _multi_llm_config


def set_multi_config(multi_config: MultiLLMConfig) -> None:
    global _multi_llm_config, _llm_config
    _multi_llm_config = multi_config
    _llm_config = None
    _save_multi_config_to_file(multi_config)


def add_config(config_item: LLMConfigItem) -> str:
    multi_config = get_current_multi_config()
    multi_config.configs.append(config_item)
    set_multi_config(multi_config)
    return config_item.id


def update_config(config_id: str, config_item: LLMConfigItem) -> bool:
    multi_config = get_current_multi_config()
    for i, c in enumerate(multi_config.configs):
        if c.id == config_id:
            config_item.id = config_id
            multi_config.configs[i] = config_item
            set_multi_config(multi_config)
            return True
    return False


def delete_config(config_id: str) -> bool:
    multi_config = get_current_multi_config()
    if len(multi_config.configs) <= 1:
        return False
    for i, c in enumerate(multi_config.configs):
        if c.id == config_id:
            multi_config.configs.pop(i)
            if multi_config.active_index >= len(multi_config.configs):
                multi_config.active_index = len(multi_config.configs) - 1
            elif multi_config.active_index > i:
                multi_config.active_index -= 1
            set_multi_config(multi_config)
            return True
    return False


def get_config(config_id: str) -> Optional[LLMConfigItem]:
    multi_config = get_current_multi_config()
    for c in multi_config.configs:
        if c.id == config_id:
            return c
    return None


def list_configs() -> list[LLMConfigItem]:
    multi_config = get_current_multi_config()
    return multi_config.configs.copy()


def get_current_config() -> LLMConfig:
    global _llm_config
    if _llm_config is None:
        multi_config = get_current_multi_config()
        active_config = multi_config.get_active_config()
        if active_config:
            _llm_config = active_config.to_llm_config()
        else:
            _llm_config = LLMConfig(
                model_name=str(config.MODEL_NAME or "").strip(),
                api_key=str(config.OPENAI_API_KEY or "").strip(),
                base_url=str(config.OPENAI_BASE_URL or "").strip(),
                temperature=0.7,
                top_p=0.95,
                frequency_penalty=0.6,
                enable_thinking=True,
                enable_vision=True,
                enable_deep_thinking=True,
                enable_tool_call=True,
            )
    return _llm_config


def set_config(new_config: LLMConfig) -> None:
    global _llm_config
    multi_config = get_current_multi_config()
    active_config = multi_config.get_active_config()
    if active_config:
        active_config.model_name = new_config.model_name
        active_config.api_key = new_config.api_key
        active_config.base_url = new_config.base_url
        active_config.temperature = new_config.temperature
        active_config.top_p = new_config.top_p
        active_config.frequency_penalty = new_config.frequency_penalty
        active_config.enable_thinking = new_config.enable_thinking
        active_config.enable_vision = new_config.enable_vision
        active_config.enable_deep_thinking = new_config.enable_deep_thinking
        active_config.enable_tool_call = new_config.enable_tool_call
    else:
        new_item = LLMConfigItem.from_llm_config(new_config, "默认配置")
        multi_config.configs.append(new_item)
        multi_config.active_index = len(multi_config.configs) - 1
    _llm_config = new_config
    set_multi_config(multi_config)


def reset_to_default() -> None:
    global _multi_llm_config, _llm_config
    _multi_llm_config = _create_default_multi_config()
    _llm_config = None
    _save_multi_config_to_file(_multi_llm_config)


def set_active_config(config_id: str) -> bool:
    multi_config = get_current_multi_config()
    for i, c in enumerate(multi_config.configs):
        if c.id == config_id:
            multi_config.active_index = i
            set_multi_config(multi_config)
            return True
    return False


def get_active_config_item() -> Optional[LLMConfigItem]:
    multi_config = get_current_multi_config()
    return multi_config.get_active_config()


def move_config_up(config_id: str) -> bool:
    multi_config = get_current_multi_config()
    configs = multi_config.configs
    if len(configs) <= 1:
        return False
    current_index = -1
    for i, c in enumerate(configs):
        if c.id == config_id:
            current_index = i
            break
    if current_index <= 0:
        return False
    configs[current_index], configs[current_index - 1] = (
        configs[current_index - 1],
        configs[current_index],
    )
    if multi_config.active_index == current_index:
        multi_config.active_index = current_index - 1
    elif multi_config.active_index == current_index - 1:
        multi_config.active_index = current_index
    set_multi_config(multi_config)
    return True


def move_config_down(config_id: str) -> bool:
    multi_config = get_current_multi_config()
    configs = multi_config.configs
    if len(configs) <= 1:
        return False
    current_index = -1
    for i, c in enumerate(configs):
        if c.id == config_id:
            current_index = i
            break
    if current_index < 0 or current_index >= len(configs) - 1:
        return False
    configs[current_index], configs[current_index + 1] = (
        configs[current_index + 1],
        configs[current_index],
    )
    if multi_config.active_index == current_index:
        multi_config.active_index = current_index + 1
    elif multi_config.active_index == current_index + 1:
        multi_config.active_index = current_index
    set_multi_config(multi_config)
    return True


def reorder_configs(config_ids: list[str]) -> bool:
    multi_config = get_current_multi_config()
    configs = multi_config.configs
    if len(config_ids) != len(configs):
        return False
    existing_ids = {c.id for c in configs}
    if set(config_ids) != existing_ids:
        return False
    id_to_config = {c.id: c for c in configs}
    new_configs = [id_to_config[cid] for cid in config_ids]
    old_active_id = configs[multi_config.active_index].id if configs else None
    multi_config.configs = new_configs
    if old_active_id:
        for i, c in enumerate(new_configs):
            if c.id == old_active_id:
                multi_config.active_index = i
                break
    set_multi_config(multi_config)
    return True


_failed_config_ids: set[str] = set()

_switch_events: list[dict] = []


def switch_to_next_config() -> Optional[LLMConfigItem]:
    """
    切换到下一个配置组。
    返回新的激活配置；如果已是最后一组则返回 None。
    """
    global _llm_config
    multi_config = get_current_multi_config()
    configs = multi_config.configs
    if len(configs) <= 1:
        return None
    current_index = multi_config.active_index
    next_index = current_index + 1
    while next_index < len(configs):
        next_config = configs[next_index]
        if next_config.id not in _failed_config_ids:
            break
        next_index += 1
    if next_index >= len(configs):
        return None
    old_config = configs[current_index]
    multi_config.active_index = next_index
    _llm_config = None
    set_multi_config(multi_config)
    new_config = configs[next_index]
    record_switch_event(old_config.id, new_config.id, "故障切换")
    return new_config


def get_next_config() -> Optional[LLMConfigItem]:
    """
    获取下一个可用的配置组（不切换），用于预判。
    返回下一个可用配置；如果没有可用的则返回 None。
    """
    multi_config = get_current_multi_config()
    configs = multi_config.configs
    if len(configs) <= 1:
        return None
    current_index = multi_config.active_index
    next_index = current_index + 1
    while next_index < len(configs):
        next_config = configs[next_index]
        if next_config.id not in _failed_config_ids:
            return next_config
        next_index += 1
    return None


def is_auto_switch_enabled() -> bool:
    """检查是否启用自动切换。"""
    multi_config = get_current_multi_config()
    return multi_config.auto_switch_on_failure


def record_switch_event(from_id: str, to_id: str, reason: str) -> None:
    """记录切换事件（用于日志）。"""
    from datetime import datetime
    event = {
        "from_id": from_id,
        "to_id": to_id,
        "reason": reason,
        "timestamp": datetime.now().isoformat(),
    }
    _switch_events.append(event)
    if len(_switch_events) > 100:
        _switch_events.pop(0)


def get_failed_config_ids() -> list[str]:
    """获取当前会话中已失败的配置ID列表。"""
    return list(_failed_config_ids)


def mark_config_failed(config_id: str) -> None:
    """标记配置为失败状态。"""
    _failed_config_ids.add(config_id)


def clear_failed_configs() -> None:
    """清除失败标记。"""
    _failed_config_ids.clear()


def get_switch_events() -> list[dict]:
    """获取切换事件历史记录。"""
    return _switch_events.copy()


def has_available_config() -> bool:
    """检查是否还有可用的配置（未被标记为失败）。"""
    multi_config = get_current_multi_config()
    for config in multi_config.configs:
        if config.id not in _failed_config_ids:
            return True
    return False


def get_all_failed_info() -> dict[str, str]:
    """
    获取所有已失败配置的信息。
    返回格式：{config_id: config_name}
    """
    multi_config = get_current_multi_config()
    failed_info: dict[str, str] = {}
    for config in multi_config.configs:
        if config.id in _failed_config_ids:
            failed_info[config.id] = config.name
    return failed_info