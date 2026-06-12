"""LibreOffice headless rendering for PPT to images."""

import shutil
import subprocess
from pathlib import Path
from typing import List

from pdf2image import convert_from_path

from .logger import logger


def check_libreoffice() -> bool:
    """Check if LibreOffice is installed."""
    return shutil.which("soffice") is not None or shutil.which("libreoffice") is not None


def get_soffice_cmd() -> str:
    """Get the soffice command path."""
    for cmd in ("soffice", "libreoffice"):
        path = shutil.which(cmd)
        if path:
            return path
    raise RuntimeError("LibreOffice not found. Install with: brew install libreoffice")


def render_ppt_to_images(pptx_path: Path, output_dir: Path, dpi: int = 300) -> List[Path]:
    """Render PPTX to PNG frames using LibreOffice + pdf2image.

    Strategy:
        1. pptx -> pdf (LibreOffice headless)
        2. pdf -> png frames (pdf2image / poppler)
    """
    if not check_libreoffice():
        raise RuntimeError(
            "LibreOffice is required for PPT rendering.\n"
            "Install: brew install libreoffice\n"
            "Or: sudo apt-get install libreoffice"
        )

    pptx_path = Path(pptx_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Convert PPTX to PDF
    tmp_dir = output_dir / ".tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    soffice = get_soffice_cmd()
    cmd = [
        soffice,
        "--headless",
        "--convert-to", "pdf",
        "--outdir", str(tmp_dir),
        str(pptx_path),
    ]
    logger.info(f"Converting PPTX to PDF: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"LibreOffice conversion failed: {result.stderr}")

    pdf_path = tmp_dir / f"{pptx_path.stem}.pdf"
    if not pdf_path.exists():
        # LibreOffice sometimes names it differently
        pdfs = list(tmp_dir.glob("*.pdf"))
        if not pdfs:
            raise RuntimeError(f"PDF conversion failed: no PDF found in {tmp_dir}")
        pdf_path = pdfs[0]

    # Step 2: Convert PDF to PNG images
    logger.info(f"Converting PDF to PNG frames at {dpi} DPI...")
    images = convert_from_path(
        pdf_path,
        dpi=dpi,
        fmt="png",
        output_folder=str(output_dir),
        paths_only=True,
    )

    # Rename to consistent naming
    frame_paths = []
    for i, img_path in enumerate(sorted(images), 1):
        src = Path(img_path)
        dst = output_dir / f"slide_{i:03d}.png"
        src.rename(dst)
        frame_paths.append(dst)

    # Cleanup tmp PDF
    pdf_path.unlink(missing_ok=True)
    if tmp_dir.exists() and not any(tmp_dir.iterdir()):
        tmp_dir.rmdir()

    logger.info(f"Rendered {len(frame_paths)} frames to {output_dir}")
    return frame_paths
