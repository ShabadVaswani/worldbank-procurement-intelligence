"""Export slides/procurement_intelligence.pptx to PDF and PNG previews (slides/previews/slide-N.png).

    uv run --with pywin32 python slides/export_deck.py

Uses PowerPoint through COM when it is installed and not already running (so a user's open PowerPoint is never
closed), otherwise LibreOffice with a throwaway profile (PDF only; render PNGs with pdftoppm).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PPTX = HERE / "procurement_intelligence.pptx"
PDF = PPTX.with_suffix(".pdf")
PREVIEWS = HERE / "previews"


def powerpoint_running() -> bool:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq POWERPNT.EXE"], capture_output=True, text=True).stdout
    return "POWERPNT.EXE" in out


def export_powerpoint() -> bool:
    try:
        import win32com.client  # type: ignore
    except ImportError:
        return False
    if powerpoint_running():
        print("PowerPoint is already running; not touching it")
        return False
    app = win32com.client.DispatchEx("PowerPoint.Application")
    try:
        pres = app.Presentations.Open(str(PPTX), ReadOnly=True, Untitled=False, WithWindow=False)
        try:
            pres.SaveAs(str(PDF), 32)  # ppSaveAsPDF
            PREVIEWS.mkdir(exist_ok=True)
            for old in PREVIEWS.glob("slide-*.png"):
                old.unlink()
            for k in range(1, pres.Slides.Count + 1):
                pres.Slides(k).Export(str(PREVIEWS / f"slide-{k}.png"), "PNG", 1600, 900)
        finally:
            pres.Close()
    finally:
        app.Quit()
    return True


def export_libreoffice() -> bool:
    soffice = shutil.which("soffice") or r"C:\Program Files\LibreOffice\program\soffice.exe"
    if not Path(soffice).exists():
        return False
    with tempfile.TemporaryDirectory() as profile:
        subprocess.run([soffice, f"-env:UserInstallation={Path(profile).as_uri()}", "--headless", "--convert-to", "pdf",
                        "--outdir", str(HERE), str(PPTX)], capture_output=True, timeout=240)
    return PDF.exists()


if __name__ == "__main__":
    ok = export_powerpoint() or export_libreoffice()
    print("pdf", PDF if ok else None, "previews", sorted(p.name for p in PREVIEWS.glob("slide-*.png")))
    sys.exit(0 if ok else 1)
