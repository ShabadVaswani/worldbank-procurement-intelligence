"""Build the figure PNGs used by the slides, then the proposal PDF (docs/build_pdf.py).

    python docs/build_docs.py            # figures (SVG + PNG) and docs/proposal.pdf

Needs pandoc and a local Chrome or Edge (headless printing); no Python packages beyond the standard library.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DOCS = Path(__file__).resolve().parent
FIGURES = DOCS / "figures"
BROWSERS = [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            "google-chrome", "chromium", "msedge"]

def browser() -> str:
    for b in BROWSERS:
        if Path(b).exists() or shutil.which(b):
            return b
    sys.exit("no Chrome or Edge found for headless printing")


def headless(args: list[str]) -> None:
    with tempfile.TemporaryDirectory() as profile:
        subprocess.run([browser(), "--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={profile}",
                        "--hide-scrollbars", *args], check=True, capture_output=True, timeout=120)


def svg_to_png(svg: Path, scale: float = 2.0) -> Path:
    """Screenshot the SVG at its own size; the PNG is used where SVG is not supported (PowerPoint via python-pptx)."""
    svg = svg.resolve()
    text = svg.read_text(encoding="utf-8")
    width = int(text.split('width="')[1].split('"')[0])
    height = int(text.split('height="')[1].split('"')[0])
    page = svg.with_suffix(".page.html")
    page.write_text(f'<html><body style="margin:0"><img src="{svg.name}" width="{width}" height="{height}"></body></html>',
                    encoding="utf-8")
    png = svg.with_suffix(".png")
    try:
        headless([f"--window-size={width},{height}", f"--force-device-scale-factor={scale}",
                  f"--screenshot={png}", page.as_uri()])
    finally:
        page.unlink(missing_ok=True)
    return png


if __name__ == "__main__":
    subprocess.run([sys.executable, str(FIGURES / "build_figures.py")], check=True)
    for svg in sorted(FIGURES.glob("*.svg")):
        print("png", svg_to_png(svg).name)
    subprocess.run([sys.executable, str(DOCS / "build_pdf.py")], check=True)
