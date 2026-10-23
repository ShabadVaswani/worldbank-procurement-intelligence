"""Convert docs/proposal.md into docs/proposal.pdf, as plain as possible.

    python docs/build_pdf.py

pandoc's default HTML template (no custom styling), then headless Chrome or Edge prints it to PDF. The ```mermaid
blocks of the Markdown are drawn by Mermaid in the browser before printing, so the PDF holds vector diagrams and no
image files. Set MERMAID_JS to a downloaded mermaid.min.js to render offline; otherwise Mermaid loads from its CDN.
Needs pandoc and Chrome or Edge; standard library only.
"""
from __future__ import annotations

import html
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

DOCS = Path(__file__).resolve().parent
MERMAID_CDN = "https://cdn.jsdelivr.net/npm/mermaid@11.6.0/dist/mermaid.min.js"
BROWSERS = [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            "google-chrome", "chromium", "msedge"]

MERMAID_RUN = """<script src="{src}"></script>
<script>
  mermaid.initialize({{startOnLoad: false}});
  mermaid.run({{querySelector: "pre.mermaid"}});
</script>"""


def browser() -> str:
    for b in BROWSERS:
        if Path(b).exists() or shutil.which(b):
            return b
    raise SystemExit("Chrome or Edge not found")


def mermaid_blocks(page: str) -> str:
    """pandoc writes ```mermaid as <pre class="mermaid"><code>..</code></pre>; Mermaid wants the text directly."""
    def unwrap(m: re.Match) -> str:
        return f'<pre class="mermaid">{html.unescape(m.group(1))}</pre>'
    return re.sub(r'<pre class="mermaid"><code>(.*?)</code></pre>', unwrap, page, flags=re.S)


def main() -> None:
    src = Path(os.environ["MERMAID_JS"]).resolve().as_uri() if os.environ.get("MERMAID_JS") else MERMAID_CDN
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "proposal.html"
        subprocess.run(["pandoc", str(DOCS / "proposal.md"), "-s", "-o", str(page), "--metadata", "lang=en",
                        "--metadata", "title=AI-Powered Procurement Intelligence Platform: technical proposal"],
                       check=True, cwd=DOCS)
        text = mermaid_blocks(page.read_text(encoding="utf-8"))
        page.write_text(text.replace("</body>", MERMAID_RUN.format(src=src) + "\n</body>"), encoding="utf-8")
        pdf = DOCS / "proposal.pdf"
        subprocess.run([browser(), "--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={Path(tmp) / 'p'}",
                        "--virtual-time-budget=30000", "--no-pdf-header-footer", f"--print-to-pdf={pdf}", page.as_uri()],
                       check=True, capture_output=True, timeout=180)
    print("pdf", pdf)


if __name__ == "__main__":
    main()
