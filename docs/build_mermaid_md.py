# ruff: noqa: E501  (Mermaid node labels are data and read better on one line)
"""Write docs/proposal_mermaid.md: the proposal with each SVG figure replaced by an equivalent Mermaid diagram.

Run after any edit to docs/proposal.md:  python docs/build_mermaid_md.py
"""
from pathlib import Path

DOCS = Path(__file__).parent

ARCHITECTURE = """flowchart LR
    subgraph S["Sources"]
        s1["Contract awards<br/>FinancesOne DS00005<br/>295,058 rows, FY2020+"]
        s2["Procurement notices<br/>search API, 2018+<br/>416,745 with HTML text"]
        s3["Projects API<br/>3,768 projects"]
        s4["Documents API<br/>PAD, ISR, ICR, ICR Review"]
        s5["Governance, finance<br/>WGI, IEG ratings, loan statements"]
        s6["Not public / not yet ingested<br/>amendments, milestones, CPIA, PPARs, CPFs"]:::designed
    end
    subgraph B["Bronze"]
        b1["Raw volume<br/>one file per API page, resumable"]
        b2["Bronze tables<br/>MERGE on key + row hash, change feed"]
        b3["Document text<br/>ratings documents, ICRs"]
        b4["Layout PDF parser<br/>headings, tables, captions"]
    end
    subgraph SV["Silver"]
        v1["Keyed relational model<br/>contracts, notices, bidders, projects, dims"]
        v2["Entity resolution<br/>344,273 ids -> 261,169 firms<br/>P 1.00, R 0.90"]
        v3["Notice-contract links<br/>64,065 tender links"]
        v4["Ratings evidence<br/>2,381 ratings, 400 projects"]
        v5["Passages + embeddings<br/>section path, date, hash"]
    end
    subgraph G["Gold"]
        g1["tender_timelines"]
        g2["Knowledge graph<br/>1.03M nodes, 2.28M edges"]
        g3["tender_benchmarks<br/>715 peer groups"]
        g4["open_tender_scores<br/>6,005 open notices"]
        g5["evidence_resolution"]
        g6["design flags, early warnings, KPIs"]
    end
    subgraph E["Engines"]
        e1["Duration + slow-risk model<br/>LightGBM quantile + conformal<br/>UC model @champion"]
        e2["Procurement agent<br/>guard, planner, tools, writer,<br/>validation in code"]
        e3["Evidence resolver<br/>source order, conflict flags"]
        e4["Tender + execution checks<br/>p13 design checks, p14 early warnings"]
    end
    subgraph U["Users"]
        u1["Cited planning brief"]
        u2["Benchmarks, risk flags"]
        u3["Monitoring, KPIs"]
        u4["User feedback<br/>pilot ratings"]
    end
    S --> B --> SV --> G --> E --> U
    U -. "daily loop: change feed -> graph MERGE, re-embed changed passages, drift, retrain gate" .-> B
    P["Platform: Unity Catalog (permissions, lineage, audit) | MLflow (experiments, traces, registry) | Workflows / Asset Bundle | Model Serving (Qwen 3.5, Llama 3.3 guard, GTE-large)"]
    classDef designed stroke-dasharray: 5 5"""

LIFECYCLE = """flowchart LR
    p1["1. Planning and strategy<br/>peer benchmarks P10/P50/P90<br/>duration model forecast<br/>similar past contracts<br/>appraisal risk passages<br/><b>built</b>"]
    p2["2. Tender design<br/>advertising period vs peers<br/>similar specifications<br/>lessons on spec problems<br/>design checks<br/><b>built on real data (p13)</b>"]
    p3["3. Evaluation and award<br/>bidders per notice and roles<br/>supplier profile, co-bidders<br/>resolved firm history<br/>thin-competition signal<br/><b>built</b>"]
    p4["4. Execution and monitoring<br/>slow-tender score<br/>open tenders past their P90<br/>newest ISR ratings<br/>early warnings<br/><b>built on real data (p14)</b>"]
    p5["5. Completion and learning<br/>ISR vs ICR vs IEG resolver<br/>ICR lessons into the index<br/>change feed refresh<br/>retrain trigger + gate<br/><b>built</b>"]
    p1 --> p2 --> p3 --> p4 --> p5
    p5 -. "completion reports, IEG reviews and new contracts flow back into the next package's plan" .-> p1"""

AGENT = """flowchart TD
    pkg["new package<br/>{country, category, method, description}"]
    guard["input guard<br/>(Llama 3.3, JSON: in_scope / injection)"]
    planner["planner LLM<br/>(Qwen 3.5)"]
    subgraph tools["tools (at most 6 calls)"]
        t1["similar_past_contracts<br/>TF-IDF + GTE re-rank, 282,890 contracts"]
        t2["tender_benchmark<br/>peer groups P10/P50/P90"]
        t3["forecast_timeline<br/>ml.proc_tender_duration@champion"]
        t4["lessons_learned<br/>appraisal + completion passages"]
        t5["supplier_profile<br/>knowledge graph"]
    end
    writer["writer LLM<br/>(JSON brief)"]
    validate["validation in code<br/>unknown ids dropped, uncited risks removed,<br/>timeline numbers equal the cited records,<br/>only close precedents kept"]
    brief["cited brief"]
    pkg --> guard --> planner
    planner -->|"tool calls"| tools
    tools -->|"records with stable ids"| writer
    planner --> writer
    writer --> validate --> brief"""

GUARDRAILS = """flowchart TD
    req["request: new procurement package"]
    l1["1. Input guard (model)<br/>a second model family classifies scope and injection; free text wrapped as data"]
    l2["2. Tool arguments (code)<br/>schema check, numeric coercion, country and method resolution"]
    l3["3. Evidence only from tools (prompt)<br/>records passed as delimited blocks with ids; tool output is data, not instructions"]
    l4["4. Evidence strength (code)<br/>weak precedents, no benchmark or distant lessons -> 'insufficient evidence'"]
    l5["5. Citation validation (code)<br/>ids no tool returned are dropped; uncited risks removed; status lowered"]
    l6["6. Numeric check (code)<br/>timeline numbers must match the cited benchmark or model forecast"]
    l7["7. Conflict flags (code)<br/>disagreeing sources shown side by side with dates, flag and confidence"]
    l8["8. Trace and human review (people)<br/>MLflow trace per run; feedback stored with model and prompt version"]
    brief["brief"]
    req --> l1 --> l2 --> l3 --> l4 --> l5 --> l6 --> l7 --> l8 --> brief"""

LEARNING_LOOP = """flowchart TD
    apis["APIs (awards, notices, documents)"]
    bronze["bronze"]
    keys["changed keys"]
    silver["silver rows of those keys"]
    kg["KG nodes / edges<br/>(incremental MERGE)"]
    stats["timelines, supplier stats<br/>(refresh affected contracts / entities)"]
    chunks["document chunks<br/>(embed only new or changed chunks)"]
    drift["drift checks (PSI, KS)"]
    chall["challenger trained (p07 recipe)"]
    champ["@champion"]
    kpis["pilot KPIs + user feedback"]
    backlog["back to the backlog"]
    apis -->|"daily MERGE (row hash: unchanged rows not rewritten)"| bronze
    bronze -->|"Change Data Feed"| keys --> silver
    silver --> kg
    silver --> stats
    silver --> chunks
    kg --> drift
    stats --> drift
    chunks --> drift
    drift -->|"retrain trigger"| chall
    chall -->|"champion / challenger gate"| champ
    champ --> kpis --> backlog"""

FIGURES = {
    "figures/architecture.svg": ARCHITECTURE,
    "figures/lifecycle.svg": LIFECYCLE,
    "figures/er_model.png": (DOCS / "figures" / "er_model.mmd").read_text(encoding="utf-8").rstrip(),
    "figures/kg_edges.png": (DOCS / "figures" / "kg_edges.mmd").read_text(encoding="utf-8").rstrip(),
    "figures/agent.svg": AGENT,
    "figures/guardrails.svg": GUARDRAILS,
    "figures/learning_loop.svg": LEARNING_LOOP,
}


def main() -> None:
    lines = (DOCS / "proposal.md").read_text(encoding="utf-8").splitlines()
    out, replaced = [], []
    for line in lines:
        hit = next((p for p in FIGURES if line.startswith("![") and f"({p})" in line), None)
        if hit is None:
            out.append(line)
            continue
        caption = line[2:line.index("](")]
        out += [f"*Figure: {caption}*", "", "```mermaid", FIGURES[hit], "```"]
        replaced.append(hit)
    missing = set(FIGURES) - set(replaced)
    if missing:
        raise SystemExit(f"figure references not found in proposal.md: {sorted(missing)}")
    (DOCS / "proposal_mermaid.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote docs/proposal_mermaid.md ({len(replaced)} diagrams as Mermaid)")


if __name__ == "__main__":
    main()
