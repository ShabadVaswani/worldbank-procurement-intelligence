"""Build the interview deck (7 slides, PPTX) with native shapes and charts, so every label stays readable on a projector.

    uv run --with python-pptx python slides/build_deck.py
    uv run --with pywin32 python slides/export_deck.py      # PDF + PNG previews (PowerPoint, else LibreOffice)

Every number on a slide comes from docs/proposal.md or README.md. Short speaker cues live in NOTES below and are
written into each slide's notes.
"""
from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION
from pptx.enum.dml import MSO_LINE_DASH_STYLE
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

OUT = Path(__file__).resolve().parent / "procurement_intelligence.pptx"
REPO_URL = "https://github.com/ShabadVaswani/worldbank-procurement-intelligence"

NAVY, TEAL, INK, MUTED = RGBColor(0x1F, 0x3A, 0x5F), RGBColor(0x0F, 0x76, 0x6E), RGBColor(0x1F, 0x29, 0x37), RGBColor(0x5B, 0x64, 0x72)
PANEL, TEAL_BG, WHITE = RGBColor(0xEE, 0xF4, 0xFB), RGBColor(0xE6, 0xF4, 0xF1), RGBColor(0xFF, 0xFF, 0xFF)
COLUMN_BG, LINE, GREY_BAR = RGBColor(0xF6, 0xF8, 0xFB), RGBColor(0x8A, 0x94, 0xA6), RGBColor(0xB8, 0xC2, 0xD0)
ICE, ORANGE_BG, ORANGE = RGBColor(0xCA, 0xDC, 0xF0), RGBColor(0xFD, 0xF1, 0xE6), RGBColor(0xB4, 0x5A, 0x12)
FONT = "Calibri"
N_SLIDES = 7

NOTES = {
    1: """About 1 minute.
- One sentence on the problem: the registry says what happened, notices say how, completion reports say why, and they sit in three places that nobody joins at planning time.
- I built it, not only designed it: everything runs on Azure Databricks on real public World Bank data.
- Plan for the next 15 minutes: architecture, data model, engines, evaluation, limits, then a short live demo.""",
    2: """About 2 minutes.
- Walk left to right once: sources, bronze with idempotent MERGE loads, a keyed silver model, gold tables and the graph, then the engines and the users.
- Dashed boxes are designed but not built or not public: amendments, CPIA, and the user feedback loop that starts in the pilot.
- The daily loop is proven on a replay: an incremental graph update equals a full rebuild, row for row. The daily job is defined but paused until the shadow phase.""",
    3: """About 2.5 minutes.
- Grain and keys first: one row per contract; joint-venture members live in a bridge table, because the feed repeats the full value on every member's row.
- Entity resolution: block by country, TF-IDF character trigrams, rules that stop chaining (for example common personal names get no name links).
- Graph in Delta, not a graph database: the questions are batch, two to four hops, and one copy keeps one set of permissions and lineage.""",
    4: """About 3 minutes.
- Duration model: the feed starts in FY2020, so it trains only on cohorts it can fully observe. LightGBM quantiles plus a conformal step, because raw intervals covered 68% instead of 80%.
- Agent: the LLM plans, retrieves and writes; statistics come from the benchmark table or the registered model, never from the LLM.
- Validation is code that runs whatever the model writes: unknown ids dropped, timeline numbers must equal the cited record, counts and methods checked against facts lines.""",
    5: """About 3.5 minutes.
- Backtest: 300 real tenders replayed on their notice date with everything later hidden. The deployed champion scores 50 days in-sample, which is a leak, so every evaluation refits at the cutoff.
- Fact-check, said carefully: the like-for-like baseline is also 5 of 30, on different briefs, and the gain combines facts lines, the writer rule, reasoning mode and the check. The holdout was never used for tuning.
- Labels: no person labelled items. Code decides what it can, three judges from different model families do the rest, an AI adjudicator settles disagreements with written evidence. Conflicts: the source depends on the question, and both sides are always shown.""",
    6: """About 1.5 minutes.
- Say the gaps plainly; each one has a stated workaround in data_gaps.md.
- Small samples: one brief moves the holdout rate by about 10 points, so treat these as early evidence.
- The pilot is gated: shadow mode first, and the trust KPIs must pass before any user sees an answer.""",
    7: """Demo, about 3 to 4 minutes, then questions.
- Enter a new package (country, category, method, description) and run the agent.
- Show the tool calls, then the brief, then open one cited record to prove the citation resolves to a row.
- Fallback if the endpoint is slow: the executed p08 notebook and the review briefs in data/human_review/.""",
}


# ---------- primitives ----------

def textbox(slide, x, y, w, h, paras, size=18, color=INK, bold=False, anchor=MSO_ANCHOR.TOP, align=PP_ALIGN.LEFT,
            bullets=False, space_after=6, name=None, italic=False):
    """paras: list of str, or list of runs [(text, {bold, color, size, italic})]."""
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    if name:
        box.name = name
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = Inches(0.05)
    tf.margin_top = tf.margin_bottom = Inches(0.03)
    for k, para in enumerate(paras):
        p = tf.paragraphs[0] if k == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_after = Pt(space_after)
        runs = [(para, {})] if isinstance(para, str) else para
        if bullets:
            runs = [("•  ", {"color": TEAL, "bold": True})] + list(runs)
        for t, o in runs:
            r = p.add_run()
            r.text = t
            r.font.name = FONT
            r.font.size = Pt(o.get("size", size))
            r.font.bold = o.get("bold", bold)
            r.font.italic = o.get("italic", italic)
            r.font.color.rgb = o.get("color", color)
    return box


def box(slide, x, y, w, h, fill=PANEL, line=None, dashed=False, radius=0.08, name=None, line_w=1.25):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    shape.adjustments[0] = radius
    if fill is None:
        shape.fill.background()
    else:
        shape.fill.solid()
        shape.fill.fore_color.rgb = fill
    if line is None:
        shape.line.fill.background()
    else:
        shape.line.color.rgb = line
        shape.line.width = Pt(line_w)
        if dashed:
            shape.line.dash_style = MSO_LINE_DASH_STYLE.DASH
    shape.shadow.inherit = False
    shape.text_frame.text = ""
    if name:
        shape.name = name
    return shape


def label_box(slide, x, y, w, h, lines, fill=PANEL, line=NAVY, dashed=False, size=16, color=INK, bold=True,
              align=PP_ALIGN.CENTER, name=None):
    """A rounded box with centred text; lines: list of str or run lists."""
    shape = box(slide, x, y, w, h, fill=fill, line=line, dashed=dashed, name=name)
    tf = shape.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf.margin_left = tf.margin_right = Inches(0.08)
    tf.margin_top = tf.margin_bottom = Inches(0.03)
    for k, para in enumerate(lines):
        p = tf.paragraphs[0] if k == 0 else tf.add_paragraph()
        p.alignment = align
        runs = [(para, {})] if isinstance(para, str) else para
        for t, o in runs:
            r = p.add_run()
            r.text = t
            r.font.name = FONT
            r.font.size = Pt(o.get("size", size))
            r.font.bold = o.get("bold", bold)
            r.font.color.rgb = o.get("color", color)
    return shape


def arrow(slide, x1, y1, x2, y2, color=LINE, width=2.25, head=True):
    c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    c.line.color.rgb = color
    c.line.width = Pt(width)
    if head:
        ln = c.line._get_or_add_ln()
        tail = ln.makeelement(qn("a:tailEnd"), {"type": "triangle", "w": "med", "len": "med"})
        ln.append(tail)
    return c


def title(slide, text, sub=None):
    textbox(slide, 0.5, 0.3, 12.33, 0.7, [text], size=34, color=NAVY, bold=True, name="Title")
    if sub:
        textbox(slide, 0.5, 0.98, 12.33, 0.45, [sub], size=18, color=MUTED, name="Subtitle")


def footer(slide, n):
    textbox(slide, 0.5, 7.03, 9, 0.32, ["Procurement Intelligence Platform  |  Shabad Vaswani"], size=12, color=MUTED)
    textbox(slide, 11.83, 7.03, 1.0, 0.32, [f"{n} / {N_SLIDES}"], size=12, color=MUTED, align=PP_ALIGN.RIGHT)


def stat(slide, x, y, w, h, number, label, fill=PANEL, color=NAVY, num_size=32, label_size=18, name=None):
    box(slide, x, y, w, h, fill=fill, name=name)
    textbox(slide, x + 0.2, y + 0.12, w - 0.4, 0.62, [number], size=num_size, color=color, bold=True)
    textbox(slide, x + 0.2, y + 0.12 + num_size / 72 * 1.25, w - 0.4, h - 0.3 - num_size / 72 * 1.25, [label],
            size=label_size, color=INK, space_after=0)


def background(slide, color):
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = color


# ---------- slides ----------

def slide_title(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    background(s, NAVY)
    textbox(s, 0.8, 0.9, 11.7, 0.9, ["Procurement Intelligence Platform"], size=46, color=WHITE, bold=True)
    textbox(s, 0.8, 1.9, 11.0, 1.1, [
        "Planning teams have contracts, notices and project-document lessons in separate places. "
        "This joins them into one cited planning brief."], size=24, color=ICE)
    chips = [("Contracts", "what happened", "282,890"),
             ("Notices", "how it was tendered", "379,820"),
             ("Project documents", "why it worked or failed", "21,118 passages")]
    cw, gap, y = 3.0, 0.35, 3.55
    for k, (head, what, n) in enumerate(chips):
        x = 0.8 + k * (cw + gap)
        label_box(s, x, y, cw, 1.35, [[(head, {"size": 22, "color": NAVY})],
                                      [(what, {"size": 18, "bold": False, "color": INK})],
                                      [(n, {"size": 18, "color": TEAL})]], fill=WHITE, line=None)
        arrow(s, x + cw + 0.04, y + 0.68, x + cw + gap - 0.04, y + 0.68, color=ICE, width=2.5)
    bx = 0.8 + 3 * (cw + gap)
    label_box(s, bx, y, 1.75, 1.35, [[("Cited", {"size": 22, "color": WHITE})], [("brief", {"size": 22, "color": WHITE})]],
              fill=TEAL, line=None)
    textbox(s, 0.8, 5.55, 11.7, 0.45, ["Shabad Vaswani  |  AI Engineer interview, World Bank  |  27 October 2026"],
            size=20, color=WHITE, bold=True)
    textbox(s, 0.8, 6.05, 11.7, 0.45, ["A working prototype on real World Bank open data, built on Azure Databricks"],
            size=18, color=ICE)
    return s


def slide_architecture(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    title(s, "Architecture: one governed copy, from sources to users",
          "Files, tables, graph, embeddings and models all live in the lakehouse under Unity Catalog")
    cols = [("Sources", [("Awards + notices", 0), ("Projects + ISRs", 0), ("PAD, ICR, IEG", 0), ("Amendments, CPIA", 2)]),
            ("Bronze", [("Raw page files", 0), ("MERGE + row hash", 0), ("Change Data Feed", 0), ("PDF layout parser", 0)]),
            ("Silver", [("Keyed model", 0), ("Entity resolution", 0), ("Notice-contract links", 0), ("Doc passages", 0)]),
            ("Gold", [("Tender timelines", 0), ("Knowledge graph", 0), ("Benchmarks", 0), ("Early warnings", 0)]),
            ("Engines", [("Duration model", 1), ("Cited agent", 1), ("Evidence resolver", 1), ("Tender checks", 1)]),
            ("Users", [("Cited brief", 0), ("Risk flags", 0), ("KPIs", 0), ("User feedback", 2)])]
    x0, top, gap = 0.5, 1.6, 0.3
    w = (12.33 - 5 * gap) / 6
    bh, bgap, head_h = 0.66, 0.13, 0.55
    col_h = head_h + 4 * bh + 3 * bgap + 0.2
    centers = []
    for k, (head, items) in enumerate(cols):
        x = x0 + k * (w + gap)
        centers.append(x + w / 2)
        box(s, x, top, w, col_h, fill=COLUMN_BG, line=RGBColor(0xDD, 0xE3, 0xEC), radius=0.05)
        textbox(s, x, top + 0.07, w, 0.45, [head], size=20, color=NAVY, bold=True, align=PP_ALIGN.CENTER)
        for j, (item, kind) in enumerate(items):
            y = top + head_h + j * (bh + bgap)
            if kind == 2:
                label_box(s, x + 0.07, y, w - 0.14, bh, [item], fill=WHITE, line=LINE, dashed=True, color=MUTED, size=16)
            else:
                label_box(s, x + 0.07, y, w - 0.14, bh, [item], fill=TEAL_BG if kind == 1 else PANEL,
                          line=TEAL if kind == 1 else NAVY, size=16)
        if k < 5:
            arrow(s, x + w + 0.02, top + col_h / 2, x + w + gap - 0.02, top + col_h / 2, color=LINE, width=2.5)
    bottom = top + col_h
    # daily loop: from Users back to Bronze
    loop_y = bottom + 0.32
    arrow(s, centers[5], bottom, centers[5], loop_y, color=TEAL, width=2.5, head=False)
    arrow(s, centers[5], loop_y, centers[1], loop_y, color=TEAL, width=2.5, head=False)
    arrow(s, centers[1], loop_y, centers[1], bottom + 0.02, color=TEAL, width=2.5)
    textbox(s, 0.5, loop_y + 0.06, 12.33, 0.42, [
        [("Daily loop:  ", {"bold": True, "color": TEAL}),
         ("changed rows only, the graph updated by one MERGE, drift checks, champion/challenger gate", {})]],
        size=18, align=PP_ALIGN.CENTER)
    # governance band
    gy, gw, ggap = 6.33, (12.33 - 3 * 0.15) / 4, 0.15
    for k, name in enumerate(["Unity Catalog", "MLflow", "Workflows", "Model Serving"]):
        label_box(s, 0.5 + k * (gw + ggap), gy, gw, 0.55, [name], fill=NAVY, line=None, color=WHITE, size=18)
    # legend
    lx = 9.9
    box(s, lx, 0.98 + 0.08, 0.32, 0.26, fill=WHITE, line=LINE, dashed=True, radius=0.15)
    textbox(s, lx + 0.38, 0.98, 2.6, 0.42, ["designed, not built"], size=16, color=MUTED)
    footer(s, 2)
    return s


def slide_data_model(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    title(s, "A keyed data model, and a knowledge graph built from it",
          "Grain and keys first; every graph edge comes from a key that was checked")
    nw, nh = 1.95, 0.85
    nodes = {"country": (3.0, 1.75, "country", "246"),
             "firm": (6.6, 1.75, "supplier firm", "316,398 entities"),
             "passage": (0.5, 3.5, "passage", "43,340"),
             "project": (3.0, 3.5, "project", "3,768"),
             "contract": (6.6, 3.5, "contract", "282,890"),
             "notice": (4.8, 5.25, "notice", "379,820")}
    for key, (x, y, name, n) in nodes.items():
        label_box(s, x, y, nw, nh, [[(name, {"size": 19, "color": WHITE})], [(n, {"size": 16, "bold": False, "color": ICE})]],
                  fill=NAVY, line=None, name=f"node_{key}")

    def left(k):
        x, y, *_ = nodes[k]
        return x, y + nh / 2

    def right(k):
        x, y, *_ = nodes[k]
        return x + nw, y + nh / 2

    def topc(k):
        x, y, *_ = nodes[k]
        return x + nw / 2, y

    def bottomc(k):
        x, y, *_ = nodes[k]
        return x + nw / 2, y + nh

    def edge(a, b, text, lx, ly, lw=1.9):
        arrow(s, *a, *b, color=LINE, width=2.25)
        textbox(s, lx, ly, lw, 0.36, [text], size=16, color=TEAL, bold=True)

    edge(right("passage"), left("project"), "DESCRIBES", 2.07, 3.1, 1.4)
    edge(topc("project"), bottomc("country"), "IN_COUNTRY", 4.07, 2.88, 1.45)
    edge(left("contract"), right("project"), "PART_OF", 5.2, 3.5, 1.2)
    edge(topc("contract"), bottomc("firm"), "AWARDED_TO", 5.92, 2.88, 1.6)
    edge(left("firm"), right("country"), "REGISTERED_IN", 4.97, 2.2, 1.68)
    nx, ny = nodes["notice"][:2]
    edge((nx + 0.4, ny), (4.55, 3.5 + nh), "FOR_PROJECT", 2.95, 4.62, 1.6)
    edge((nx + nw - 0.4, ny), (7.0, 3.5 + nh), "ADVERTISES", 6.95, 4.62, 1.5)
    # BID_ON: firm -> notice, routed around the right side
    fx, fy = nodes["firm"][:2]
    rx = fx + nw + 0.3
    arrow(s, fx + nw, fy + nh / 2, rx, fy + nh / 2, color=LINE, width=2.25, head=False)
    arrow(s, rx, fy + nh / 2, rx, ny + nh / 2, color=LINE, width=2.25, head=False)
    arrow(s, rx, ny + nh / 2, nx + nw, ny + nh / 2, color=LINE, width=2.25)
    textbox(s, nx + nw + 0.15, ny + nh / 2 + 0.04, 1.2, 0.36, ["BID_ON"], size=16, color=TEAL, bold=True)
    textbox(s, 0.5, 6.35, 8.3, 0.5, ["Delta node and edge tables; SQL joins and GraphFrames gave the same answer"],
            size=18, color=MUTED, italic=True)
    x, w = 9.25, 3.58
    stat(s, x, 1.65, w, 1.6, "0 orphans", "and 0 duplicate keys on 25 checks; a breach stops the notebook", num_size=30)
    stat(s, x, 3.45, w, 1.6, "261,169 firms", "from 344,273 supplier ids; precision 1.00, recall 0.90",
         fill=TEAL_BG, color=TEAL, num_size=30)
    stat(s, x, 5.25, w, 1.6, "2.28M edges", "1.03M nodes, 0 dangling edges", num_size=30)
    footer(s, 3)
    return s


def slide_engines(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    title(s, "Engines: a calibrated forecast and an agent that must cite",
          "Statistics come from models and tables; the LLM plans, retrieves and writes, and code checks it")
    # left: duration model vs peer baseline
    lx, lw = 0.5, 5.6
    textbox(s, lx, 1.6, lw, 0.45, ["Duration and slow-tender risk"], size=22, color=NAVY, bold=True)
    textbox(s, lx, 2.05, lw, 0.4, ["P50 error in days, 6,624 test tenders"], size=18, color=MUTED)
    cd = CategoryChartData()
    cd.categories = ["Model", "Peer-group lookup"]
    cd.add_series("MAE, days", (76, 88))  # proposal 3.1
    gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(lx), Inches(2.4), Inches(lw), Inches(2.55), cd)
    ch = gf.chart
    ch.has_legend = False
    ch.has_title = False
    ch.font.name = FONT
    ch.font.size = Pt(18)
    ch.font.color.rgb = INK
    plot = ch.plots[0]
    plot.gap_width = 70
    plot.has_data_labels = True
    dl = plot.data_labels
    dl.font.size = Pt(24)
    dl.font.bold = True
    dl.font.color.rgb = INK
    dl.position = XL_LABEL_POSITION.OUTSIDE_END
    dl.number_format = '0'
    dl.number_format_is_linked = False
    for i, color in enumerate([TEAL, GREY_BAR]):
        pt = plot.series[0].points[i]
        pt.format.fill.solid()
        pt.format.fill.fore_color.rgb = color
    va = ch.value_axis
    va.visible = False
    va.has_major_gridlines = False
    va.maximum_scale = 100
    va.minimum_scale = 0
    ca = ch.category_axis
    ca.tick_labels.font.size = Pt(18)
    ca.format.line.color.rgb = GREY_BAR
    stat(s, lx, 5.05, 2.7, 1.75, "80.7%", "P10-P90 coverage, after a conformal step", num_size=28, label_size=18)
    stat(s, lx + 2.9, 5.05, 2.7, 1.75, "0.747", "ROC-AUC for slow tenders; peer rate 0.584",
         num_size=28, label_size=18)
    # right: agent flow
    rx, rw = 6.65, 6.18
    textbox(s, rx, 1.6, rw, 0.45, ["Cited agent"], size=22, color=NAVY, bold=True)
    steps = [("Input guard", "Llama 3.3 checks scope and injection", ORANGE_BG, ORANGE),
             ("Planner + 5 tools", "Qwen 3.5, at most 6 tool calls", TEAL_BG, TEAL),
             ("Writer", "JSON brief, a record id on every claim", TEAL_BG, TEAL),
             ("Validation in code", "unknown ids dropped, facts checked", ORANGE_BG, ORANGE),
             ("Cited brief", "timeline, risks, precedents, evidence gaps", PANEL, NAVY)]
    sy, sh, sgap = 2.1, 0.7, 0.22
    for k, (head, desc, fill, line) in enumerate(steps):
        y = sy + k * (sh + sgap)
        shape = label_box(s, rx, y, rw, sh, [[(head + "   ", {"size": 19, "color": line}),
                                              (desc, {"size": 18, "bold": False, "color": INK})]],
                          fill=fill, line=line, align=PP_ALIGN.LEFT)
        shape.text_frame.margin_left = Inches(0.18)
        if k < len(steps) - 1:
            arrow(s, rx + 0.6, y + sh, rx + 0.6, y + sh + sgap, color=LINE, width=2.25)
    textbox(s, rx, sy + 5 * sh + 4 * sgap + 0.1, rw, 0.42, ["The model is never the last check."], size=18,
            color=TEAL, bold=True, italic=True)
    footer(s, 4)
    return s


def slide_evaluation(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    title(s, "Evaluation and trust",
          "Tested as of the notice date, with every label's origin stated")
    tw, tgap, ty, th = (12.33 - 2 * 0.3) / 3, 0.3, 1.6, 2.45
    tiles = [("87 vs 100 days", "timeline error on 300 real tenders replayed as of their notice date: model vs peer lookup",
              PANEL, NAVY),
             ("5 → 2 of 30", "briefs with an unsupported claim, before and after facts lines and a code fact-check; "
              "1 of 10 on a holdout", TEAL_BG, TEAL),
             ("35 of 68", "projects IEG rated unsatisfactory still had a satisfactory last ISR; both sides are shown",
              PANEL, NAVY)]
    for k, (num, lab, fill, color) in enumerate(tiles):
        stat(s, 0.5 + k * (tw + tgap), ty, tw, th, num, lab, fill=fill, color=color, num_size=40)
    textbox(s, 0.5, 4.35, 12.33, 0.45, ["How the evaluation labels were made"], size=22, color=NAVY, bold=True)
    steps = [("1  Code", "decides what it can: range hit, citation validity"),
             ("2  Three LLM judges", "from different model families, one rubric"),
             ("3  AI adjudicator", "settles disagreements, writes its evidence")]
    sw, sgap, sy, sh = 3.75, 0.54, 4.85, 1.15
    for k, (head, desc) in enumerate(steps):
        x = 0.5 + k * (sw + sgap)
        label_box(s, x, sy, sw, sh, [[(head, {"size": 19, "color": NAVY})], [(desc, {"size": 18, "bold": False})]],
                  fill=WHITE, line=NAVY, align=PP_ALIGN.LEFT)
        if k < 2:
            arrow(s, x + sw + 0.05, sy + sh / 2, x + sw + sgap - 0.05, sy + sh / 2, color=LINE, width=2.5)
    textbox(s, 0.5, 6.22, 12.33, 0.45, [[("No item was labelled by a person. ", {"bold": True, "color": TEAL}),
                                          ("Procurement specialists validate the labels in the pilot.", {})]], size=18)
    footer(s, 5)
    return s


def slide_limits(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    title(s, "Limits and next steps",
          "What is not built, what the public data cannot show, and what a pilot would add")
    cols = [("Not built yet", PANEL, NAVY, [
                "A check that a cited passage supports its sentence",
                "Vector Search over every PAD and ICR",
                "Daily job defined, paused until the shadow phase"]),
            ("Data gaps", PANEL, NAVY, [
                "Amendments, milestones and payments are not public (STEP)",
                "Awards only from FY2020; no CPIA",
                "Lessons from 300 of about 8,100 ICRs"]),
            ("What the pilot adds", TEAL_BG, TEAL, [
                "Shadow mode, 4 to 6 weeks: answers logged, not shown",
                "2 or 3 hubs, 15 to 30 specialists; staff decide",
                "Specialists label 100+ packages and check the AI labels"])]
    cw, gap, y, h = (12.33 - 2 * 0.3) / 3, 0.3, 1.6, 3.65
    for k, (head, fill, color, items) in enumerate(cols):
        x = 0.5 + k * (cw + gap)
        box(s, x, y, cw, h, fill=fill)
        textbox(s, x + 0.25, y + 0.2, cw - 0.5, 0.5, [head], size=24, color=color, bold=True)
        textbox(s, x + 0.25, y + 0.85, cw - 0.45, h - 1.0, items, size=18, bullets=True, space_after=14)
    box(s, 0.5, 5.55, 12.33, 1.0, fill=ORANGE_BG)
    textbox(s, 0.75, 5.6, 11.9, 0.9, [[("Small samples:  ", {"bold": True, "color": ORANGE}),
                                         ("20 agent packages, 30 + 10 reviewed briefs; one brief moves the holdout rate "
                                          "by about 10 points", {})]], size=18, anchor=MSO_ANCHOR.MIDDLE)
    footer(s, 6)
    return s


def slide_close(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    background(s, NAVY)
    textbox(s, 0.8, 1.0, 11.7, 1.1, ["Demo"], size=60, color=WHITE, bold=True)
    textbox(s, 0.8, 2.15, 11.7, 0.6, ["A new package in, a cited planning brief out"], size=26, color=ICE)
    steps = ["Enter a package", "Watch the tool calls", "Open a cited record"]
    cw, gap, y = 3.2, 0.45, 3.2
    for k, st in enumerate(steps):
        x = 0.8 + k * (cw + gap)
        label_box(s, x, y, cw, 0.85, [[(f"{k + 1}  ", {"color": TEAL, "size": 22}), (st, {"size": 20, "color": NAVY})]],
                  fill=WHITE, line=None)
        if k < 2:
            arrow(s, x + cw + 0.05, y + 0.425, x + cw + gap - 0.05, y + 0.425, color=ICE, width=2.5)
    textbox(s, 0.8, 4.75, 11.7, 0.7, ["Thank you. Questions welcome."], size=32, color=WHITE, bold=True)
    link = textbox(s, 0.8, 5.55, 11.7, 0.55, [REPO_URL.replace("https://", "")], size=22, color=ICE)
    link.click_action.hyperlink.address = REPO_URL  # shape-level link keeps the text colour readable
    textbox(s, 0.8, 6.15, 11.7, 0.45, ["Shabad Vaswani"], size=20, color=ICE)
    return s


def build() -> Path:
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    makers = [slide_title, slide_architecture, slide_data_model, slide_engines, slide_evaluation, slide_limits, slide_close]
    for k, make in enumerate(makers, start=1):
        slide = make(prs)
        slide.notes_slide.notes_text_frame.text = NOTES[k]
    prs.core_properties.title = "Procurement Intelligence Platform"
    prs.core_properties.author = "Shabad Vaswani"
    prs.save(OUT)
    return OUT


if __name__ == "__main__":
    print("pptx", build())
