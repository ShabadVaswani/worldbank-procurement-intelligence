"""Convert docs/proposal.md into docs/proposal.pdf, laid out as a formal project report.

    python docs/build_pdf.py

Steps:
  1. pandoc turns the Markdown body into an HTML fragment. The YAML front matter (title, subtitle, author, date)
     becomes a title page; nothing else is added to the front matter.
  2. The page is assembled with a table of contents and a list of figures, styled by docs/report.css (A4, Times
     12 pt, 1.5 spacing, 37 mm binding margin). Each ```mermaid block and its "*Figure: ...*" caption become one
     numbered figure ("Figure 1.1" = first figure of chapter 1). In the browser each diagram is scaled to fit the
     text block; a wide flowchart may be redrawn with its flow direction turned (see MERMAID_RUN).
  3. Two-pass print with headless Chrome or Edge. Pass 1 prints with empty page-number boxes of fixed width; Chrome
     keeps every element id as a named destination, which gives the page of each heading and figure. Pass 2
     prints again with the numbers filled in. The layout cannot move between passes (the boxes keep their width);
     the build checks that, and that each listed page really shows its heading or caption.
  4. PyMuPDF stamps the running header (short title + thin rule) and the centred page number on every page except
     the title page: lower-case roman for the front matter, arabic from the first body chapter. It also writes
     matching PDF page labels, bookmarks and metadata.

Mermaid draws the diagrams in the browser before printing, so the PDF holds vector diagrams and no image files.
Set MERMAID_JS to a downloaded mermaid.min.js to render offline; otherwise Mermaid loads from its CDN.
Needs pandoc, Chrome or Edge, and PyMuPDF (pip install pymupdf).
"""
from __future__ import annotations

import html
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import fitz  # PyMuPDF

DOCS = Path(__file__).resolve().parent
SOURCE = DOCS / "proposal.md"
OUTPUT = DOCS / "proposal.pdf"
CSS = DOCS / "report.css"
MERMAID_CDN = "https://cdn.jsdelivr.net/npm/mermaid@11.6.0/dist/mermaid.min.js"
BROWSERS = [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            "google-chrome", "chromium", "msedge"]

# Page geometry in mm; must match the @page rule in report.css.
PAGE_W, PAGE_H = 210, 297
MARGIN_LEFT, MARGIN_RIGHT = 37, 25
HEADER_BASELINE, HEADER_RULE, FOOTER_BASELINE = 17, 19, 284
MM = 72 / 25.4

# Mermaid draws every diagram, then layout() sizes each one to the text block (148 mm wide, at most 190 mm tall;
# sizes are fixed in mm because the script runs on the screen layout, not the print layout). A flowchart that would
# shrink below 55% is also drawn two other ways: transposed (left-to-right <-> top-to-bottom, subgraphs too), and
# with subgraphs that set no direction running across the main flow (so a row of unlinked nodes becomes a column).
# The drawing that prints largest is kept. Words, nodes and edges never change, only the direction they flow.
MERMAID_RUN = r"""<script src="{src}"></script>
<script>
  const PX = 96 / 25.4, TEXT_W = 148 * PX, MAX_H = 190 * PX, SMALL = 0.55;
  const FLIP = {{LR: "TB", RL: "BT", TB: "LR", TD: "LR", BT: "RL"}};
  const scale = svg => Math.min(1, TEXT_W / svg.viewBox.baseVal.width, MAX_H / svg.viewBox.baseVal.height);
  const decode = t => {{ const a = document.createElement("textarea"); a.innerHTML = t; return a.value; }};
  const transpose = src => src.replace(/^(\s*(?:flowchart|direction)\s+)(LR|RL|TB|TD|BT)\b/gm,
                                       (m, head, dir) => head + FLIP[dir]);
  const across = src => {{
    const outer = (src.match(/^\s*flowchart\s+(LR|RL|TB|TD|BT)\b/m) || [, "TB"])[1];
    return src.replace(/^(\s*)(subgraph\b.*)\n(?!\s*direction\b)/gm,
                       (m, ind, line) => `${{ind}}${{line}}\n${{ind}}    direction ${{FLIP[outer]}}\n`);
  }};
  async function layout() {{
    const figs = [...document.querySelectorAll("figure.diagram")];
    const sources = figs.map(f => decode(f.querySelector("pre.mermaid").innerHTML));  // as Mermaid reads it
    await mermaid.run({{querySelector: "pre.mermaid"}});
    for (const [i, fig] of figs.entries()) {{
      const pre = fig.querySelector("pre.mermaid");
      let s = scale(pre.querySelector("svg"));
      if (s < SMALL && /^\s*flowchart/.test(sources[i])) {{
        for (const [k, variant] of [transpose, across].entries()) {{
          const src = variant(sources[i]);
          if (src === sources[i]) continue;
          const best = pre.innerHTML;
          pre.innerHTML = (await mermaid.render(`v${{i}}_${{k}}`, src)).svg;
          const t = scale(pre.querySelector("svg"));
          if (t > s) s = t; else pre.innerHTML = best;
        }}
      }}
      const svg = pre.querySelector("svg");
      svg.style.maxWidth = "none";
      svg.style.width = (svg.viewBox.baseVal.width * s) + "px";
      svg.style.height = (svg.viewBox.baseVal.height * s) + "px";
      fig.dataset.scale = s.toFixed(2);
    }}
  }}
  mermaid.initialize({{startOnLoad: false, theme: "neutral", fontFamily: '"Times New Roman", Times, serif',
                       flowchart: {{nodeSpacing: 30, rankSpacing: 40}}, er: {{nodeSpacing: 40, rankSpacing: 50}}}});
  layout();
</script>"""


def browser() -> str:
    for b in BROWSERS:
        if Path(b).exists() or shutil.which(b):
            return b
    raise SystemExit("Chrome or Edge not found")


def front_matter() -> dict[str, str]:
    """The simple key: "value" pairs of the YAML block at the top of the Markdown."""
    block = SOURCE.read_text(encoding="utf-8").split("---", 2)[1]
    return dict(re.findall(r'^(\w+):\s*"(.*)"\s*$', block, flags=re.M))


def plain(fragment: str) -> str:
    """Visible text of an HTML fragment, whitespace collapsed."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", fragment)).split())


def figures(body: str) -> tuple[str, list[dict]]:
    """Wrap each Mermaid block and the caption after it in a numbered <figure>, counted per chapter.

    pandoc writes ```mermaid as <pre class="mermaid"><code>..</code></pre>; Mermaid wants the text directly.
    """
    figs: list[dict] = []
    out, pos, chapter, count = [], 0, "", 0
    pattern = re.compile(r'<h1 id="[^"]*">(.*?)</h1>|<pre class="mermaid"><code>(.*?)</code></pre>\s*'
                         r'<p><em>Figure:\s*(.*?)</em></p>', flags=re.S)
    for m in pattern.finditer(body):
        out.append(body[pos:m.start()])
        pos = m.end()
        if m.group(1) is not None:          # a chapter heading: restart the count
            num = re.match(r"(\d+|Appendix [A-Z])\.", plain(m.group(1)))
            chapter, count = (num.group(1).replace("Appendix ", "") if num else ""), 0
            out.append(m.group(0))
            continue
        count += 1
        label = f"Figure {chapter}.{count}" if chapter else f"Figure {len(figs) + 1}"
        fid = f"fig-{len(figs) + 1}"
        figs.append({"id": fid, "label": label, "caption": m.group(3)})
        out.append(f'<figure class="diagram" id="{fid}">'
                   f'<pre class="mermaid">{html.unescape(m.group(2))}</pre>'
                   f'<figcaption><strong>{label}:</strong> {m.group(3)}</figcaption></figure>')
    out.append(body[pos:])
    if body.count('class="mermaid"') != len(figs):
        raise SystemExit("a Mermaid block has no '*Figure: ...*' caption right after it")
    return "".join(out), figs


def keep_together(body: str) -> str:
    """Mark short tables (class "keep": never split) and bold lead-in paragraphs (class "lead": stay with what follows).

    A table counts as short if its estimated height is under a third of the text block. Taller tables may break between
    rows, with the header row repeated, so they never leave a near-empty page behind them.
    """
    def table(m: re.Match) -> str:
        rows = re.findall(r"<tr.*?</tr>", m.group(0), flags=re.S)
        cells = [re.findall(r"<t[hd]\b.*?</t[hd]>", r, flags=re.S) for r in rows]
        per_line = 90 // max(len(c) for c in cells)                 # characters per cell line at 10.5 pt
        lines = sum(max(max(1, -(-len(plain(c)) // per_line)) for c in row) for row in cells)
        short = lines * 13.7 + len(rows) * 7 < (PAGE_H - 50) * MM / 3  # points: line height, cell padding
        return m.group(0).replace("<table", '<table class="keep"', 1) if short else m.group(0)
    body = re.sub(r"<table.*?</table>", table, body, flags=re.S)
    return re.sub(r"<p>(<strong>[^<]*</strong>)</p>", r'<p class="lead">\1</p>', body)


def entry(href: str, text: str, number: str, cls: str) -> str:
    """One TOC/LoF line: title, dot leader, page number in a fixed-width box (so filling it never moves text)."""
    return (f'<a class="entry {cls}" href="#{href}"><span class="t">{text}</span><span class="dots"></span>'
            f'<span class="pg">{number}</span></a>')


def assemble(meta: dict, body: str, heads: list[dict], figs: list[dict], pages: dict[str, str]) -> str:
    """The whole printable page. `pages` maps an anchor id to its printed page number ('' in pass 1)."""
    toc = [entry("lof", "List of Figures", pages.get("lof", ""), "lvl1")]
    toc += [entry(h["id"], h["html"], pages.get(h["id"], ""), f'lvl{h["level"]}') for h in heads]
    lof = [entry(f["id"], f'<span class="fl">{f["label"]}</span>{f["caption"]}', pages.get(f["id"], ""), "fig")
           for f in figs]
    title = (f'<section class="title-page"><div class="tp-title">{meta["title"]}</div>'
             f'<div class="tp-subtitle">{meta.get("subtitle", "")}</div><div class="tp-kind">Technical report</div>'
             f'<div class="tp-author">{meta.get("author", "")}</div><div class="tp-date">{meta.get("date", "")}</div>'
             f'</section>')
    return (f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>{plain(meta["title"])}</title>'
            f'<link rel="stylesheet" href="{CSS.as_uri()}"></head><body>{title}'
            f'<nav class="toc"><h1 class="fm" id="toc">Table of Contents</h1>{"".join(toc)}</nav>'
            f'<nav class="lof"><h1 class="fm" id="lof">List of Figures</h1>{"".join(lof)}</nav>'
            f'<main>{body}</main></body></html>')


def print_pdf(page_html: str, tmp: Path, name: str, src: str) -> Path:
    """Print one HTML page to PDF with headless Chrome; the browser exits when the print is written."""
    page, pdf = tmp / f"{name}.html", tmp / f"{name}.pdf"
    page.write_text(page_html.replace("</body>", MERMAID_RUN.format(src=src) + "\n</body>"), encoding="utf-8")
    subprocess.run([browser(), "--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={tmp / 'p'}",
                    "--virtual-time-budget=30000", "--no-pdf-header-footer", f"--print-to-pdf={pdf}", page.as_uri()],
                   check=True, capture_output=True, timeout=180)
    return pdf


def targets(pdf: Path, keys: list[str]) -> dict[str, int]:
    """0-based page of each anchor. Chrome writes every element id as a named destination, so read those."""
    with fitz.open(pdf) as doc:
        names = doc.resolve_names()
    missing = [k for k in keys if k not in names]
    if missing:
        raise SystemExit(f"no destination in the PDF for {missing}")
    return {k: names[k]["page"] for k in keys}


def roman(n: int) -> str:
    out = ""
    for value, digits in [(10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")]:
        while n >= value:
            out, n = out + digits, n - value
    return out


def stamp(pdf: Path, out: Path, meta: dict, body_start: int, heads: list[dict], where: dict[str, int]) -> int:
    """Running header and page numbers on every page but the title page, plus labels, bookmarks and metadata."""
    short = meta["title"].split(":")[0].strip()
    left, right = MARGIN_LEFT * MM, (PAGE_W - MARGIN_RIGHT) * MM
    with fitz.open(pdf) as doc:
        for i, page in enumerate(doc):
            if i == 0:
                continue
            number = roman(i + 1) if i < body_start else str(i - body_start + 1)
            page.insert_text((left, HEADER_BASELINE * MM), short, fontname="tiit", fontsize=10)
            page.draw_line((left, HEADER_RULE * MM), (right, HEADER_RULE * MM), width=0.5)
            width = fitz.get_text_length(number, fontname="tiro", fontsize=11)
            page.insert_text(((PAGE_W * MM - width) / 2, FOOTER_BASELINE * MM), number, fontname="tiro", fontsize=11)
        doc.set_page_labels([{"startpage": 0, "prefix": "", "style": "r", "firstpagenum": 1},
                             {"startpage": body_start, "prefix": "", "style": "D", "firstpagenum": 1}])
        doc.set_toc([[1, "Table of Contents", 2], [1, "List of Figures", where["lof"] + 1]]
                    + [[h["level"], plain(h["html"]), where[h["id"]] + 1] for h in heads])
        doc.set_metadata({"title": plain(meta["title"]), "subject": plain(meta.get("subtitle", "")),
                          "author": meta.get("author", ""), "creator": "docs/build_pdf.py"})
        doc.save(out, garbage=3, deflate=True)
        return len(doc)


def check(pdf: Path, heads: list[dict], figs: list[dict], where: dict[str, int]) -> None:
    """Each listed page must show its heading or caption label; no image may sneak in; Mermaid must have drawn."""
    sizes: dict[float, int] = {}
    with fitz.open(pdf) as doc:
        text = [" ".join(p.get_text().split()) for p in doc]
        images = sum(len(p.get_images()) for p in doc)
        for page in doc:
            for block in page.get_text("dict")["blocks"]:
                for span in (s for line in block.get("lines", []) for s in line["spans"]):
                    sizes[round(span["size"], 1)] = sizes.get(round(span["size"], 1), 0) + len(span["text"])
    wanted = [(h["id"], plain(h["html"])) for h in heads] + [(f["id"], f["label"] + ":") for f in figs]
    bad = [t for key, t in wanted if t not in text[where[key]]]
    if bad:
        raise SystemExit(f"listed page does not show: {bad}")
    if images:
        raise SystemExit(f"{images} embedded images; diagrams should be vector")
    body_size = max(sizes, key=sizes.get)  # if anything is wider than the page, Chrome shrinks every page to fit it
    if abs(body_size - 12) > 0.2:
        raise SystemExit(f"body text printed at {body_size} pt, not 12 pt: something overflows the page width")
    body = " ".join(text)
    if "Unsupported markdown" in body or re.search(r"\bflowchart (TB|LR|TD)\b|erDiagram", body):
        raise SystemExit("a Mermaid diagram did not render")


def main() -> None:
    src = Path(os.environ["MERMAID_JS"]).resolve().as_uri() if os.environ.get("MERMAID_JS") else MERMAID_CDN
    meta = front_matter()
    body = subprocess.run(["pandoc", str(SOURCE), "-f", "markdown", "-t", "html5", "--wrap=none"],
                          check=True, capture_output=True, cwd=DOCS).stdout.decode("utf-8")
    body, figs = figures(body)
    body = keep_together(body)
    heads = [{"level": int(lv), "id": hid, "html": inner}
             for lv, hid, inner in re.findall(r'<h([12]) id="([^"]+)">(.*?)</h\1>', body, flags=re.S)]
    keys = ["lof"] + [h["id"] for h in heads] + [f["id"] for f in figs]

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        # Pass 1: empty number boxes; read the page of every heading and figure.
        first = targets(print_pdf(assemble(meta, body, heads, figs, {}), tmp, "pass1", src), keys)
        body_start = first[heads[0]["id"]]
        label = {k: roman(p + 1) if p < body_start else str(p - body_start + 1) for k, p in first.items()}
        # Pass 2: the numbers filled in; every anchor must still be on the page it had in pass 1.
        pdf = print_pdf(assemble(meta, body, heads, figs, label), tmp, "pass2", src)
        if targets(pdf, keys) != first:
            raise SystemExit("layout moved between pass 1 and pass 2")
        check(pdf, heads, figs, first)
        pages = stamp(pdf, OUTPUT, meta, body_start, heads, first)
    print(f"pdf {OUTPUT} ({pages} pages, body starts on page {body_start + 1})")


if __name__ == "__main__":
    main()
