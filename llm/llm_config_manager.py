from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import config
from resource_path import paths


def _get_config_path() -> Path:
    if paths.is_frozen:
        return paths.user_data_dir / "llm_config.json"
    return paths.project_root / "llm_config.json"


_CONFIG_PATH = _get_config_path()


class LLMConfig:
    def __init__(
        self,
        model_name: str,
        api_key: str,
        base_url: str,
        temperature: float = 0.7,
        top_p: float = 0.95,
        frequency_penalty: float = 0.6,
        enable_thinking: bool = True,
    ) -> None:
        self.model_name = model_name
        self.api_key = api_key
        self.base_url = base_url
        self.temperature = temperature
        self.top_p = top_p
        self.frequency_penalty = frequency_penalty
        self.enable_thinking = enable_thinking


_llm_config: Optional[LLMConfig] = None


def _load_config_from_file() -> Optional[LLMConfig]:
    if not _CONFIG_PATH.is_file():
        return None
    try:
        raw = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    model_name = str(raw.get("model_name", "")).strip()
    api_key = str(raw.get("api_key", "")).strip()
    base_url = str(raw.get("base_url", "")).strip()
    temperature = float(raw.get("temperature", 0.7))
    top_p = float(raw.get("top_p", 0.95))
    frequency_penalty = float(raw.get("frequency_penalty", 0.6))
    enable_thinking = bool(raw.get("enable_thinking", True))
    if not model_name or not api_key or not base_url:
        return None
    return LLMConfig(
        model_name=model_name,
        api_key=api_key,
        base_url=base_url,
        temperature=temperature,
        top_p=top_p,
        frequency_penalty=frequency_penalty,
        enable_thinking=enable_thinking,
    )


def _save_config_to_file(config: LLMConfig) -> None:
    data = {
        "model_name": config.model_name,
        "api_key": config.api_key,
        "base_url": config.base_url,
        "temperature": config.temperature,
        "top_p": config.top_p,
        "frequency_penalty": config.frequency_penalty,
        "enable_thinking": config.enable_thinking,
    }
    text = json.dumps(data, ensure_ascii=False, indent=2)
    _CONFIG_PATH.write_text(text + "\n", encoding="utf-8")


def get_current_config() -> LLMConfig:
    global _llm_config
    if _llm_config is None:
        _llm_config = _load_config_from_file()
    if _llm_config is None:
        _llm_config = LLMConfig(
            model_name=str(config.MODEL_NAME or "").strip(),
            api_key=str(config.OPENAI_API_KEY or "").strip(),
            base_url=str(config.OPENAI_BASE_URL or "").strip(),
            temperature=0.7,
            top_p=0.95,
            frequency_penalty=0.6,
            enable_thinking=True,
        )
    return _llm_config


def set_config(config: LLMConfig) -> None:
    global _llm_config
    _llm_config = config
    _save_config_to_file(config)


def reset_to_default() -> None:
    global _llm_config
    _llm_config = LLMConfig(
        model_name=str(config.MODEL_NAME or "").strip(),
        api_key=str(config.OPENAI_API_KEY or "").strip(),
        base_url=str(config.OPENAI_BASE_URL or "").strip(),
        temperature=0.7,
        top_p=0.95,
        frequency_penalty=0.6,
        enable_thinking=True,
    )
    if _CONFIG_PATH.is_file():
        _CONFIG_PATH.unlink()