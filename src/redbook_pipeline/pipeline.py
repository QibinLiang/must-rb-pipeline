"""Pipeline orchestrator:串联所有 Skill 执行完整流程."""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import Settings, load_settings
from .models import ExtractedPaper, PaperStructure, PresentationContent
from .skills.s01_pdf_parser import PDFParserSkill
from .skills.s02_paper_analyzer import PaperAnalyzerSkill
from .skills.s03_slide_generator import SlideGeneratorSkill
from .skills.s04_ppt_builder import PPTBuilderSkill
from .skills.s05_voice_clone import VoiceCloneSkill
from .skills.s05b_tts_synthesizer import TTSSynthesizerSkill
from .skills.s06_ppt_renderer import PPTRendererSkill
from .skills.s07_video_composer import VideoComposerSkill
from .utils.logger import logger

SKILL_REGISTRY = {
    "pdf_parser": PDFParserSkill,
    "paper_analyzer": PaperAnalyzerSkill,
    "slide_generator": SlideGeneratorSkill,
    "ppt_builder": PPTBuilderSkill,
    "voice_clone": VoiceCloneSkill,
    "tts_synthesizer": TTSSynthesizerSkill,
    "ppt_renderer": PPTRendererSkill,
    "video_composer": VideoComposerSkill,
}

# Define execution order. Steps 4 and 5b can run in parallel after step 3.
# For simplicity, we run sequentially.
EXECUTION_ORDER = [
    "pdf_parser",
    "paper_analyzer",
    "slide_generator",
    "voice_clone",       # Step 5a (cached after first run)
    "ppt_builder",       # Step 4
    "tts_synthesizer",   # Step 5b (needs speaker_id from voice_clone)
    "ppt_renderer",      # Step 6
    "video_composer",    # Step 7
]


class Pipeline:
    """Orchestrates the full redbook-pipeline."""

    def __init__(self, settings: Optional[Settings] = None, output_base: Path = Path("outputs")):
        self.settings = settings or load_settings()
        self.output_base = Path(output_base)

    def _make_job_id(self, pdf_path: Path) -> str:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = pdf_path.stem[:30].replace(" ", "_").replace(".", "_")
        return f"{ts}_{name}"

    def run(
        self,
        pdf_path: Path,
        job_id: Optional[str] = None,
        start_from: Optional[str] = None,
        only: Optional[str] = None,
        force: bool = False,
    ) -> Path:
        """Run the full pipeline or a subset.

        Args:
            pdf_path: Input PDF file
            job_id: Optional job ID (auto-generated if not provided)
            start_from: Resume from a specific skill
            only: Run only a single skill (for debugging)
            force: Force re-run even if already done

        Returns:
            Path to the final output (08_final.mp4 or intermediate result)
        """
        pdf_path = Path(pdf_path)
        job_id = job_id or self._make_job_id(pdf_path)
        work_dir = self.output_base / job_id
        work_dir.mkdir(parents=True, exist_ok=True)

        # Save job metadata
        meta = {
            "job_id": job_id,
            "pdf_path": str(pdf_path.absolute()),
            "created_at": datetime.now().isoformat(),
            "status": "running",
        }
        (work_dir / "00_meta.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        config = {"settings": self.settings}
        logger.info(f"Job ID: {job_id} | Work dir: {work_dir}")

        # Single-step mode
        if only:
            return self._run_single(only, work_dir, job_id, pdf_path, config, force)

        # Determine which skills to run
        skills_to_run = self._get_skills_to_run(start_from)

        # Execute each skill, passing outputs to next skill
        # We need to track intermediate results
        results = {}

        for skill_name in skills_to_run:
            result = self._run_skill(
                skill_name, work_dir, job_id, pdf_path, config, force, results
            )
            results[skill_name] = result

        # Update metadata
        meta["status"] = "completed"
        (work_dir / "00_meta.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        final_path = work_dir / "08_final.mp4"
        logger.info(f"Pipeline complete! Output: {final_path}")
        return final_path

    def _get_skills_to_run(self, start_from: Optional[str]) -> list[str]:
        """Get the list of skills to execute."""
        if not start_from:
            return list(EXECUTION_ORDER)

        if start_from not in SKILL_REGISTRY:
            raise ValueError(f"Unknown skill: {start_from}. Available: {list(SKILL_REGISTRY.keys())}")

        idx = EXECUTION_ORDER.index(start_from)
        return EXECUTION_ORDER[idx:]

    def _run_skill(
        self,
        skill_name: str,
        work_dir: Path,
        job_id: str,
        pdf_path: Path,
        config: dict,
        force: bool,
        results: dict,
    ):
        """Run a single skill with appropriate inputs."""
        skill_cls = SKILL_REGISTRY[skill_name]
        skill = skill_cls(job_id=job_id, work_dir=work_dir, config=config)

        # Prepare inputs based on skill type
        kwargs = {}

        if skill_name == "pdf_parser":
            kwargs["pdf_path"] = pdf_path

        elif skill_name == "paper_analyzer":
            # Load from previous step if not in results
            if "pdf_parser" in results:
                kwargs["paper"] = results["pdf_parser"]
            else:
                raw_path = work_dir / "01_raw_text.json"
                kwargs["paper"] = ExtractedPaper.model_validate_json(
                    raw_path.read_text(encoding="utf-8")
                )

        elif skill_name == "slide_generator":
            if "paper_analyzer" in results:
                kwargs["paper_structure"] = results["paper_analyzer"]
            else:
                # PaperStructure already imported at top
                struct_path = work_dir / "02_paper_structure.json"
                kwargs["paper_structure"] = PaperStructure.model_validate_json(
                    struct_path.read_text(encoding="utf-8")
                )
            # Also need the raw paper for context
            # ExtractedPaper already imported at top
            raw_path = work_dir / "01_raw_text.json"
            if raw_path.exists():
                kwargs["paper"] = ExtractedPaper.model_validate_json(
                    raw_path.read_text(encoding="utf-8")
                )

        elif skill_name == "voice_clone":
            pass  # No inputs needed, uses settings

        elif skill_name == "ppt_builder":
            if "slide_generator" in results:
                kwargs["presentation"] = results["slide_generator"]
            else:
                # PresentationContent already imported at top
                content_path = work_dir / "03_slide_content.json"
                kwargs["presentation"] = PresentationContent.model_validate_json(
                    content_path.read_text(encoding="utf-8")
                )

        elif skill_name == "tts_synthesizer":
            if "slide_generator" in results:
                kwargs["presentation"] = results["slide_generator"]
            else:
                # PresentationContent already imported at top
                content_path = work_dir / "03_slide_content.json"
                kwargs["presentation"] = PresentationContent.model_validate_json(
                    content_path.read_text(encoding="utf-8")
                )
            # Get speaker_id from voice_clone result
            clone_result = results.get("voice_clone")
            if not clone_result:
                clone_path = work_dir / "04_voice_clone_result.json"
                if clone_path.exists():
                    clone_result = json.loads(clone_path.read_text(encoding="utf-8"))
                else:
                    # Try global cache
                    cache_path = Path("outputs/.voice_clone_cache.json")
                    if cache_path.exists():
                        clone_result = json.loads(cache_path.read_text(encoding="utf-8"))
            kwargs["speaker_id"] = clone_result.get("speaker_id") if clone_result else None
            # If speaker_id is None, TTSSynthesizerSkill will use built-in voice as fallback

        elif skill_name == "ppt_renderer":
            kwargs["pptx_path"] = work_dir / "06_output.pptx"

        elif skill_name == "video_composer":
            kwargs["frames_dir"] = work_dir / "07_frames"
            kwargs["audio_dir"] = work_dir / "05_audio"

        return skill.run(force=force, **kwargs)

    def _run_single(
        self,
        only: str,
        work_dir: Path,
        job_id: str,
        pdf_path: Path,
        config: dict,
        force: bool,
    ):
        """Run a single skill for debugging."""
        if only not in SKILL_REGISTRY:
            raise ValueError(f"Unknown skill: {only}")

        skill_cls = SKILL_REGISTRY[only]
        skill = skill_cls(job_id=job_id, work_dir=work_dir, config=config)

        # For single-step mode, user must ensure prerequisite outputs exist
        logger.info(f"Running single skill: {only}")
        # ... (similar input preparation as above)
        # For simplicity, we just run with minimal inputs
        # In practice, the user would need to have generated intermediate files
        return skill.run(force=force, pdf_path=pdf_path)
