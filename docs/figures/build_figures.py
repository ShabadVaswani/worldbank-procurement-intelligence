"""Write the proposal and slide diagrams as small hand-laid SVG files (standard library only).

    python docs/figures/build_figures.py

Solid boxes are built and run on real data; dashed boxes are designed but not built. Every number
in a figure is one that the notebooks measured (see docs/proposal.md for the sources).
"""
from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parent

NAVY, TEAL, INK, MUTED, LINE = "#1F3A5F", "#0F766E", "#1F2937", "#5B6472", "#8A94A6"
FILL, PANEL, ENGINE, WARN = "#EEF4FB", "#F6F8FB", "#E6F4F1", "#FFF7ED"
FONT = "Inter, 'Segoe UI', Arial, sans-serif"

# Status line under the two lifecycle stages that phase-3 components build (p13 tender checks, p14 early warnings).
STAGE_STATUS = {"Tender design": "built on real data (p13)", "Execution and monitoring": "built on real data (p14)"}


class Svg:
    def __init__(self, width: int, height: int):
        self.w, self.h, self.parts = width, height, []

    def add(self, s: str) -> None:
        self.parts.append(s)

    def text(self, x, y, s, size=11, weight=400, color=INK, anchor="start", italic=False) -> None:
        style = ' font-style="italic"' if italic else ""
        self.add(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{color}" '
                 f'text-anchor="{anchor}"{style}>{escape(s)}</text>')

    def rect(self, x, y, w, h, fill=FILL, stroke=NAVY, dashed=False, rx=6, width=1.2) -> None:
        dash = ' stroke-dasharray="5 4"' if dashed else ""
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}" '
                 f'stroke-width="{width}"{dash}/>')

    def box(self, x, y, w, h, title, lines=(), fill=FILL, stroke=NAVY, dashed=False, size=11, title_size=12) -> None:
        self.rect(x, y, w, h, fill=fill, stroke=LINE if dashed else stroke, dashed=dashed)
        self.text(x + 9, y + 17, title, size=title_size, weight=600, color=MUTED if dashed else NAVY)
        for k, line in enumerate(lines):
            self.text(x + 9, y + 33 + k * (size + 3), line, size=size, color=MUTED if dashed else INK)

    def arrow(self, x1, y1, x2, y2, color=LINE, width=1.4, dashed=False, label=None, label_dx=0, label_dy=-4,
              label_color=TEAL, label_size=10, label_weight=600) -> None:
        dash = ' stroke-dasharray="5 4"' if dashed else ""
        self.add(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{width}"{dash} '
                 f'marker-end="url(#arrow)"/>')
        if label:
            mx, my = (x1 + x2) / 2 + label_dx, (y1 + y2) / 2 + label_dy
            self.label(mx, my, label, color=label_color, size=label_size, weight=label_weight)

    def path(self, d, color=LINE, width=1.4, dashed=False, marker=True) -> None:
        dash = ' stroke-dasharray="5 4"' if dashed else ""
        end = ' marker-end="url(#arrow)"' if marker else ""
        self.add(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}"{dash}{end}/>')

    def label(self, x, y, s, color=TEAL, size=10, weight=600, anchor="middle") -> None:
        w = len(s) * size * 0.58 + 8
        x0 = x - w / 2 if anchor == "middle" else x - 4
        self.add(f'<rect x="{x0:.1f}" y="{y - size:.1f}" width="{w:.1f}" height="{size + 5}" fill="#FFFFFF" opacity="0.92"/>')
        self.text(x, y, s, size=size, weight=weight, color=color, anchor=anchor)

    def save(self, name: str) -> None:
        head = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}" width="{self.w}" '
                f'height="{self.h}" font-family="{FONT}">'
                '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
                f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{LINE}"/></marker></defs>'
                f'<rect width="{self.w}" height="{self.h}" fill="#FFFFFF"/>')
        (OUT / name).write_text(head + "".join(self.parts) + "</svg>\n", encoding="utf-8")


def legend(s: Svg, x: int, y: int) -> None:
    s.rect(x, y - 10, 22, 13, rx=3)
    s.text(x + 28, y, "built and run on real data", size=10, color=MUTED)
    s.rect(x + 190, y - 10, 22, 13, fill="#FFFFFF", stroke=LINE, dashed=True, rx=3)
    s.text(x + 218, y, "designed, not built yet", size=10, color=MUTED)


def architecture() -> None:
    s = Svg(1200, 700)
    cols = [("Sources", 16, 196), ("Bronze", 232, 176), ("Silver", 428, 200), ("Gold", 648, 186),
            ("Engines", 854, 196), ("Users", 1070, 116)]
    for name, x, w in cols:
        s.rect(x - 6, 14, w + 12, 588, fill=PANEL, stroke="#E2E8F0", rx=10)
        s.text(x + w / 2, 36, name, size=14, weight=700, color=NAVY, anchor="middle")
    for (_, x, w), (_, nx, _) in zip(cols, cols[1:], strict=False):
        s.arrow(x + w + 4, 300, nx - 4, 300, color=NAVY, width=2)

    y0, step = 52, 88
    src = [("Contract awards", ["FinancesOne DS00005", "295,058 rows, FY2020+"]),
           ("Procurement notices", ["search API, 2018+", "416,745 with HTML text"]),
           ("Projects API", ["3,768 projects: sector,", "commitment, E&S category"]),
           ("Documents API", ["PAD, ISR, ICR, ICR Review", "text renderings"]),
           ("Governance, finance", ["WGI; IEG ratings dataset;", "IBRD/IDA loan statements"])]
    for k, (t, ls) in enumerate(src):
        s.box(16, y0 + k * step, 196, 74, t, ls)
    s.box(16, y0 + 5 * step, 196, 74, "Not public or not yet", ["amendments, milestones,", "CPIA, PPARs, CPFs"], dashed=True,
          fill="#FFFFFF")

    bronze = [("Raw volume", ["one file per API page;", "a restart skips saved pages"]),
              ("Bronze tables", ["MERGE on key + row hash;", "soft delete; change feed on"]),
              ("Document text", ["1,200 rating documents,", "300 ICRs, with hashes"])]
    for k, (t, ls) in enumerate(bronze):
        s.box(232, 80 + k * 120, 176, 88, t, ls)
    s.box(232, 440, 176, 88, "Layout PDF parser", ["headings, tables, captions;", "10 PADs, 941 pages (p12)"])

    silver = [("Keyed relational model", ["contracts, notices, bidders,", "projects, dims; 25 key checks"]),
              ("Entity resolution", ["344,273 supplier ids", "-> 261,169 firms; P 0.97 R 0.90"]),
              ("Notice-contract links", ["4 tiers, each audited;", "64,065 tender links"]),
              ("Ratings evidence", ["last / mid ISR, ICR, IEG;", "2,381 ratings, 400 projects"]),
              ("Passages + embeddings", ["section path, date, hash;", "21,118 used by the agent"])]
    for k, (t, ls) in enumerate(silver):
        s.box(428, y0 + k * 106, 200, 86, t, ls)

    gold = [("tender_timelines", ["56,156 timed contracts"]),
            ("Knowledge graph", ["1.03M nodes, 2.28M edges"]),
            ("tender_benchmarks", ["715 peer groups"]),
            ("open_tender_scores", ["6,005 open notices"]),
            ("evidence_resolution", ["800 resolved answers"]),
            ("flags, warnings, KPIs", ["3,227 design flags; 1,340", "projects scored; 9 KPIs"])]
    for k, (t, ls) in enumerate(gold):
        s.box(648, y0 + k * 90, 186, 62, t, ls)

    engines = [("Duration + slow-risk", ["LightGBM quantile + conformal", "UC model @champion"], ENGINE),
               ("Procurement agent", ["guard, planner, tools, writer,", "validation in code"], ENGINE),
               ("Evidence resolver", ["source order per question,", "conflict flags"], ENGINE),
               ("Tender + execution checks", ["p13 design vs policy and peers;", "p14 early warnings, cited"], ENGINE)]
    for k, (t, ls, f) in enumerate(engines):
        s.box(854, 70 + k * 128, 196, 96, t, ls, fill=f, stroke=TEAL)

    users = [("Cited planning", ["brief"]), ("Benchmarks,", ["risk flags"]), ("Monitoring,", ["KPIs"])]
    for k, (t, ls) in enumerate(users):
        s.box(1070, 90 + k * 120, 116, 70, t, ls)
    s.box(1070, 450, 116, 70, "User feedback", ["pilot ratings"], dashed=True, fill="#FFFFFF")

    s.path("M1128,522 L1128,584 L320,584 L320,532", color=TEAL, dashed=True)
    s.label(724, 588, "daily loop: change feed -> graph MERGE, re-embed changed passages, drift, retrain gate",
            color=TEAL, size=10.5)

    band = [("Unity Catalog", "permissions, lineage, audit, keys"),
            ("MLflow", "experiments, agent traces, registry"),
            ("Workflows / Asset Bundle", "pipeline + daily incremental job"),
            ("Model Serving", "Qwen 3.5, Llama 3.3 guard, GTE-large")]
    for k, (t, d) in enumerate(band):
        x = 16 + k * 295
        s.rect(x, 614, 284, 48, fill=NAVY, stroke=NAVY, rx=6)
        s.text(x + 12, 634, t, size=12, weight=700, color="#FFFFFF")
        s.text(x + 12, 652, d, size=10.5, color="#DCE6F2")
    legend(s, 16, 688)
    s.save("architecture.svg")


def er_kg() -> None:
    s = Svg(1210, 660)

    def entity(x, y, w, name, rows, layer="silver"):
        h = 26 + 15 * len(rows) + 8
        s.rect(x, y, w, h, fill="#FFFFFF", stroke=NAVY)
        s.add(f'<rect x="{x}" y="{y}" width="{w}" height="24" rx="6" fill="{NAVY}"/>')
        s.text(x + 9, y + 16, name, size=12, weight=700, color="#FFFFFF")
        s.text(x + w - 8, y + 16, layer, size=9.5, color="#DCE6F2", anchor="end")
        for k, r in enumerate(rows):
            weight = 600 if r.startswith(("PK", "FK")) else 400
            s.text(x + 9, y + 40 + 15 * k, r, size=10.5, weight=weight, color=INK if weight == 600 else MUTED)
        return x, y, w, h

    c1, c2, c3, c4 = 20, 310, 630, 950
    pas = entity(c1, 30, 230, "document / lesson chunk",
                 ["PK chunk_id", "FK project_id", "doc_type, doc_date", "section path, text_hash", "embedding (GTE-large)"])
    rat = entity(c1, 250, 230, "project_ratings_evidence",
                 ["FK project_id", "source_type: isr_last, isr_earlier,", "  icr_self_rating, ieg_validation",
                  "dimension, rating, as_of, doc_id"])
    cy = entity(c1, 440, 230, "country_year", ["PK country_iso2, year", "WGI + macro indicators,",
                                               "joined for the year before", "the notice"], layer="reused")
    prj = entity(c2, 150, 220, "dim_project", ["PK project_id", "FK country_code", "region, sector, approval_date",
                                               "commitment, env_category"])
    ntc = entity(c2, 390, 220, "notices", ["PK notice_id", "FK project_id", "notice_type, method, category",
                                           "notice_date, deadline"])
    cty = entity(c3, 24, 220, "dim_country", ["PK country_code (ISO2 or region)"])
    con = entity(c3, 170, 220, "contracts", ["PK contract_id", "FK project_id, borrower_country", "method, category, signing_date",
                                             "amount (once per contract)"])
    lnk = entity(c3, 370, 220, "notice_contract_links", ["PK notice_id, contract_id", "link_role: tender | award",
                                                         "match_tier, days_to_signing"])
    tl = entity(c3, 500, 220, "tender_timelines", ["PK contract_id (1:1 contracts)", "days_notice_to_signing, is_timed"],
                layer="gold")
    ent = entity(c4, 24, 240, "supplier_entities", ["PK supplier_entity_id", "FK country_code", "canonical name, n_ids"])
    sup = entity(c4, 170, 240, "suppliers + entity map", ["PK supplier_id", "FK supplier_entity_id",
                                                           "is_anonymised_individual"])
    cs = entity(c4, 300, 240, "contract_suppliers", ["PK contract_id, supplier_id", "joint-venture member rows"])
    nb = entity(c4, 420, 240, "notice_bidders", ["PK notice_id, supplier_id", "role: awarded | evaluated | rejected",
                                                 "parsed from award notice HTML"])

    def right(b, f=0.5):
        return b[0] + b[2], b[1] + b[3] * f

    def left(b, f=0.5):
        return b[0], b[1] + b[3] * f

    def top(b, f=0.5):
        return b[0] + b[2] * f, b[1]

    def bottom(b, f=0.5):
        return b[0] + b[2] * f, b[1] + b[3]

    def link(a, b, text="", dx=0, dy=-4, color=LINE):
        s.arrow(*a, *b, color=color, label=text or None, label_dx=dx, label_dy=dy)

    link(right(pas, 0.6), left(prj, 0.3), "DESCRIBES", dy=-10)
    link(right(rat, 0.3), left(prj, 0.75))
    link(right(cy, 0.4), left(ntc, 0.8))
    link(top(prj, 0.7), left(cty, 0.6), "IN_COUNTRY", dx=-10)
    link(top(ntc), bottom(prj), "FOR_PROJECT", dx=46)
    link(left(con, 0.45), right(prj, 0.45), "PART_OF")
    link(right(ntc, 0.3), left(lnk, 0.3), "ADVERTISES /", dy=-12)
    s.label(570, 412, "ANNOUNCES", color=TEAL)
    link(top(lnk), bottom(con), "notice -> contract", dx=58)
    link(bottom(lnk), top(tl), "durations", dx=40, color="#C7CED9")
    link(left(cs, 0.5), right(con, 0.75), "AWARDED_TO", dx=4, dy=-8)
    link(top(cs), bottom(sup))
    link(top(sup), bottom(ent), "N:1 (entity resolution)", dx=72)
    link(left(ent, 0.5), right(cty, 0.6), "REGISTERED_IN")
    link(top(nb, 0.85), bottom(cs, 0.85))
    s.text(c4 + 196, 412, "FK supplier_id", size=9.5, color=MUTED, anchor="end")
    nx, ny = left(nb, 0.75)
    s.path(f"M{nx},{ny} L{nx - 40},{ny} L{nx - 40},608 L{c2 + 110},608 L{c2 + 110},{ntc[1] + ntc[3] + 2}")
    s.label(760, 612, "BID_ON (role)", color=TEAL)

    s.text(20, 648, "Grey arrows: keys in the silver model (declared in Unity Catalog, checked for duplicates and orphans). "
           "Teal capitals: the knowledge-graph edge built from those keys (proc_gold.kg_edges).", size=10.5, color=MUTED)
    s.save("er_kg.svg")


def lifecycle() -> None:
    s = Svg(1200, 400)
    stages = [("Planning and strategy", ["peer benchmarks P10/P50/P90", "duration model forecast", "similar past contracts",
                                         "appraisal risk passages"], "built"),
              ("Tender design", ["advertising period vs peers", "similar specifications", "lessons on spec problems",
                                 "design checks"], "W3"),
              ("Evaluation and award", ["bidders per notice and roles", "supplier profile, co-bidders",
                                        "resolved firm history", "thin-competition signal"], "built"),
              ("Execution and monitoring", ["slow-tender score", "open tenders past their P90", "newest ISR ratings",
                                            "early warnings"], "W3"),
              ("Completion and learning", ["ISR vs ICR vs IEG resolver", "ICR lessons into the index",
                                           "change feed refresh", "retrain trigger + gate"], "built")]
    w, gap = 222, 12
    for k, (name, caps, status) in enumerate(stages):
        x = 16 + k * (w + gap)
        pts = f"{x},40 {x + w - 16},40 {x + w},68 {x + w - 16},96 {x},96 {x + 16 if k else x},68"
        s.add(f'<polygon points="{pts}" fill="{NAVY}"/>')
        s.text(x + w / 2, 73, name, size=13.5, weight=700, color="#FFFFFF", anchor="middle")
        dashed = status != "built"
        s.rect(x, 112, w - 10, 172, fill=FILL if not dashed else "#FFFFFF", stroke=NAVY, dashed=False)
        for j, c in enumerate(caps):
            s.text(x + 12, 140 + j * 24, c, size=12, color=INK)
        tag = "built on real data" if status == "built" else STAGE_STATUS[name]
        s.text(x + 12, 272, tag, size=10.5, weight=600, color=TEAL)
    s.path("M1058,286 L1058,330 L122,330 L122,290", color=TEAL, dashed=True)
    s.label(600, 334, "completion reports, IEG reviews and new contracts flow back into the next package's plan",
            color=TEAL, size=11)
    s.text(16, 384, "Every stage reads the same governed tables; the agent cites the record behind each statement.",
           size=11, color=MUTED)
    s.save("lifecycle.svg")


def agent() -> None:
    s = Svg(1200, 352)
    s.box(16, 120, 150, 92, "New package", ["country, category,", "method, description"])
    s.box(196, 120, 150, 92, "Input guard", ["Llama 3.3: scope,", "injection; text is data"], fill=WARN, stroke="#B45309")
    s.box(376, 120, 170, 92, "Planner", ["Qwen 3.5, at most", "6 tool calls, coverage", "check adds a missed tool"],
          fill=ENGINE, stroke=TEAL)
    tools = [("similar_past_contracts", "TF-IDF top 30 + GTE re-rank"), ("tender_benchmark", "peer group P50 / P90"),
             ("forecast_timeline", "registered duration model"), ("lessons_learned", "21,118 passages, filters"),
             ("supplier_profile", "graph edges, ~4.5 s")]
    for k, (t, d) in enumerate(tools):
        s.box(586, 14 + k * 62, 230, 52, t, [d], size=10.5)
        s.arrow(546, 166, 584, 40 + k * 62, color="#C7CED9", width=1)
    s.box(856, 120, 150, 92, "Writer", ["JSON brief in a", "fixed schema; ids", "on every claim"], fill=ENGINE, stroke=TEAL)
    s.box(1036, 96, 150, 140, "Validation in code", ["unknown ids dropped", "uncited risks removed", "numbers vs benchmark",
                                                       "status lowered", "-> cited brief or", "insufficient evidence"],
          fill=WARN, stroke="#B45309")
    s.arrow(166, 166, 194, 166)
    s.arrow(346, 166, 374, 166)
    s.path("M816,166 L854,166")
    s.text(835, 158, "records", size=9.5, color=MUTED, anchor="middle")
    s.arrow(1006, 166, 1034, 166)
    s.text(16, 342, "Orange: deterministic or independent checks. Teal: LLM steps. One MLflow trace per run records "
           "the guard, every tool call, the records returned and the brief.", size=10.5, color=MUTED)
    s.save("agent.svg")


def guardrails() -> None:
    s = Svg(1100, 470)
    layers = [("1  Input guard", "a second model family classifies scope and injection; free text is wrapped as data", "model"),
              ("2  Tool arguments", "schema check, numeric coercion, country and method resolution; invalid calls counted", "code"),
              ("3  Evidence only from tools", "records passed as delimited blocks with ids; tool output is data, not instructions",
               "prompt"),
              ("4  Evidence strength", "weak precedents, no benchmark or distant lessons -> 'insufficient evidence'", "code"),
              ("5  Citation validation", "ids no tool returned are dropped; uncited risks removed; status lowered", "code"),
              ("6  Numeric check", "timeline numbers must match the cited benchmark or model forecast", "code"),
              ("7  Conflict flags", "disagreeing sources shown side by side with dates, flag and confidence", "code"),
              ("8  Trace and human review", "MLflow trace per run; feedback stored with model and prompt version", "people")]
    color = {"model": "#B45309", "code": TEAL, "prompt": LINE, "people": NAVY}
    for k, (t, d, kind) in enumerate(layers):
        y = 20 + k * 54
        inset = k * 6
        s.rect(16 + inset, y, 1068 - 2 * inset, 44, fill=FILL if kind != "code" else ENGINE, stroke=color[kind])
        s.text(32 + inset, y + 27, t, size=13, weight=700, color=NAVY)
        s.text(290, y + 27, d, size=11.5, color=INK)
        s.text(1068 - inset, y + 27, kind, size=10.5, weight=600, color=color[kind], anchor="end")
    s.text(16, 458, "Teal layers are deterministic code with unit tests; they run whatever the model writes.",
           size=11, color=MUTED)
    s.save("guardrails.svg")


def learning_loop() -> None:
    s = Svg(1150, 520)
    steps = [(30, 40, "1  Daily MERGE", ["awards + notices;", "unchanged rows untouched"]),
             (310, 40, "2  Change Data Feed", ["changed keys since", "the last checkpoint"]),
             (590, 40, "3  Graph MERGE", ["notice neighbourhood in", "one commit; refresh queue"]),
             (870, 40, "4  Re-embed", ["only new or changed", "passages (content hash)"]),
             (870, 210, "5  Drift checks", ["PSI on inputs, KS on", "durations; signing-date windows"]),
             (870, 380, "6  Retrain trigger", ["drift, error or age, and", ">= 1,000 new labels"]),
             (590, 380, "7  Champion / challenger", ["same newest window, by", "segment; move @champion"]),
             (310, 380, "8  New ICRs, IEG reviews", ["evidence tables and", "lessons corpus updated"]),
             (30, 380, "9  Pilot KPIs, feedback", ["refreshed daily;", "back to the backlog"])]
    w, h = 250, 86
    for x, y, t, ls in steps:
        s.box(x, y, w, h, t, ls, fill=ENGINE if t[0] in "3456" else FILL, stroke=TEAL if t[0] in "3456" else NAVY)
    for (x1, y1, *_), (x2, y2, *_) in zip(steps, steps[1:], strict=False):
        if y1 == y2:
            if x2 > x1:
                s.arrow(x1 + w, y1 + h / 2, x2 - 2, y2 + h / 2)
            else:
                s.arrow(x1, y1 + h / 2, x2 + w + 2, y2 + h / 2)
        else:
            s.arrow(x1 + w / 2, y1 + h, x2 + w / 2, y2 - 2)
    s.arrow(30 + w / 2, 380, 30 + w / 2, 128)
    s.rect(310, 168, 530, 170, fill="#FFFFFF", stroke="#E2E8F0", rx=10)
    s.text(575, 196, "Proof on a replay of real notices", size=13, weight=700, color=NAVY, anchor="middle")
    for k, line in enumerate(["7 held-back days + 100 corrected notices",
                              "bronze: 934 inserts, 100 updates",
                              "graph: 3,290 inserts, 50 deletes (not 1.36M rewritten)",
                              "incremental = full rebuild = production: 0 differences",
                              "drift on the latest run: stable (PSI <= 0.085)"]):
        s.text(330, 224 + k * 22, line, size=12, color=INK)
    s.text(30, 506, "Teal: model and index maintenance. Rollback = move the @champion alias back; serving code never changes.",
           size=11, color=MUTED)
    s.save("learning_loop.svg")


def results() -> None:
    """Two small bar charts for the slides (one highlight hue + neutral; the invalid bar is a dashed outline)."""
    s = Svg(1100, 370)
    hi, base = TEAL, "#B8C2D0"

    def bars(x0, title, unit, items, vmax, note, fmt="{:g}"):
        s.text(x0, 30, title, size=15, weight=700, color=NAVY)
        s.text(x0, 50, unit, size=11.5, color=MUTED)
        top, height, bw, gap = 74, 210, 92, 46
        s.add(f'<line x1="{x0}" y1="{top + height}" x2="{x0 + len(items) * (bw + gap)}" y2="{top + height}" '
              f'stroke="#CBD5E1" stroke-width="1"/>')
        for k, (name, v, kind) in enumerate(items):
            h = height * v / vmax
            x = x0 + 10 + k * (bw + gap)
            y = top + height - h
            d = (f"M{x},{top + height} L{x},{y + 4} Q{x},{y} {x + 4},{y} L{x + bw - 4},{y} Q{x + bw},{y} "
                 f"{x + bw},{y + 4} L{x + bw},{top + height} Z")
            if kind == "invalid":
                s.add(f'<path d="{d}" fill="#FFFFFF" stroke="{LINE}" stroke-width="1.5" stroke-dasharray="5 4"/>')
            else:
                s.add(f'<path d="{d}" fill="{hi if kind == "best" else base}"/>')
            s.text(x + bw / 2, y - 8, fmt.format(v), size=14, weight=700 if kind == "best" else 500,
                   color=MUTED if kind == "invalid" else INK, anchor="middle")
            for j, part in enumerate(name.split("|")):
                s.text(x + bw / 2, top + height + 20 + 15 * j, part, size=11.5, color=MUTED if kind == "invalid" else INK,
                       anchor="middle")
        s.text(x0, top + height + 76, note, size=10.5, color=MUTED)

    bars(20, "Tender duration error, 6,624 test tenders", "mean absolute error of P50, days; lower is better",
         [("model refit|at the cutoff", 75, "best"), ("peer-group|lookup", 88, "base"),
          ("deployed model,|in-sample (leaks)", 50, "invalid")], 100,
         "The deployed @champion was refit on these tenders, so its 50 days is not a result.")
    bars(600, "Lessons that named a real problem", "100 projects; did the project's own ICR report it? (LLM judge)",
         [("retrieved|lessons", 38, "best"), ("random|passages", 8, "base")], 45,
         "Yes or partly: 84% vs 22%. Judge agrees with an AI agent's blind spot-check on 13 of 15.", fmt="{:g}%")
    s.save("results.svg")


# Slide versions: fewer words and larger type, because a slide shows the figure at about half the size of a page.

def architecture_slide() -> None:
    s = Svg(1172, 560)
    cols = {"Sources": ["Contract awards", "Procurement notices", "Projects", "PAD, ISR, ICR docs", "WGI, IEG, loans",
                        "~Amendments, CPIA"],
            "Bronze": ["Raw page files", "MERGE + row hash", "Document text", "PDF layout parser"],
            "Silver": ["Keyed model", "Entity resolution", "Notice-contract links", "Ratings evidence", "Doc passages"],
            "Gold": ["Tender timelines", "Knowledge graph", "Benchmarks", "Open tender scores", "Evidence resolution"],
            "Engines": ["Duration model", "Procurement agent", "Evidence resolver", "Tender checks"],
            "Users": ["Cited brief", "Risk flags", "KPIs", "~User feedback"]}
    w, gap = 172, 23
    for c, (name, items) in enumerate(cols.items()):
        x = 8 + c * (w + gap)
        s.rect(x - 4, 6, w + 8, 448, fill=PANEL, stroke="#E2E8F0", rx=10)
        s.text(x + w / 2, 34, name, size=18, weight=700, color=NAVY, anchor="middle")
        for k, item in enumerate(items):
            dashed = item.startswith("~")
            fill = "#FFFFFF" if dashed else (ENGINE if name == "Engines" else FILL)
            stroke = LINE if dashed else (TEAL if name == "Engines" else NAVY)
            s.rect(x, 50 + k * 66, w, 54, fill=fill, stroke=stroke, dashed=dashed)
            s.text(x + w / 2, 83 + k * 66, item.lstrip("~"), size=15, weight=600, color=MUTED if dashed else INK,
                   anchor="middle")
        if c < len(cols) - 1:
            s.arrow(x + w + 3, 230, x + w + gap - 3, 230, color=NAVY, width=2.4)
    band = ["Unity Catalog", "MLflow", "Workflows", "Model Serving"]
    for k, t in enumerate(band):
        s.rect(4 + k * 292, 470, 284, 46, fill=NAVY, stroke=NAVY, rx=6)
        s.text(4 + k * 292 + 142, 500, t, size=16, weight=700, color="#FFFFFF", anchor="middle")
    s.rect(8, 532, 26, 16, rx=3)
    s.text(42, 545, "built on real data", size=13, color=MUTED)
    s.rect(220, 532, 26, 16, fill="#FFFFFF", stroke=LINE, dashed=True, rx=3)
    s.text(254, 545, "designed, not built yet", size=13, color=MUTED)
    s.save("architecture_slide.svg")


def er_kg_slide() -> None:
    s = Svg(1110, 620)
    boxes = {}

    def ent(key, x, y, name, rows, w=206, layer=""):
        h = 30 + 18 * len(rows) + 8
        s.rect(x, y, w, h, fill="#FFFFFF", stroke=NAVY)
        s.add(f'<rect x="{x}" y="{y}" width="{w}" height="28" rx="6" fill="{NAVY}"/>')
        s.text(x + 9, y + 20, name, size=15, weight=700, color="#FFFFFF")
        if layer:
            s.text(x + w - 8, y + 20, layer, size=12, color="#DCE6F2", anchor="end")
        for k, r in enumerate(rows):
            s.text(x + 9, y + 47 + 18 * k, r, size=13, weight=600, color=INK)
        boxes[key] = (x, y, w, h)

    ent("pas", 10, 70, "passages", ["PK chunk_id", "FK project_id"], layer="text")
    ent("rat", 10, 240, "ratings evidence", ["FK project_id", "source, rating, date"])
    ent("prj", 296, 150, "project", ["PK project_id", "FK country_code"])
    ent("ntc", 296, 370, "notices", ["PK notice_id", "FK project_id"])
    ent("cty", 600, 36, "country", ["PK country_code"])
    ent("con", 600, 200, "contracts", ["PK contract_id", "FK project_id, country"])
    ent("lnk", 600, 370, "notice_contract_links", ["PK notice_id, contract_id"])
    ent("tl", 600, 490, "tender_timelines", ["PK contract_id"], layer="gold")
    ent("ent", 894, 36, "supplier_entities", ["PK supplier_entity_id"])
    ent("cs", 894, 200, "contract_suppliers", ["PK contract_id, supplier_id", "-> supplier_entity_map"])
    ent("nb", 894, 370, "notice_bidders", ["PK notice_id, supplier_id", "role: awarded | evaluated"])
    b = boxes

    def pt(k, side, f=0.5):
        x, y, w, h = b[k]
        return {"r": (x + w, y + h * f), "l": (x, y + h * f), "t": (x + w * f, y), "b": (x + w * f, y + h)}[side]

    def link(a, c, text="", dx=0, dy=-5):
        s.arrow(*a, *c, width=1.8, label=text or None, label_dx=dx, label_dy=dy, label_size=12.5)

    link(pt("pas", "r", 0.6), pt("prj", "l", 0.3), "DESCRIBES", dy=-14)
    link(pt("rat", "r", 0.4), pt("prj", "l", 0.8))
    link(pt("prj", "t", 0.7), pt("cty", "l", 0.6), "IN_COUNTRY", dx=-24, dy=-2)
    link(pt("ntc", "t"), pt("prj", "b"), "FOR_PROJECT", dx=58)
    link(pt("con", "l", 0.45), pt("prj", "r", 0.6), "PART_OF", dy=-8)
    link(pt("ntc", "r", 0.5), pt("lnk", "l", 0.5), "ADVERTISES", dy=-14)
    link(pt("lnk", "t"), pt("con", "b"))
    link(pt("lnk", "b"), pt("tl", "t"), "", dx=0)
    link(pt("cs", "l", 0.5), pt("con", "r", 0.5), "AWARDED_TO", dy=-10)
    link(pt("cs", "t"), pt("ent", "b"), "N:1", dx=24)
    link(pt("ent", "l", 0.6), pt("cty", "r", 0.6))
    s.label(851, 24, "REGISTERED_IN", color=TEAL, size=12.5)
    x, y = pt("nb", "b", 0.5)
    s.path(f"M{x},{y} L{x},598 L{b['ntc'][0] + 103},598 L{b['ntc'][0] + 103},{b['ntc'][1] + b['ntc'][3] + 2}", width=1.8)
    s.label(700, 603, "BID_ON (role)", color=TEAL, size=12.5)
    s.save("er_kg_slide.svg")


def learning_loop_slide() -> None:
    s = Svg(772, 250)
    steps = [("1 Daily MERGE", "awards, notices"), ("2 Change feed", "changed keys"), ("3 Graph MERGE", "one commit"),
             ("4 Re-embed", "changed passages"), ("5 Drift checks", "PSI, KS"), ("6 Retrain trigger", ">= 1,000 labels"),
             ("7 Champion gate", "move @champion"), ("8 New ICRs, IEG", "evidence, lessons"), ("9 KPIs, feedback", "to the backlog")]
    w, h, gap = 136, 64, 20
    pos = [(4 + k * (w + gap), 10) for k in range(5)] + [(4 + (4 - k) * (w + gap), 160) for k in range(4)]
    for (x, y), (t, d) in zip(pos, steps, strict=True):
        model = t[0] in "3456"
        s.rect(x, y, w, h, fill=ENGINE if model else FILL, stroke=TEAL if model else NAVY)
        s.text(x + 10, y + 26, t, size=14, weight=700, color=NAVY)
        s.text(x + 10, y + 47, d, size=12.5, color=INK)
    for (x1, y1), (x2, y2) in zip(pos, pos[1:], strict=False):
        if y1 == y2:
            s.arrow(x1 + w, y1 + h / 2, x2 - 2, y2 + h / 2) if x2 > x1 else s.arrow(x1, y1 + h / 2, x2 + w + 2, y2 + h / 2)
        else:
            s.arrow(x1 + w / 2, y1 + h, x2 + w / 2, y2 - 2)
    s.path(f"M{pos[-1][0]},{pos[-1][1] + h / 2} L{pos[0][0] + 30},{pos[-1][1] + h / 2} L{pos[0][0] + 30},{pos[0][1] + h + 2}")
    s.save("learning_loop_slide.svg")


if __name__ == "__main__":
    for build in (architecture, er_kg, lifecycle, agent, guardrails, learning_loop, results,
                  architecture_slide, er_kg_slide, learning_loop_slide):
        build()
    print("wrote", sorted(p.name for p in OUT.glob("*.svg")))
