"""Build the proposal PDF and the figure PNGs used by the slides.

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

CSS = """
@page { size: A4; margin: 16mm 15mm 16mm 15mm; }
body { font-family: Inter, 'Segoe UI', Arial, sans-serif; font-size: 9.6pt; line-height: 1.4; color: #1F2937;
       max-width: none; margin: 0; padding: 0; }
h1 { font-size: 16pt; color: #1F3A5F; border-bottom: 2px solid #1F3A5F; padding-bottom: 3px; margin: 20px 0 8px; break-after: avoid; }
h2 { font-size: 12pt; color: #1F3A5F; margin: 14px 0 5px; break-after: avoid; }
p, li { orphans: 3; widows: 3; }
ul, ol { padding-left: 18px; margin: 4px 0 8px; }
li { margin: 2px 0; }
table { border-collapse: collapse; width: 100%; margin: 6px 0 10px; font-size: 8.4pt; }
thead { display: table-header-group; }
tr { break-inside: avoid; }
th { background: #1F3A5F; color: #fff; text-align: left; padding: 4px 6px; font-weight: 600; }
td { border-bottom: 1px solid #E2E8F0; padding: 3.5px 6px; vertical-align: top; }
tr:nth-child(even) td { background: #F6F8FB; }
code { font-family: Consolas, 'Cascadia Mono', monospace; font-size: 8.6pt; background: #F1F5F9; padding: 0 2px; border-radius: 2px; }
figure { margin: 8px 0 12px; break-inside: avoid; text-align: center; }
figure img { max-width: 100%; }
figcaption { font-size: 8.6pt; color: #5B6472; margin-top: 3px; }
blockquote { border-left: 3px solid #0F766E; margin: 6px 0; padding: 2px 10px; color: #374151; background: #F6F8FB; }
header#title-block-header { margin-bottom: 14px; }
.title { font-size: 21pt; color: #1F3A5F; margin: 0 0 4px; border: none; }
.subtitle { font-size: 12pt; color: #0F766E; margin: 0 0 6px; }
.author, .date { font-size: 10pt; color: #5B6472; margin: 0; }
a { color: #0F766E; }
"""


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


def proposal_pdf() -> Path:
    html = DOCS / "proposal.html"
    css = DOCS / "_proposal.css"
    css.write_text(CSS, encoding="utf-8")
    try:
        subprocess.run(["pandoc", str(DOCS / "proposal.md"), "-s", "-o", str(html), "--css", css.name,
                        "--embed-resources", "--columns=2000", "--metadata", "lang=en", "--resource-path", str(DOCS)],
                       check=True, cwd=DOCS)
    finally:
        css.unlink(missing_ok=True)
    pdf = DOCS / "proposal.pdf"
    headless(["--no-pdf-header-footer", f"--print-to-pdf={pdf}", html.as_uri()])
    html.unlink()
    return pdf


if __name__ == "__main__":
    subprocess.run([sys.executable, str(FIGURES / "build_figures.py")], check=True)
    subprocess.run([sys.executable, str(FIGURES / "render_mermaid.py"), "er_model", "kg_edges"], check=True)
    for svg in sorted(FIGURES.glob("*.svg")):
        print("png", svg_to_png(svg).name)
    print("pdf", proposal_pdf())
