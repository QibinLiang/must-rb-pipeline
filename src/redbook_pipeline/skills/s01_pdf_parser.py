"""Step 1: PDF Parser — extract structured text from PDF."""

import json
import os
import re
from pathlib import Path

import fitz  # PyMuPDF

from .base import BaseSkill
from ..models import ExtractedPaper, PaperSection, PaperFigure, PaperTable, ExtractedImage
from ..utils.logger import logger


class PDFParserSkill(BaseSkill):
    """Parse PDF into structured text with sections, figures, tables, and images."""

    # Margin (in points) added around a text block when rendering a screenshot
    CLIP_MARGIN_PT = 36  # ~0.5 inch

    @property
    def skill_name(self) -> str:
        return "pdf_parser"

    @property
    def output_path(self) -> Path:
        return self.work_dir / "01_raw_text.json"

    def execute(self, pdf_path: Path, **inputs) -> ExtractedPaper:
        pdf_path = Path(pdf_path)
        logger.info(f"Parsing PDF: {pdf_path}")

        doc = fitz.open(str(pdf_path))
        metadata = {
            "title": doc.metadata.get("title", ""),
            "author": doc.metadata.get("author", ""),
            "page_count": len(doc),
        }

        # Extract text page by page
        full_text = ""
        for page_num, page in enumerate(doc, 1):
            text = page.get_text()
            full_text += f"\n--- Page {page_num} ---\n{text}"

        # Try to identify sections
        sections = self._extract_sections(full_text)

        # Try to find figure/table captions
        figures = self._extract_figures(full_text)
        tables = self._extract_tables(full_text)

        # Extract images from PDF pages
        images_dir = self.work_dir / "images"
        extracted_images = self._extract_images(doc, images_dir, figures)

        # Extract useful page/region screenshots
        extracted_images.extend(self._extract_title_page_screenshot(doc, images_dir))
        extracted_images.extend(self._extract_table_screenshots(doc, images_dir, tables))
        extracted_images.extend(self._extract_architecture_screenshots(doc, images_dir, figures))
        extracted_images.extend(self._extract_methodology_text_screenshots(doc, images_dir, sections))

        paper = ExtractedPaper(
            metadata=metadata,
            sections=sections,
            figures=figures,
            tables=tables,
            extracted_images=extracted_images,
            raw_text=full_text[:50000],  # Limit to avoid token overflow
        )

        # Save
        self.output_path.write_text(
            paper.model_dump_json(indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return paper

    def _extract_sections(self, text: str) -> list[PaperSection]:
        """Heuristic section extraction from raw text."""
        import re

        # Common section headers in academic papers
        section_patterns = [
            ("abstract", r"(?i)^\s*abstract\b"),
            ("introduction", r"(?i)^\s*(?:1\.?\s*)?introduction\b"),
            ("related_work", r"(?i)^\s*(?:2\.?\s*)?related\s+work\b"),
            ("methodology", r"(?i)^\s*(?:3\.?\s*)?(?:method|methods|methodology|approach)\b"),
            ("experiments", r"(?i)^\s*(?:4\.?\s*)?(?:experiment|experiments|evaluation|results)\b"),
            ("discussion", r"(?i)^\s*(?:5\.?\s*)?discussion\b"),
            ("conclusion", r"(?i)^\s*(?:6\.?\s*)?(?:conclusion|conclusions)\b"),
            ("references", r"(?i)^\s*references\b"),
        ]

        # Find all section boundaries
        boundaries = []
        for name, pattern in section_patterns:
            for match in re.finditer(pattern, text, re.MULTILINE):
                boundaries.append((match.start(), name))

        boundaries.sort()

        if not boundaries:
            # Fallback: treat entire text as one section
            return [PaperSection(name="full_text", content=text[:10000])]

        sections = []
        for i, (start, name) in enumerate(boundaries):
            end = boundaries[i + 1][0] if i + 1 < len(boundaries) else len(text)
            content = text[start:end].strip()
            # Skip very short sections
            if len(content) > 50:
                sections.append(PaperSection(name=name, content=content[:8000]))

        return sections

    def _extract_figures(self, text: str) -> list[PaperFigure]:
        """Extract figure captions."""
        import re

        figures = []
        for match in re.finditer(r"(?i)Figure\s+(\d+)[:.]\s*(.*?)(?=\n|$)", text):
            figures.append(
                PaperFigure(index=int(match.group(1)), caption=match.group(2).strip(), page=0)
            )
        return figures[:10]  # Limit

    def _extract_tables(self, text: str) -> list[PaperTable]:
        """Extract table captions."""
        import re

        tables = []
        for match in re.finditer(r"(?i)Table\s+(\d+)[:.]\s*(.*?)(?=\n|$)", text):
            tables.append(
                PaperTable(index=int(match.group(1)), caption=match.group(2).strip(), page=0)
            )
        return tables[:10]

    def _extract_images(
        self, doc: fitz.Document, images_dir: Path, figures: list[PaperFigure]
    ) -> list[ExtractedImage]:
        """Extract raster images from PDF pages.

        Filters out tiny images (likely icons/decorative elements) and saves
        the rest to ``images_dir``.
        """
        images_dir.mkdir(parents=True, exist_ok=True)
        extracted: list[ExtractedImage] = []
        seen_xrefs: set[int] = set()

        MIN_WIDTH = 200   # px
        MIN_HEIGHT = 150  # px
        MAX_IMAGES_PER_PAGE = 3

        for page_num in range(len(doc)):
            page = doc[page_num]
            img_list = page.get_images(full=True)

            page_img_count = 0
            for img_index, img in enumerate(img_list):
                xref = img[0]
                if xref in seen_xrefs:
                    continue
                seen_xrefs.add(xref)

                base_image = doc.extract_image(xref)
                if not base_image:
                    continue

                pix = fitz.Pixmap(doc, xref)
                # Convert CMYK to RGB if needed
                if pix.n > 4:
                    pix = fitz.Pixmap(fitz.csRGB, pix)

                width, height = pix.width, pix.height

                # Skip tiny images (icons, decorative dots, etc.)
                if width < MIN_WIDTH or height < MIN_HEIGHT:
                    pix = None
                    continue

                # Skip if aspect ratio is extreme (likely a line/border)
                aspect = width / max(height, 1)
                if aspect > 10 or aspect < 0.1:
                    pix = None
                    continue

                # Limit images per page
                page_img_count += 1
                if page_img_count > MAX_IMAGES_PER_PAGE:
                    pix = None
                    continue

                idx = len(extracted) + 1
                filename = f"img_{idx:03d}.png"
                filepath = images_dir / filename
                pix.save(str(filepath))
                pix = None

                # Try to match with a figure caption
                caption = ""
                for fig in figures:
                    if fig.page == 0 or fig.page == page_num + 1:
                        # Loose matching: any figure not yet matched
                        if not any(e.caption == fig.caption for e in extracted):
                            caption = fig.caption
                            break

                extracted.append(
                    ExtractedImage(
                        index=idx,
                        filename=filename,
                        page=page_num + 1,
                        caption=caption,
                        width=width,
                        height=height,
                    )
                )
                logger.debug(f"Extracted image {filename} from page {page_num + 1} ({width}x{height})")

        logger.info(f"Extracted {len(extracted)} images from PDF to {images_dir}")
        return extracted

    def _extract_title_page_screenshot(
        self, doc: fitz.Document, images_dir: Path
    ) -> list[ExtractedImage]:
        """Render the first page of the PDF as a title-page screenshot."""
        images_dir.mkdir(parents=True, exist_ok=True)
        if len(doc) == 0:
            return []

        page = doc[0]
        filename = "page_001_title.png"
        filepath = images_dir / filename
        try:
            pix = page.get_pixmap(dpi=150)
            pix.save(str(filepath))
            return [
                ExtractedImage(
                    index=0,
                    filename=filename,
                    page=1,
                    caption="论文首页",
                    width=pix.width,
                    height=pix.height,
                    image_type="title_page",
                )
            ]
        except Exception as e:
            logger.warning(f"Failed to render title page screenshot: {e}")
            return []

    def _find_text_blocks_for_pattern(
        self, doc: fitz.Document, pattern: re.Pattern
    ) -> list[tuple[int, fitz.Rect, str]]:
        """Find text blocks across pages whose text matches the regex pattern.

        Returns list of (page_number, bbox, matched_text).
        """
        matches: list[tuple[int, fitz.Rect, str]] = []
        for page_idx in range(len(doc)):
            page = doc[page_idx]
            blocks = page.get_text("dict").get("blocks", [])
            for block in blocks:
                if block.get("type") != 0:
                    continue
                block_text = " ".join(
                    span["text"] for line in block.get("lines", []) for span in line.get("spans", [])
                )
                m = pattern.search(block_text)
                if m:
                    bbox = fitz.Rect(block["bbox"])
                    matches.append((page_idx + 1, bbox, m.group(0)))
        return matches

    def _render_clip(
        self,
        doc: fitz.Document,
        page_num: int,
        bbox: fitz.Rect,
        output_path: Path,
        margin: float | None = None,
    ) -> tuple[int, int] | None:
        """Render a clipped region of a page to PNG. Returns (width, height) or None."""
        margin = margin if margin is not None else self.CLIP_MARGIN_PT
        page = doc[page_num - 1]
        page_rect = page.rect
        clip = bbox + margin
        clip = clip.intersect(page_rect)
        if clip.is_empty or clip.width < 10 or clip.height < 10:
            return None
        try:
            pix = page.get_pixmap(clip=clip, dpi=150)
            pix.save(str(output_path))
            return pix.width, pix.height
        except Exception as e:
            logger.warning(f"Failed to render clip on page {page_num}: {e}")
            return None

    def _extract_table_screenshots(
        self, doc: fitz.Document, images_dir: Path, tables: list[PaperTable]
    ) -> list[ExtractedImage]:
        """Render screenshots around table captions."""
        images_dir.mkdir(parents=True, exist_ok=True)
        extracted: list[ExtractedImage] = []
        # Require the block to start with "Table N" (real caption), not just mention it
        table_pattern = re.compile(r"(?i)^\s*Table\s+(\d+)[:.\s]")
        matches = self._find_text_blocks_for_pattern(doc, table_pattern)

        used_names: set[str] = set()
        for page_num, bbox, matched_text in matches:
            m = table_pattern.search(matched_text)
            if not m:
                continue
            table_idx = int(m.group(1))
            caption = ""
            for t in tables:
                if t.index == table_idx:
                    caption = t.caption
                    break

            filename = f"table_{table_idx:03d}_page{page_num}.png"
            if filename in used_names:
                continue
            used_names.add(filename)

            # Expand bbox downward generously to capture the full table body below caption
            expanded = fitz.Rect(
                bbox.x0 - self.CLIP_MARGIN_PT,
                bbox.y0 - self.CLIP_MARGIN_PT,
                bbox.x1 + self.CLIP_MARGIN_PT,
                bbox.y1 + self.CLIP_MARGIN_PT * 14,
            )
            filepath = images_dir / filename
            size = self._render_clip(doc, page_num, expanded, filepath)
            if size:
                extracted.append(
                    ExtractedImage(
                        index=0,
                        filename=filename,
                        page=page_num,
                        caption=f"表{table_idx}: {caption}" if caption else f"表{table_idx}",
                        width=size[0],
                        height=size[1],
                        image_type="table",
                    )
                )
                logger.info(f"Rendered table screenshot: {filename}")
        return extracted

    def _extract_architecture_screenshots(
        self, doc: fitz.Document, images_dir: Path, figures: list[PaperFigure]
    ) -> list[ExtractedImage]:
        """Render screenshots for figures whose captions suggest model architecture."""
        images_dir.mkdir(parents=True, exist_ok=True)
        architecture_keywords = re.compile(
            r"(?i)(architecture|framework|overview|model|pipeline|structure|approach|"
            r"network|method|system|design|schematic|tokeniz|embed|predictive|"
            r"autoregressive|transformer|backbone|encoder|decoder|overall)"
        )

        # Mark figures whose captions match architecture keywords
        target_figures: list[PaperFigure] = []
        for fig in figures:
            if architecture_keywords.search(fig.caption):
                target_figures.append(fig)

        # Fallback: if no architecture keyword matched, treat the first 1-2 figures
        # as architecture candidates (common convention in ML papers).
        if not target_figures:
            for fig in figures:
                if fig.index <= 2:
                    target_figures.append(fig)

        if not target_figures:
            return []

        figure_pattern = re.compile(r"(?i)Figure\s+(\d+)[:.\s]")
        matches = self._find_text_blocks_for_pattern(doc, figure_pattern)
        match_by_index: dict[int, tuple[int, fitz.Rect]] = {}
        for page_num, bbox, matched_text in matches:
            m = figure_pattern.search(matched_text)
            if not m:
                continue
            idx = int(m.group(1))
            if idx not in match_by_index:
                match_by_index[idx] = (page_num, bbox)

        extracted: list[ExtractedImage] = []
        used_names: set[str] = set()
        for fig in target_figures:
            if fig.index not in match_by_index:
                continue
            page_num, bbox = match_by_index[fig.index]
            filename = f"fig_{fig.index:03d}_architecture_page{page_num}.png"
            if filename in used_names:
                continue
            used_names.add(filename)

            # Figure is typically above its caption; expand upward significantly
            expanded = fitz.Rect(
                bbox.x0 - self.CLIP_MARGIN_PT,
                bbox.y0 - self.CLIP_MARGIN_PT * 16,
                bbox.x1 + self.CLIP_MARGIN_PT,
                bbox.y1 + self.CLIP_MARGIN_PT,
            )
            filepath = images_dir / filename
            size = self._render_clip(doc, page_num, expanded, filepath)
            if size:
                extracted.append(
                    ExtractedImage(
                        index=0,
                        filename=filename,
                        page=page_num,
                        caption=f"图{fig.index} ({fig.caption})",
                        width=size[0],
                        height=size[1],
                        image_type="architecture",
                    )
                )
                logger.info(f"Rendered architecture screenshot: {filename}")
        return extracted

    def _extract_methodology_text_screenshots(
        self, doc: fitz.Document, images_dir: Path, sections: list[PaperSection]
    ) -> list[ExtractedImage]:
        """Render key methodology section pages as text screenshots."""
        images_dir.mkdir(parents=True, exist_ok=True)
        methodology_section: PaperSection | None = None
        for sec in sections:
            if sec.name in ("methodology", "method", "methods", "approach"):
                methodology_section = sec
                break

        if not methodology_section:
            return []

        # Determine which pages contain methodology text by matching chunks
        sec_text = methodology_section.content[:2000]
        target_pages: set[int] = set()
        for page_idx in range(len(doc)):
            page = doc[page_idx]
            page_text = page.get_text()
            # Use a few representative snippets to identify pages
            snippets = [s for s in sec_text.split("\n") if len(s.strip()) > 40][:3]
            if any(snip in page_text for snip in snippets):
                target_pages.add(page_idx + 1)

        if not target_pages:
            return []

        extracted: list[ExtractedImage] = []
        used_pages: set[int] = set()
        for page_num in sorted(target_pages):
            if page_num in used_pages:
                continue
            used_pages.add(page_num)

            page = doc[page_num - 1]
            page_rect = page.rect
            # Clip to main body area, excluding typical margins (top 80pt, bottom 60pt)
            body_rect = fitz.Rect(
                page_rect.x0 + 54,
                page_rect.y0 + 80,
                page_rect.x1 - 54,
                page_rect.y1 - 60,
            )
            filename = f"text_method_page{page_num}.png"
            filepath = images_dir / filename
            size = self._render_clip(doc, page_num, body_rect, filepath, margin=0)
            if size:
                extracted.append(
                    ExtractedImage(
                        index=0,
                        filename=filename,
                        page=page_num,
                        caption="研究方法关键文字",
                        width=size[0],
                        height=size[1],
                        image_type="text_fallback",
                    )
                )
                logger.info(f"Rendered methodology text screenshot: {filename}")
        return extracted
