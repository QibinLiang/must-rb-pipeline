# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`redbook-pipeline` is a Python CLI tool that converts academic paper PDFs into AI-narrated presentation videos. Pipeline: PDF parse → LLM analysis → slide content generation → PPT building → TTS synthesis → PPT rendering → video composition.

## Development Commands

Install dependencies (editable mode):
```bash
pip install -e .
```

Run the full pipeline:
```bash
redbook run <paper.pdf>
```

Run a single step (for debugging):
```bash
redbook run <paper.pdf> --only <skill_name> --force
```

Resume from a specific step:
```bash
redbook resume <job_id> --from <skill_name>
```

Check job status:
```bash
redbook status <job_id>
```

List all jobs:
```bash
redbook list-jobs
```

Run the Volcengine service test:
```bash
python test_volc_services.py
```

There is no formal test suite (pytest is not configured). The project relies on manual end-to-end testing via `redbook run` and `test_volc_services.py`.

## Architecture

### Pipeline Structure

The pipeline is an 8-step sequential processor defined in `src/redbook_pipeline/pipeline.py`:

1. `pdf_parser` — Extract structured text/sections/figures from PDF via PyMuPDF
2. `paper_analyzer` — LLM analysis of paper structure (Kimi API)
3. `slide_generator` — LLM generation of slide content + narration scripts
4. `voice_clone` — Optional voice clone via Volcengine (cached globally)
5. `ppt_builder` — Fill PPT template with generated content
6. `tts_synthesizer` — Synthesize narration audio per slide
7. `ppt_renderer` — Render PPT to PNG frames via LibreOffice
8. `video_composer` — Compose frames + audio into final MP4 via moviepy

Steps 4 and 5 run sequentially but 4 is cached after first run; step 6 depends on step 5's output.

### Skill Framework

All steps inherit from `BaseSkill` (`src/redbook_pipeline/skills/base.py`). Each skill:
- Declares `skill_name` and `output_path` (used for checkpointing)
- Implements `execute(**inputs)` for business logic
- Gets checkpoint/resume for free via `.done` flag files in the job directory
- Loads prior results automatically when resuming

The `Pipeline` class orchestrates execution, resolves inputs between steps, and manages the job workspace under `outputs/<job_id>/`.

### Data Models

Inter-step data flows through Pydantic v2 models in `src/redbook_pipeline/models/`:
- `ExtractedPaper` — output of pdf_parser
- `PaperStructure` — output of paper_analyzer
- `PresentationContent` / `SlideContent` — output of slide_generator, input to ppt_builder and tts_synthesizer

### Configuration

Settings are loaded from `.env` (via `pydantic-settings`) and optionally overridden by `config/settings.yaml`. Required env vars:
- `LLM_API_KEY` — for LLM content generation (OpenAI-compatible endpoint; optional `LLM_BASE_URL`, `LLM_MODEL`)
- `VOLC_APPID`, `VOLC_API_KEY` — for TTS synthesis
- `VOLC_SPEAKER_ID` — pre-cloned speaker ID (falls back to built-in voice if missing)
- `PRESENTER_NAME`, `PRESENTER_AFFILIATION` — displayed on PPT cover

### Key Implementation Details

- **PPT slide deletion**: `python-pptx` does not support slide deletion, so `PPTBuilderSkill._remove_unused_slides()` manipulates the underlying `prs.slides._sldIdLst` XML element directly, deleting from high index to low.
- **Voice clone caching**: The voice clone step writes to `outputs/.voice_clone_cache.json`. If `VOLC_SPEAKER_ID` is set in `.env`, that ID is used directly and cloning is skipped.
- **PPT rendering strategy**: `PPTRendererSkill` converts PPTX → PDF via LibreOffice headless, then PDF → PNG via `pdf2image`/`poppler`.
- **TTS client**: `VolcengineTTSClient` in `utils/volcengine_tts.py` handles both v3 standard TTS and v1 clone TTS APIs with different header formats.

## External Dependencies

LibreOffice and poppler must be installed system-wide:
```bash
# macOS
brew install libreoffice poppler

# Ubuntu
sudo apt-get install libreoffice poppler-utils
```
