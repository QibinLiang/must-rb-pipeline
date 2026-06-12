"""Configuration management."""

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, loaded from .env and settings.yaml."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Paths
    output_dir: Path = Path("outputs")
    template_path: Path = Path("pptx_template/模板.pptx")
    source_voice: Path = Path("source_voice/source.mp3")

    # Kimi / LLM
    kimi_api_key: str = Field(alias="KIMI_API_KEY")
    kimi_base_url: str = Field(default="https://api.moonshot.cn/v1", alias="KIMI_BASE_URL")
    kimi_model: str = Field(default="moonshot-v1-8k", alias="KIMI_MODEL")

    # Volcengine v3 TTS (standard voices)
    volc_appid: str = Field(alias="VOLC_APPID")
    volc_api_key: str = Field(alias="VOLC_API_KEY")
    volc_resource_id: str = Field(default="volc.service_type.10029", alias="VOLC_RESOURCE_ID")
    volc_tts_url: str = Field(
        default="https://openspeech.bytedance.com/api/v3/tts/unidirectional", alias="VOLC_TTS_URL"
    )

    # Volcengine Voice Clone (大模型)
    volc_clone_api_key: str = Field(default="", alias="VOLC_CLONE_API_KEY")
    volc_clone_secret: str = Field(default="", alias="VOLC_CLONE_SECRET")
    volc_speaker_id: str = Field(default="", alias="VOLC_SPEAKER_ID")

    # Presenter
    presenter_name: str = Field(default="", alias="PRESENTER_NAME")
    presenter_affiliation: str = Field(default="", alias="PRESENTER_AFFILIATION")
    presenter_date: str = Field(default="", alias="PRESENTER_DATE")

    # Pipeline
    max_slides: int = 16
    min_slides: int = 8
    tts_speed_ratio: float = 0.95
    slide_tail_buffer_sec: float = 1.2
    tts_request_interval_ms: int = 500

    @property
    def presenter_info(self) -> str:
        parts = [p for p in [self.presenter_name, self.presenter_affiliation] if p]
        return " ".join(parts) if parts else "汇报人信息待填写"


def load_settings(config_path: Optional[Path] = None) -> Settings:
    """Load settings from .env (via pydantic-settings) and optional YAML.

    Priority: .env > settings.yaml > defaults
    """
    from datetime import datetime

    settings = Settings()

    yaml_path = config_path or Path("config/settings.yaml")
    if yaml_path.exists():
        yaml_data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        if yaml_data:
            # Handle presenter section: YAML fills gaps left by .env defaults
            if "presenter" in yaml_data:
                p = yaml_data["presenter"]
                if p.get("name") and not settings.presenter_name:
                    settings.presenter_name = p["name"]
                if p.get("affiliation") and not settings.presenter_affiliation:
                    settings.presenter_affiliation = p["affiliation"]
                if p.get("date") and not settings.presenter_date:
                    settings.presenter_date = p["date"]

    # Default date to today if not provided (YYYY/MM/DD format)
    if not settings.presenter_date:
        settings.presenter_date = datetime.now().strftime("%Y/%m/%d")

    return settings
