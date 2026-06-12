"""Step 3: Slide Generator — LLM-based slide content + narration script generation."""

import json
from pathlib import Path

from openai import OpenAI

from .base import BaseSkill
from ..models import PaperStructure, PresentationContent
from ..config import Settings
from ..utils.logger import logger
from ..utils.retry import retry_on_http_error


class SlideGeneratorSkill(BaseSkill):
    """Generate slide content and narration scripts using LLM."""

    def __init__(self, job_id: str, work_dir: Path, config: dict):
        super().__init__(job_id, work_dir, config)
        self.settings = config.get("settings", Settings())
        self.client = OpenAI(
            api_key=self.settings.kimi_api_key,
            base_url=self.settings.kimi_base_url,
        )
        # Use 32k/128k model for generating 16 rich slides (needs ~12-16k tokens output)
        raw_model = getattr(self.settings, "kimi_model", "moonshot-v1-8k")
        if "32k" in raw_model or "128k" in raw_model:
            self._model = raw_model
        elif "8k" in raw_model:
            self._model = raw_model.replace("8k", "32k")
            logger.info(f"Auto-upgraded model {raw_model} -> {self._model} for 16-slide generation")
        else:
            self._model = raw_model

    @property
    def skill_name(self) -> str:
        return "slide_generator"

    @property
    def output_path(self) -> Path:
        return self.work_dir / "03_slide_content.json"

    def _load_prompt(self) -> str:
        prompt_path = Path("config/prompts/slide_generation.md")
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
        return "请根据论文摘要生成PPT内容和旁白脚本，输出JSON格式。"

    def execute(
        self, paper_structure: PaperStructure, paper: "ExtractedPaper", **inputs
    ) -> PresentationContent:
        logger.info("Generating slide content with LLM...")

        prompt = self._load_prompt()

        # Build structured input for the LLM
        structure_json = paper_structure.model_dump_json(ensure_ascii=False)

        # Include raw text sections for context
        sections_text = "\n\n".join(
            f"## {s.name}\n{s.content[:2000]}" for s in paper.sections
        )

        # Extract original paper title from PDF metadata or first page text
        original_title = paper.metadata.get("title", "").strip()
        if not original_title and paper.raw_text:
            # Fallback: extract first non-empty line from page 1
            import re as _re
            m = _re.search(r"---\s*Page\s*1\s*---\n(.*?)\n", paper.raw_text)
            if m:
                first_line = m.group(1).strip()
                if len(first_line) > 10:
                    original_title = first_line
        if not original_title:
            original_title = "（无法提取论文标题）"

        # Build image catalog for LLM to choose from
        image_catalog = ""
        if paper.extracted_images:
            image_lines = []
            type_label_map = {
                "title_page": "首页",
                "table": "表格",
                "architecture": "架构图",
                "text_fallback": "文字",
                "figure": "配图",
            }
            for img in paper.extracted_images:
                caption_info = f" — {img.caption}" if img.caption else ""
                label = type_label_map.get(img.image_type, img.image_type)
                image_lines.append(
                    f"  [{label}] {img.filename} (第{img.page}页{img.width}x{img.height}){caption_info}"
                )
            image_catalog = "论文中提取到的图片列表:\n" + "\n".join(image_lines)

        # Presenter info from settings (three separate fields for cover layout)
        presenter_name = getattr(self.settings, "presenter_name", "")
        presenter_affiliation = getattr(self.settings, "presenter_affiliation", "")
        presenter_date = getattr(self.settings, "presenter_date", "")
        presenter = self.settings.presenter_info  # backward compat for narration

        user_content = (
            f"{prompt}\n\n"
            f"论文原标题（英文）: {original_title}\n\n"
            f"论文结构化摘要:\n{structure_json}\n\n"
            f"论文原始内容（供参考）:\n{sections_text}\n\n"
            f"{image_catalog}\n\n"
            f"汇报人姓名: {presenter_name}\n"
            f"汇报人院系/专业: {presenter_affiliation}\n"
            f"汇报日期: {presenter_date}\n"
            f"旁白中提及的完整汇报人信息: {presenter}\n\n"
            f"请输出完整的 slides JSON，包含所有16个页面的内容。"
        )

        response = self._call_llm(user_content)

        # Parse JSON (normalize smart quotes first, as some LLMs emit them)
        normalized = (
            response.replace("“", '"')
            .replace("”", '"')
            .replace("‘", "'")
            .replace("’", "'")
        )
        try:
            data = json.loads(normalized)
        except json.JSONDecodeError as e:
            import re

            logger.warning(f"Direct JSON parse failed: {e}. Trying markdown extraction.")
            match = re.search(r"```json\s*(.*?)\s*```", normalized, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1))
                except json.JSONDecodeError as e2:
                    logger.warning(f"Markdown JSON parse failed: {e2}")
                    match = None
            if not match:
                # Try finding JSON object directly
                match = re.search(r"(\{.*\})", normalized, re.DOTALL)
                if match:
                    try:
                        data = json.loads(match.group(1))
                    except json.JSONDecodeError as e3:
                        logger.error(f"Raw JSON object parse failed: {e3}")
                        raise ValueError(f"Failed to parse LLM response: {normalized[:800]}")
                else:
                    raise ValueError(f"Failed to parse LLM response: {normalized[:500]}")

        # Fix missing fields with sensible defaults
        slides = data.get("slides", [])
        if "presentation_title" not in data:
            # Infer from first slide or paper structure
            data["presentation_title"] = slides[0].get("title", "论文解读") if slides else "论文解读"
        if "total_slides" not in data:
            data["total_slides"] = len(slides)
        if "estimated_total_duration_seconds" not in data:
            # Rough estimate: ~30s per slide
            data["estimated_total_duration_seconds"] = len(slides) * 30
        if "presenter_info" not in data:
            data["presenter_info"] = presenter
        if "presenter_date" not in data:
            data["presenter_date"] = presenter_date
        if "english_title" not in data:
            data["english_title"] = None

        content = PresentationContent.model_validate(data)

        # Enforce original paper title on cover slide
        content = self._enforce_original_title(content, original_title)

        # Validate and enforce quality (word count + bullet counts)
        content = self._enforce_quality(content, user_content)

        # Save
        self.output_path.write_text(
            content.model_dump_json(indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info(f"Slide generation complete: {content.total_slides} slides")
        return content

    def _enforce_original_title(
        self, content: PresentationContent, original_title: str
    ) -> PresentationContent:
        """Ensure cover slide uses the exact original paper title."""
        if not original_title or original_title == "（无法提取论文标题）":
            return content

        # Force english_title to the original title
        if content.english_title != original_title:
            logger.info(
                f"Enforcing original title: '{content.english_title}' -> '{original_title}'"
            )
            content.english_title = original_title

        # Also update Slide 1 title if it was rewritten
        for slide in content.slides:
            if slide.slide_type == "title":
                # If the Chinese title looks like a rewrite (not containing key words from original),
                # we can't auto-translate, but we can at least flag it.
                # Heuristic: if slide.title has no Latin chars and no obvious keywords,
                # it's likely a rewrite.
                orig_lower = original_title.lower()
                title_lower = slide.title.lower()
                # Check if major words from original title appear in the Chinese title
                # (transliterations or translations).  Very loose check.
                key_words = [w for w in orig_lower.split() if len(w) > 3]
                matched = sum(1 for w in key_words if w in title_lower)
                if matched == 0 and len(slide.title) < len(original_title) * 0.8:
                    logger.warning(
                        f"Slide 1 title may have been rewritten: '{slide.title}'. "
                        f"Expected to reflect original: '{original_title}'"
                    )
                break

        return content

    def _count_narration_words(self, slides: list) -> int:
        """Count Chinese characters in narration scripts (excluding spaces/punctuation)."""
        total = 0
        for slide in slides:
            if isinstance(slide, dict):
                script = slide.get("narration_script", "")
            else:
                script = getattr(slide, "narration_script", "")
            # Count CJK characters as "words"
            total += sum(1 for ch in script if "\u4e00" <= ch <= "\u9fff")
        return total

    # Minimum bullets per slide_type from the prompt
    MIN_BULLETS = {
        "title": 0,
        "toc": 6,
        "paper_info": 3,
        "background": 6,
        "objective": 5,
        "results": 6,
        "methods": 6,
        "discussion": 5,
        "ending": 0,
    }

    # Minimum narration words per slide_type from the prompt
    # Tuned to keep total around 2300-2700 CJK characters for an 8-10 min video at 0.95x TTS speed.
    MIN_WORDS_PER_SLIDE = {
        "title": 60,
        "toc": 80,
        "paper_info": 60,
        "background": 150,
        "objective": 110,
        "results": 150,
        "methods": 140,
        "discussion": 120,
        "ending": 40,
    }

    def _enforce_quality(
        self, content: PresentationContent, original_prompt: str
    ) -> PresentationContent:
        """Ensure total narration length and per-slide bullet counts meet targets."""
        MIN_TOTAL_WORDS = 2300
        MAX_TOTAL_WORDS = 2700
        MAX_RETRIES = 2
        EXPANDABLE_TYPES = {"background", "objective", "results", "methods", "discussion"}

        for attempt in range(MAX_RETRIES + 1):
            issues: list[dict] = []
            total_words = self._count_narration_words(content.slides)

            for s in content.slides:
                stype = s.slide_type
                cjk = sum(1 for ch in s.narration_script if "\u4e00" <= ch <= "\u9fff")
                min_bullets = self.MIN_BULLETS.get(stype, 0)
                min_words = self.MIN_WORDS_PER_SLIDE.get(stype, 0)
                if stype in EXPANDABLE_TYPES:
                    if len(s.bullet_points) < min_bullets or cjk < min_words:
                        issues.append(
                            {
                                "slide_index": s.slide_index,
                                "slide_type": stype,
                                "title": s.title,
                                "current_bullets": s.bullet_points,
                                "current_word_count": cjk,
                                "required_bullets": min_bullets,
                                "required_words": min_words,
                                "current_narration_script": s.narration_script,
                            }
                        )

            logger.info(
                f"Quality check: total words={total_words} (target {MIN_TOTAL_WORDS}-{MAX_TOTAL_WORDS}), "
                f"slides needing work={len(issues)}"
            )

            if total_words >= MIN_TOTAL_WORDS and not issues:
                if total_words > MAX_TOTAL_WORDS:
                    logger.warning(
                        f"Total words {total_words} exceeds max {MAX_TOTAL_WORDS}; trimming narrations"
                    )
                    content = self._trim_narrations_to_target(content, MAX_TOTAL_WORDS)
                return content

            if attempt == MAX_RETRIES:
                logger.warning(
                    f"Quality check stopped after {MAX_RETRIES} retries. "
                    f"total_words={total_words}, remaining_issues={len(issues)}"
                )
                return content

            deficit = max(0, MIN_TOTAL_WORDS - total_words)
            logger.info(
                f"Asking LLM to fix {len(issues)} slides and add ~{deficit} words (attempt {attempt + 1})"
            )

            # Process issues in batches to keep each LLM call small and reliable
            BATCH_SIZE = 4
            merged = 0
            for batch_start in range(0, len(issues), BATCH_SIZE):
                batch = issues[batch_start : batch_start + BATCH_SIZE]
                fix_prompt = (
                    "你是一位资深学术内容讲解专家。以下 slides 的 bullet_points 数量或旁白字数不达标，"
                    "请重新生成这些 slides 的完整内容。\n\n"
                    "要求：\n"
                    f"1. 当前总旁白字数 {total_words}，还需要补充约 {deficit} 字。\n"
                    f"2. 修复后总旁白字数必须严格控制在 {MIN_TOTAL_WORDS}-{MAX_TOTAL_WORDS} 字之间，绝对不能超过 {MAX_TOTAL_WORDS} 字。\n"
                    "3. 每个 slide 的 bullet_points 数量必须达到 required_bullets。\n"
                    "4. 每个 slide 的 narration_script 字数必须达到 required_words，但不要大幅超出。\n"
                    "5. bullet_points 每条 50-80 字，必须是完整句子，带数据或对比。\n"
                    "6. narration_script 要在 bullet 基础上适度展开，口语化，像 UP 主讲解。\n"
                    "7. 输出 JSON 数组，每个元素包含 slide_index、title、bullet_points、narration_script。\n"
                    "8. 不要输出 markdown 代码块。\n\n"
                    "需要修正的 slides（请直接生成满足要求的新内容）：\n"
                    f"{json.dumps(batch, ensure_ascii=False, indent=2)}"
                )
                response = self._call_llm(fix_prompt)
                fixes = self._parse_fix_response(response)
                if not fixes:
                    logger.warning("Failed to parse fix response batch; skipping")
                    continue
                for item in fixes:
                    idx = item.get("slide_index")
                    if idx is None:
                        continue
                    for s in content.slides:
                        if s.slide_index == idx:
                            if "bullet_points" in item and item["bullet_points"]:
                                s.bullet_points = item["bullet_points"]
                            if "narration_script" in item and item["narration_script"]:
                                s.narration_script = item["narration_script"]
                            if "title" in item and item["title"]:
                                s.title = item["title"]
                            merged += 1
                            break
            logger.info(f"Merged {merged} fixed slides")

        return content

    def _parse_fix_response(self, response: str) -> list[dict]:
        """Parse LLM fix response into a list of slide fix dicts."""
        import re as _re

        # Normalize smart quotes before parsing
        normalized = (
            response.replace("“", '"')
            .replace("”", '"')
            .replace("‘", "'")
            .replace("’", "'")
        )

        # Try direct JSON parse first
        try:
            data = json.loads(normalized.strip())
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and "slides" in data:
                return data["slides"]
        except json.JSONDecodeError:
            pass

        # Try markdown code block
        match = _re.search(r"```json\s*(.*?)\s*```", normalized, _re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1).strip())
                if isinstance(data, list):
                    return data
                if isinstance(data, dict) and "slides" in data:
                    return data["slides"]
            except json.JSONDecodeError:
                pass

        # Try to extract the outermost JSON array or object
        for pattern in (r"(\[.*\])", r"(\{.*\})"):
            match = _re.search(pattern, normalized, _re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1).strip())
                    if isinstance(data, list):
                        return data
                    if isinstance(data, dict) and "slides" in data:
                        return data["slides"]
                except json.JSONDecodeError:
                    continue

        logger.warning("Could not parse fix response as JSON")
        return []

    def _trim_narrations_to_target(
        self, content: PresentationContent, target_total: int
    ) -> PresentationContent:
        """Trim narration scripts proportionally so total CJK count <= target.

        Uses sentence-level truncation: compute a per-slide budget proportional
        to its current length, then drop sentences from the end until the slide
        fits its budget. Preserves at least the first sentence of every slide.
        """
        import re as _re

        slides = content.slides
        current = self._count_narration_words(slides)
        if current <= target_total:
            return content

        # Allocate budget proportionally, with a floor so short slides don't vanish
        budgets: list[int] = []
        counts = [
            sum(1 for ch in s.narration_script if "\u4e00" <= ch <= "\u9fff")
            for s in slides
        ]
        for c in counts:
            budgets.append(max(int(c * target_total / current), 20))

        # Reconcile rounding so sum == target_total
        diff = target_total - sum(budgets)
        if diff != 0:
            # Add/subtract from slides with largest/smallest current counts
            idx_sorted = sorted(range(len(slides)), key=lambda i: counts[i], reverse=diff > 0)
            for _ in range(abs(diff)):
                for idx in idx_sorted:
                    if budgets[idx] > 30:
                        budgets[idx] += 1 if diff > 0 else -1
                        break

        for i, s in enumerate(slides):
            script = s.narration_script
            # Split on Chinese sentence-ending punctuation
            sentences = _re.split(r"(?<=[。！？\.\!\?])\s*", script)
            sentences = [sent for sent in sentences if sent.strip()]
            if not sentences:
                continue

            trimmed = sentences[0]
            for sent in sentences[1:]:
                candidate = trimmed + sent
                cand_count = sum(1 for ch in candidate if "\u4e00" <= ch <= "\u9fff")
                if cand_count <= budgets[i]:
                    trimmed = candidate
                else:
                    break

            # Ensure we didn't go over budget due to the first sentence itself
            while sum(1 for ch in trimmed if "\u4e00" <= ch <= "\u9fff") > budgets[i] and len(trimmed) > 20:
                trimmed = trimmed[:-1]

            s.narration_script = trimmed.strip()

        new_total = self._count_narration_words(slides)
        logger.info(f"Trimmed narrations from {current} to {new_total} CJK characters")
        return content

    @retry_on_http_error(max_attempts=3, min_wait=4, max_wait=30)
    def _call_llm(self, content: str) -> str:
        response = self.client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": "你是一个学术内容讲解专家。请严格输出JSON格式，不要包含markdown代码块标记。旁白脚本必须口语化，像视频博主一样自然讲解。必须生成完整的16页slides，内容要丰富充实。"},
                {"role": "user", "content": content},
            ],
            temperature=0.7,
            max_tokens=16000,
        )
        return response.choices[0].message.content
