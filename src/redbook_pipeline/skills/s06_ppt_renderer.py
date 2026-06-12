"""Step 6: PPT Renderer — convert PPTX to PNG frames."""

from pathlib import Path
from typing import List

from .base import BaseSkill
from ..utils.libreoffice import render_ppt_to_images
from ..utils.logger import logger


class PPTRendererSkill(BaseSkill):
    """Render PPTX slides to PNG images using LibreOffice."""

    @property
    def skill_name(self) -> str:
        return "ppt_renderer"

    @property
    def output_path(self) -> Path:
        return self.work_dir / "07_frames"

    def execute(self, pptx_path: Path, **inputs) -> List[Path]:
        pptx_path = Path(pptx_path)
        logger.info(f"Rendering PPT to frames: {pptx_path}")

        frames = render_ppt_to_images(
            pptx_path=pptx_path,
            output_dir=self.output_path,
            dpi=300,
        )

        logger.info(f"Rendered {len(frames)} frames")
        return frames
