"""Step 7: Video Composer — combine frames and audio into final MP4."""

from pathlib import Path
from typing import List

from moviepy import ImageClip, AudioFileClip, concatenate_videoclips

from .base import BaseSkill
from ..config import Settings
from ..utils.logger import logger


class VideoComposerSkill(BaseSkill):
    """Compose PNG frames and MP3 audio into final video."""

    def __init__(self, job_id: str, work_dir: Path, config: dict):
        super().__init__(job_id, work_dir, config)
        self.settings = config.get("settings", Settings())

    @property
    def skill_name(self) -> str:
        return "video_composer"

    @property
    def output_path(self) -> Path:
        return self.work_dir / "08_final.mp4"

    def execute(
        self,
        frames_dir: Path,
        audio_dir: Path,
        **inputs,
    ) -> Path:
        frames_dir = Path(frames_dir)
        audio_dir = Path(audio_dir)

        # Collect and sort frames and audios
        frames = sorted(frames_dir.glob("slide_*.png"))
        audios = sorted(audio_dir.glob("slide_*.mp3"))

        if not frames:
            raise ValueError(f"No frames found in {frames_dir}")
        if not audios:
            raise ValueError(f"No audio files found in {audio_dir}")

        logger.info(f"Composing video from {len(frames)} frames + {len(audios)} audios")

        buffer_sec = self.settings.slide_tail_buffer_sec

        clips = []
        for i, (frame_path, audio_path) in enumerate(zip(frames, audios), 1):
            try:
                audio = AudioFileClip(str(audio_path))
            except Exception as e:
                logger.warning(f"Failed to load audio {audio_path}: {e}, using 3s default")
                audio = None
                duration = 3.0

            if audio is not None:
                duration = audio.duration + buffer_sec

            img_clip = (
                ImageClip(str(frame_path))
                .with_duration(duration)
            )

            if audio is not None:
                img_clip = img_clip.with_audio(audio)

            clips.append(img_clip)
            logger.info(f"  Slide {i}: {duration:.1f}s")

        if not clips:
            raise ValueError("No clips to compose")

        final = concatenate_videoclips(clips)

        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        final.write_videofile(
            str(self.output_path),
            fps=30,
            codec="libx264",
            audio_codec="aac",
            temp_audiofile=str(self.work_dir / "tmp_audio.m4a"),
            remove_temp=True,
        )

        # Cleanup clips to free memory
        for clip in clips:
            clip.close()
        final.close()

        logger.info(f"Video saved: {self.output_path}")
        return self.output_path
