"""Step 5a: Voice Clone — upload source audio and train cloned voice."""

import json
from pathlib import Path

from .base import BaseSkill
from ..config import Settings
from ..utils.volcengine_tts import VolcengineTTSClient
from ..utils.logger import logger


class VoiceCloneSkill(BaseSkill):
    """Clone voice from source audio using Volcengine Mega-TTS.

    If clone service is not available (403/400), falls back to built-in voice.
    """

    def __init__(self, job_id: str, work_dir: Path, config: dict):
        super().__init__(job_id, work_dir, config)
        self.settings = config.get("settings", Settings())
        self.client = VolcengineTTSClient(
            api_key=self.settings.volc_api_key,
            appid=self.settings.volc_appid,
            resource_id=getattr(self.settings, "volc_resource_id", "volc.service_type.10029"),
        )

    @property
    def skill_name(self) -> str:
        return "voice_clone"

    @property
    def output_path(self) -> Path:
        return self.work_dir / "04_voice_clone_result.json"

    def execute(self, **inputs) -> dict:
        # Check if a speaker_id is already configured (pre-cloned voice)
        preset_speaker_id = getattr(self.settings, "volc_speaker_id", None)
        if preset_speaker_id:
            logger.info(f"Using pre-configured speaker_id: {preset_speaker_id}")
            result = {
                "speaker_id": preset_speaker_id,
                "status": "preset",
                "message": "Using pre-cloned voice",
            }
            self._save_result(result)
            return result

        # Check if already have a saved speaker_id
        saved_result = self._load_saved_result()
        if saved_result and saved_result.get("speaker_id"):
            logger.info(f"Using saved speaker_id: {saved_result['speaker_id']}")
            return saved_result

        source_path = Path(self.settings.source_voice)
        if not source_path.exists():
            logger.warning(f"Source voice not found: {source_path}, using built-in voice")
            return self._fallback_result("source voice file not found")

        logger.info(f"Starting voice clone from: {source_path}")
        try:
            speaker_id = self.client.clone_voice(
                audio_path=source_path,
                speaker_name=f"redbook_{self.job_id}",
            )
        except Exception as e:
            error_msg = str(e)
            logger.warning(f"Voice clone failed: {error_msg}")
            logger.warning("Falling back to built-in TTS voice")
            return self._fallback_result(error_msg)

        result = {
            "speaker_id": speaker_id,
            "status": "success",
            "source_file": str(source_path),
        }

        self._save_result(result)
        logger.info(f"Voice clone complete: speaker_id={speaker_id}")
        return result

    def _fallback_result(self, reason: str) -> dict:
        """Return a result indicating built-in voice should be used."""
        result = {
            "speaker_id": None,
            "status": "fallback",
            "reason": reason,
            "message": "Using built-in TTS voice (clone service unavailable)",
        }
        self._save_result(result)
        return result

    def _save_result(self, result: dict) -> None:
        """Save result to job dir and global cache."""
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text(
            json.dumps(result, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        cache_path = Path("outputs/.voice_clone_cache.json")
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(result, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _load_saved_result(self) -> dict | None:
        """Try to load cached speaker_id."""
        if self.output_path.exists():
            return json.loads(self.output_path.read_text(encoding="utf-8"))
        cache_path = Path("outputs/.voice_clone_cache.json")
        if cache_path.exists():
            return json.loads(cache_path.read_text(encoding="utf-8"))
        return None
