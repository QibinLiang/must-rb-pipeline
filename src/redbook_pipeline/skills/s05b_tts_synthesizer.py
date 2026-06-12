"""Step 5b: TTS Synthesizer — generate audio for each slide narration."""

import time
from pathlib import Path

from .base import BaseSkill
from ..models import PresentationContent
from ..config import Settings
from ..utils.volcengine_tts import VolcengineTTSClient
from ..utils.logger import logger


class TTSSynthesizerSkill(BaseSkill):
    """Synthesize narration scripts to audio files using Volcengine TTS.

    Uses v3 API (standard built-in voices) by default.
    Falls back to built-in voice if clone voice is not available.
    """

    # Default built-in speaker for v3 TTS (fallback when clone unavailable)
    DEFAULT_SPEAKER = "zh_male_beijingxiaoye_emo_v2_mars_bigtts"

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
        return "tts_synthesizer"

    @property
    def output_path(self) -> Path:
        return self.work_dir / "05_audio"

    def execute(
        self,
        presentation: PresentationContent,
        speaker_id: str | None = None,
        **inputs,
    ) -> Path:
        audio_dir = self.output_path
        audio_dir.mkdir(parents=True, exist_ok=True)

        # Determine which speaker to use
        # speaker_id from clone takes priority, otherwise use built-in voice
        speaker = speaker_id if speaker_id else self.DEFAULT_SPEAKER
        is_clone = speaker_id is not None and speaker_id != self.DEFAULT_SPEAKER

        if is_clone:
            logger.info(f"Using cloned voice: {speaker}")
        else:
            logger.info(f"Using built-in voice: {speaker}")

        total = len(presentation.slides)
        for i, slide in enumerate(presentation.slides, 1):
            if not slide.narration_script.strip():
                logger.warning(f"Slide {slide.slide_index} has empty narration, skipping")
                continue

            output_file = audio_dir / f"slide_{slide.slide_index:03d}.mp3"

            # Skip if already exists (for resume)
            if output_file.exists():
                logger.info(f"[{i}/{total}] Audio already exists: {output_file.name}")
                continue

            logger.info(f"[{i}/{total}] Synthesizing audio for slide {slide.slide_index}...")
            try:
                if is_clone:
                    self.client.synthesize_v1(
                        text=slide.narration_script,
                        speaker=speaker,
                        output_path=output_file,
                        speed_ratio=self.settings.tts_speed_ratio,
                    )
                else:
                    self.client.synthesize_v3(
                        text=slide.narration_script,
                        speaker=speaker,
                        output_path=output_file,
                        speed_ratio=self.settings.tts_speed_ratio,
                    )
            except Exception as e:
                logger.error(f"TTS failed for slide {slide.slide_index}: {e}")
                raise

            # Rate limiting
            interval_ms = self.settings.tts_request_interval_ms
            if interval_ms > 0 and i < total:
                time.sleep(interval_ms / 1000.0)

        logger.info(f"TTS synthesis complete: {total} slides")
        return audio_dir
