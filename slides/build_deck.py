"""Build the 5-slide presentation deck (PPTX) and, when PowerPoint or LibreOffice is available, its PDF.

    pip install python-pptx            # only this script needs it
    python docs/build_docs.py          # figures as PNG first
    python slides/build_deck.py

Speaker notes are read from docs/speaker_notes.md ("## Slide N" sections), so the notes have one source.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "docs" / "figures"
OUT = Path(__file__).resolve().parent / "procurement_intelligence.pptx"

NAVY, TEAL, INK, MUTED = RGBColor(0x1F, 0x3A, 0x5F), RGBColor(0x0F, 0x76, 0x6E), RGBColor(0x1F, 0x29, 0x37), RGBColor(0x5B, 0x64, 0x72)
PANEL, TEAL_BG, WHITE = RGBColor(0xEE, 0xF4, 0xFB), RGBColor(0xE6, 0xF4, 0xF1), RGBColor(0xFF, 0xFF, 0xFF)
FONT = "Calibri"


def notes_by_slide() -> dict[int, str]:
    text = (ROOT / "docs" / "speaker_notes.md").read_text(encoding="utf-8")
    parts = re.split(r"^## Slide (\d+)\..*$", text, flags=re.M)
    notes = {}
    for k in range(1, len(parts) - 1, 2):
        body = parts[k + 1].split("\n## ")[0].strip()
        notes[int(parts[k])] = re.sub(r"[*`]", "", body)
    return notes


def textbox(slide, x, y, w, h, paras, size=14, color=INK, bold=False, anchor=MSO_ANCHOR.TOP, align=PP_ALIGN.LEFT,
            bullets=False, space_after=4, name=None):
    """paras: list of str or list of [(text, {bold, color, size})] runs."""
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    if name:
        box.name = name
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = Inches(0.04)
    tf.margin_top = tf.margin_bottom = Inches(0.02)
    for k, para in enumerate(paras):
        p = tf.paragraphs[0] if k == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_after = Pt(space_after)
        runs = [(para, {})] if isinstance(para, str) else para
        if bullets:
            runs = [("\u2022  ", {"color": TEAL, "bold": True})] + runs
        for t, o in runs:
            r = p.add_run()
            r.text = t
            r.font.name = FONT
            r.font.size = Pt(o.get("size", size))
            r.font.bold = o.get("bold", bold)
            r.font.color.rgb = o.get("color", color)
    return box


def panel(slide, x, y, w, h, fill=PANEL, line=None, name=None):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    shape.adjustments[0] = 0.06
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    if line is None:
        shape.line.fill.background()
    else:
        shape.line.color.rgb = line
        shape.line.width = Pt(1)
    shape.shadow.inherit = False
    if name:
        shape.name = name
    return shape


def picture(slide, name, x, y, w):
    path = FIG / f"{name}.png"
    return slide.shapes.add_picture(str(path), Inches(x), Inches(y), width=Inches(w))


def title(slide, text, sub=None):
    textbox(slide, 0.5, 0.32, 12.3, 0.7, [text], size=30, color=NAVY, bold=True, name="Title")
    if sub:
        textbox(slide, 0.5, 0.98, 12.3, 0.4, [sub], size=15, color=MUTED, name="Subtitle")


def footer(slide, n):
    textbox(slide, 0.5, 7.08, 9, 0.3, ["Procurement Intelligence Platform  |  prototype on World Bank open data, Azure Databricks"],
            size=10, color=MUTED)
    textbox(slide, 12.0, 7.08, 0.83, 0.3, [f"{n} / 5"], size=10, color=MUTED, align=PP_ALIGN.RIGHT)


def section(slide, x, y, w, head, items, size=13.5, head_color=NAVY):
    textbox(slide, x, y, w, 0.34, [head], size=15, color=head_color, bold=True)
    return textbox(slide, x, y + 0.36, w, 0.3 * len(items) + 0.3, items, size=size, bullets=True, space_after=3)


def stat(slide, x, y, w, h, number, label, fill=PANEL, color=NAVY):
    panel(slide, x, y, w, h, fill=fill)
    textbox(slide, x + 0.18, y + 0.08, w - 0.3, 0.55, [number], size=26, color=color, bold=True)
    textbox(slide, x + 0.18, y + 0.6, w - 0.3, h - 0.65, [label], size=12, color=INK)


def build() -> Path:
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    blank = prs.slide_layouts[6]
    notes = notes_by_slide()
    slides = []

    # 1. Problem and what I built
    s = prs.slides.add_slide(blank)
    slides.append(s)
    title(s, "Procurement intelligence on real World Bank data",
          "The registry says what happened, notices say how, completion reports say why. I joined them and built the platform.")
    picture(s, "architecture_slide", 0.5, 1.75, 8.55)
    tiles = [("282,890", "contracts, linked to 379,820 notices and 3,768 projects"),
             ("261,169", "supplier firms resolved from 344,273 ids; precision 1.00, recall 0.90"),
             ("75 vs 88 days", "duration error on 6,624 test tenders: model trained before them vs the peer lookup"),
             ("300 tenders", "replayed as of their notice date to test the whole platform, with nothing later visible")]
    for k, (n, label) in enumerate(tiles):
        stat(s, 9.35, 1.55 + k * 1.33, 3.48, 1.2, n, label, fill=TEAL_BG if k == 3 else PANEL, color=TEAL if k == 3 else NAVY)
    footer(s, 1)

    # 2. Data model and knowledge graph
    s = prs.slides.add_slide(blank)
    slides.append(s)
    title(s, "One keyed data model, and a knowledge graph built from it",
          "Grain and keys first; every graph edge comes from a key that was checked for duplicates and orphans")
    picture(s, "er_kg_slide", 0.5, 1.45, 8.0)
    panel(s, 0.5, 5.98, 8.0, 1.0, fill=TEAL_BG)
    textbox(s, 0.68, 6.03, 7.7, 0.92, [
        [("Brief's example, contract row to ICR lesson:  ", {"bold": True, "color": TEAL}),
         ("contract -PART_OF-> project -> completion-report passage of that project, or the nearest passages by embedding "
          "within country and sector. Dates decide whether a lesson explains the contract or is a precedent for a new one.", {})]],
        size=12.5)
    x, w = 8.8, 4.03
    section(s, x, 1.5, w, "Entity resolution", [
        "blocked by country; TF-IDF trigrams",
        "rules stop chaining; common names not merged",
        "P 1.00, R 0.90 on 97 pairs; audit 34 of 40"])
    section(s, x, 3.35, w, "Tender timelines", [
        "notice-contract links in 4 tiers, each audited",
        "44.9% of open contracts timed; median 158 days",
        "joint-venture amounts kept once per contract"])
    section(s, x, 5.2, w, "Knowledge graph in Delta", [
        "1.03M nodes, 2.28M edges, 0 dangling",
        "same answer from SQL joins and GraphFrames"])
    footer(s, 2)

    # 3. AI methods
    s = prs.slides.add_slide(blank)
    slides.append(s)
    title(s, "A calibrated duration model and an agent that must cite",
          "Statistics come from models and tables; the LLM plans, retrieves and writes, and code checks what it wrote")
    picture(s, "agent", 1.4, 1.4, 10.5)
    cards = [(0.5, "Duration model", PANEL, [
                 "trained only on fully observable cohorts",
                 "conformal P10-P90: 80.7% coverage",
                 "package fields only: 91 vs 85 days for the peer group; with notice facts 60 (20 indicative cases)"]),
             (4.66, "Tender and execution checks", PANEL, [
                 "672 of 1,939 international tenders advertised < 30 business days: 4.9 vs 5.6 bidders",
                 "1,340 active projects: 73 red, 238 amber, reasons cited"])]
    for x, head, fill, items in cards:
        panel(s, x, 4.6, 3.96, 2.15, fill=fill)
        section(s, x + 0.17, 4.66, 3.65, head, items, size=12.5)
    panel(s, 8.82, 4.6, 4.01, 2.15, fill=WHITE, line=TEAL)
    textbox(s, 8.98, 4.66, 3.72, 2.25, [
        [("Brief excerpt: rural roads, Kenya", {"bold": True, "color": TEAL, "size": 15})],
        [("Timeline: median 119 days to signing, P90 540. ", {}),
         ("[benchmark:country_method_category-5fa286a9]", {"color": MUTED, "size": 10.5})],
        [("Risk: works awarded in the rainy season stall; sequence awards to the dry season. ", {}),
         ("[lesson_chunk:P123828-34118211-0110]", {"color": MUTED, "size": 10.5})]], size=12.5, space_after=6)
    footer(s, 3)

    # 4. Trust
    s = prs.slides.add_slide(blank)
    slides.append(s)
    title(s, "Trust: a backtest as of the notice date, flagged conflicts, stated gaps",
          "300 real tenders replayed with everything later hidden; the deployed model's in-sample score is shown as a leak")
    picture(s, "results", 0.5, 1.5, 7.4)
    panel(s, 0.5, 4.15, 7.4, 1.95, fill=PANEL)
    section(s, 0.68, 4.21, 7.1, "Backtest on 300 replayed tenders", [
        "timeline error 87 days (95% CI 77-98) vs 100 for the peer lookup; slow-flag AUC 0.74 vs 0.58",
        "precedents: 77% of those shown relevant; 73% of packages get one, 19% none",
        "30 full briefs: actual inside the cited range 20/30; unsupported claim 5/30",
        "labels: code checks, then 3 LLM judges, then an AI adjudicator with evidence"], size=12.5)
    textbox(s, 0.5, 6.32, 7.4, 0.6, [[("Guardrails:  ", {"bold": True, "color": NAVY}),
                                      ("input guard 3/3; code drops ids no tool returned; 19 of 20 briefs judged grounded", {})]],
            size=12.5)
    stat(s, 8.25, 1.5, 4.58, 1.45, "35 of 68",
         "projects IEG rated unsatisfactory still had a satisfactory last ISR (400 closed projects)", fill=TEAL_BG, color=TEAL)
    section(s, 8.25, 3.1, 4.58, "Conflict policy", [
        "outcome: IEG > ICR > last ISR > earlier ISR",
        "current status: newest ISR, marked stale when old",
        "both sides shown with a flag and confidence"], size=13)
    section(s, 8.25, 4.85, 4.58, "Data gaps, handled openly", [
        "amendments and milestones not public (STEP)",
        "plain chunking lost 26.8% of table rows; fixed",
        "awards from FY2020 only; 300 of ~8,100 ICRs"], size=13)
    footer(s, 4)

    # 5. Rollout
    s = prs.slides.add_slide(blank)
    slides.append(s)
    title(s, "Rollout: a closed learning loop and a gated pilot",
          "Incremental updates proven on real data; each pilot phase has a go/no-go threshold")
    picture(s, "learning_loop_slide", 0.5, 1.5, 6.6)
    section(s, 0.5, 3.8, 6.6, "Proven on a replay of real notices", [
        "934 inserts + 100 corrections -> 3,290 graph inserts, 50 deletes",
        "incremental result = full rebuild = production: 0 differences"], size=13)
    section(s, 0.5, 5.15, 6.6, "KPIs, stored in pilot_kpis with baseline and target", [
        "planning cycle time: 160 days today; -10% in pilot hubs vs similar hubs",
        "precision@5 >= 0.70; valid citations >= 0.95; freshness >= 0.95",
        "adoption >= 50% weekly; positive feedback >= 70%"], size=13)
    phases = [("0  Shadow, 4-6 weeks", "answers logged, not shown; trust KPIs must pass"),
              ("1  Assisted pilot, 3 months", "2-3 regional hubs, 15-30 specialists; staff decide"),
              ("2  Scale-out", "all regions, inside STEP planning; rollback = move @champion")]
    for k, (h, d) in enumerate(phases):
        y = 1.5 + k * 1.02
        panel(s, 7.45, y, 5.38, 0.9, fill=PANEL if k else TEAL_BG)
        textbox(s, 7.62, y + 0.06, 5.1, 0.35, [h], size=14.5, color=TEAL if k == 0 else NAVY, bold=True)
        textbox(s, 7.62, y + 0.42, 5.1, 0.45, [d], size=13)
    section(s, 7.45, 4.65, 5.38, "First 90 days", [
        "full ICR and PAD corpus behind the lessons tool",
        "amendment feed and a tender-package entity",
        "labelled evaluation set with specialists; shadow mode"], size=13)
    footer(s, 5)

    for k, slide in enumerate(slides, start=1):
        slide.notes_slide.notes_text_frame.text = notes.get(k, "")
    prs.save(OUT)
    return OUT


def export_pdf(pptx: Path) -> Path | None:
    """PDF via LibreOffice with a throwaway profile (never touches a running Office); None if it is not installed."""
    pdf = pptx.with_suffix(".pdf")
    soffice = shutil.which("soffice") or r"C:\Program Files\LibreOffice\program\soffice.exe"
    if not Path(soffice).exists():
        return None
    with tempfile.TemporaryDirectory() as profile:
        subprocess.run([soffice, f"-env:UserInstallation={Path(profile).as_uri()}", "--headless", "--convert-to", "pdf",
                        "--outdir", str(pptx.parent), str(pptx)], capture_output=True, timeout=240)
    return pdf if pdf.exists() else None


if __name__ == "__main__":
    deck = build()
    print("pptx", deck)
    print("pdf", export_pdf(deck))
