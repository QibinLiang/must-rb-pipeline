"""BaseSkill abstract class with checkpoint/resume support."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any
import json
import time

from ..utils.logger import logger


class BaseSkill(ABC):
    """All skills inherit from this. Provides:
    - Unified run() interface
    - Automatic result persistence
    - Checkpoint/resume via .done files
    - Execution time tracking
    """

    def __init__(self, job_id: str, work_dir: Path, config: dict):
        self.job_id = job_id
        self.work_dir = Path(work_dir)
        self.config = config
        self.work_dir.mkdir(parents=True, exist_ok=True)

    @property
    @abstractmethod
    def skill_name(self) -> str:
        """e.g. 'pdf_parser', 'tts_synthesizer'"""

    @property
    @abstractmethod
    def output_path(self) -> Path:
        """Primary output file or directory for this skill."""

    def is_done(self) -> bool:
        """Check if valid output already exists (supports resume)."""
        done_flag = self.work_dir / f".{self.skill_name}.done"
        return done_flag.exists() and self.output_path.exists()

    def mark_done(self):
        done_flag = self.work_dir / f".{self.skill_name}.done"
        done_flag.write_text(str(time.time()))

    @abstractmethod
    def execute(self, **inputs) -> Any:
        """Actual business logic, implemented by subclasses."""

    def run(self, force: bool = False, **inputs) -> Any:
        """Entry point: check checkpoint -> execute -> persist -> mark done."""
        if self.is_done() and not force:
            logger.info(f"[{self.skill_name}] Skipped (already done, use force=True to re-run)")
            return self.load_result()

        logger.info(f"[{self.skill_name}] Starting...")
        start_ts = time.time()

        try:
            result = self.execute(**inputs)
            self.mark_done()
            elapsed = time.time() - start_ts
            logger.info(f"[{self.skill_name}] Done in {elapsed:.1f}s")
            return result
        except Exception as e:
            logger.error(f"[{self.skill_name}] Failed: {e}")
            raise

    def load_result(self) -> Any:
        """Load existing result (used when resuming)."""
        if self.output_path.suffix == ".json":
            return json.loads(self.output_path.read_text(encoding="utf-8"))
        if self.output_path.is_dir():
            return self.output_path
        return self.output_path
