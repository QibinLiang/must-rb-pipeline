"""Step 2: Paper Analyzer — LLM-based paper structure extraction."""

import json
from pathlib import Path

from openai import OpenAI

from .base import BaseSkill
from ..models import ExtractedPaper, PaperStructure
from ..config import Settings
from ..utils.logger import logger
from ..utils.retry import retry_on_http_error


class PaperAnalyzerSkill(BaseSkill):
    """Use LLM to analyze paper and extract structured information."""

    def __init__(self, job_id: str, work_dir: Path, config: dict):
        super().__init__(job_id, work_dir, config)
        self.settings = config.get("settings", Settings())
        self.client = OpenAI(
            api_key=self.settings.kimi_api_key,
            base_url=self.settings.kimi_base_url,
        )

    @property
    def skill_name(self) -> str:
        return "paper_analyzer"

    @property
    def output_path(self) -> Path:
        return self.work_dir / "02_paper_structure.json"

    def _load_prompt(self) -> str:
        prompt_path = Path("config/prompts/paper_analysis.md")
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
        return "请分析以下论文，提取关键信息并输出JSON格式。"

    def execute(self, paper: ExtractedPaper, **inputs) -> PaperStructure:
        logger.info("Analyzing paper with LLM...")

        # Build prompt with paper text
        prompt = self._load_prompt()
        sections_text = "\n\n".join(
            f"## {s.name}\n{s.content[:3000]}" for s in paper.sections
        )
        user_content = f"{prompt}\n\n论文内容:\n{sections_text}"

        response = self._call_llm(user_content)

        # Parse JSON response
        try:
            data = json.loads(response)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code block
            import re

            match = re.search(r"```json\s*(.*?)\s*```", response, re.DOTALL)
            if match:
                data = json.loads(match.group(1))
            else:
                raise ValueError(f"Failed to parse LLM response as JSON: {response[:500]}")

        structure = PaperStructure.model_validate(data)

        # Save
        self.output_path.write_text(
            structure.model_dump_json(indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info(f"Paper analysis complete: {structure.one_line_summary[:60]}...")
        return structure

    @retry_on_http_error(max_attempts=3, min_wait=4, max_wait=30)
    def _call_llm(self, content: str) -> str:
        response = self.client.chat.completions.create(
            model=self.settings.kimi_model,
            messages=[
                {"role": "system", "content": "你是一个学术内容分析专家。请严格输出JSON格式，不要包含markdown代码块标记。"},
                {"role": "user", "content": content},
            ],
            temperature=0.7,
            max_tokens=8192,
        )
        return response.choices[0].message.content
