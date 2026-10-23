"""Render Mermaid sources (*.mmd) to PNG with headless Chrome (2x scale, cropped to the diagram).

Mermaid's own HTML labels are kept (forcing plain-SVG labels drops the relationship labels of ER diagrams),
so the output is a PNG screenshot of the rendered diagram rather than an SVG file.
Usage: python docs/figures/render_mermaid.py er_model kg_edges
"""
import html
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

FIGURES = Path(__file__).parent
MERMAID = "https://cdn.jsdelivr.net/npm/mermaid@11.6.0/dist/mermaid.esm.min.mjs"
BROWSERS = [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"]

PAGE = """<!doctype html><html><body style="margin:0;background:#fff"><div id="fig-box"></div>
<pre id="out" style="display:none">PENDING</pre>
<script type="module">
import mermaid from "{mermaid}";
mermaid.initialize({{startOnLoad: false, theme: "neutral",
                     er: {{useMaxWidth: false}}, fontFamily: "Arial, Helvetica, sans-serif"}});
try {{
  const {{svg}} = await mermaid.render("fig", {code});
  document.getElementById("fig-box").innerHTML = svg;
  const vb = document.querySelector("#fig-box svg").viewBox.baseVal;
  document.getElementById("out").textContent = vb.width + "x" + vb.height;
}} catch (e) {{
  document.getElementById("out").textContent = "ERROR " + e;
}}
</script></body></html>"""


def browser() -> str:
    for b in BROWSERS:
        if Path(b).exists():
            return b
    raise SystemExit("Chrome or Edge not found")


def chrome(args: list[str], tmp: str) -> str:
    result = subprocess.run([browser(), "--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars",
                             f"--user-data-dir={Path(tmp) / 'profile'}", "--virtual-time-budget=20000", *args],
                            capture_output=True, text=True, timeout=120, check=True)
    return result.stdout


def render(name: str, scale: float = 2.0) -> Path:
    code = (FIGURES / f"{name}.mmd").read_text(encoding="utf-8")
    out = FIGURES / f"{name}.png"
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "page.html"
        page.write_text(PAGE.format(mermaid=MERMAID, code=json.dumps(code)), encoding="utf-8")
        dom = chrome(["--dump-dom", page.as_uri()], tmp)            # pass 1: learn the diagram size
        match = re.search(r'<pre id="out"[^>]*>(.*?)</pre>', dom, flags=re.S)
        size = html.unescape(match.group(1)) if match else "ERROR no output"
        if not re.fullmatch(r"[\d.]+x[\d.]+", size):
            raise SystemExit(f"{name}: render failed: {size[:300]}")
        w, h = (round(float(v)) + 2 for v in size.split("x"))
        chrome([f"--window-size={w},{h}", f"--force-device-scale-factor={scale}",  # pass 2: screenshot at that size
                f"--screenshot={out}", page.as_uri()], tmp)
    return out


if __name__ == "__main__":
    for n in sys.argv[1:] or ["er_model", "kg_edges"]:
        print("png", render(n).name)
