"""Merge the owner's adjudication decisions with the label panel's answers into final_labels.csv, then print the metrics.

    .venv/Scripts/python data/human_review/apply_adjudication.py [decisions.csv] [panel_labels.csv]
        [--out final_labels.csv] [--pairs-from final_labels.csv]

- decisions.csv: the file "Download my decisions (CSV)" on adjudicate.html saves (default:
  data/human_review/adjudication_decisions.csv; missing file = no decisions yet).
- panel_labels.csv: written by notebooks/p15_label_panel (panel value, votes, disagreement flag per item x field).
- --out: the merged file (default data/human_review/final_labels.csv).
- --pairs-from: a final_labels file whose pair rows are taken as they are, for a run that relabelled the briefs
  only (p15 on review_briefs_v2.csv writes panel_labels_v2.csv without pairs). For the re-measured review pack:
      apply_adjudication.py adjudication_decisions_v2.csv panel_labels_v2.csv --out final_labels_v2.csv --pairs-from final_labels.csv

A field the panel agreed on keeps the panel's value; a field it disagreed on takes the owner's decision, or stays
"pending" (left out of every metric, and counted) until the owner decides it.
Metrics: entity-resolution precision / recall of the pipeline's link decision (threshold 0.70, as p04 scores it:
both records in one entity) against the final pair labels, and the review-pack summary of the 30 briefs.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "src"))

from proc_intel.panel import agreement_with, er_labels, final_value, review_summary  # noqa: E402
from proc_intel.similarity import precision_recall, wilson_interval  # noqa: E402

FIELDS = ["item_type", "item_id", "field", "final_value", "source", "panel_value", "earlier_label", "pipeline_same", "n_listed"]


def read_csv(path: str) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def merge(panel_rows: list[dict], decisions: list[dict]) -> list[dict]:
    """One final row per item x field (see the module docstring for the rule)."""
    owner = {(d["item_type"], d["item_id"], d["field"]): d.get("owner_value") for d in decisions}
    # who decided an escalated item (e.g. "owner" or "tier3_ai_agent"); defaults to "owner"
    decided_by = {(d["item_type"], d["item_id"], d["field"]): d.get("adjudicator") or "owner" for d in decisions}
    out = []
    for r in panel_rows:
        key = (r["item_type"], r["item_id"], r["field"])
        value, source = final_value(r["field"], r["panel_value"] or None, r["needs_owner"] == "1", owner.get(key))
        if source == "owner":
            source = decided_by.get(key, "owner")
        out.append({**{k: r.get(k, "") for k in FIELDS}, "final_value": value or "", "source": source})
    return out


def er_metrics(final: list[dict]) -> dict:
    pairs = [r for r in final if r["item_type"] == "pair"]
    labels = er_labels([r["final_value"] or None for r in pairs])
    kept = [(y, r["pipeline_same"] in ("1", "1.0", "True")) for y, r in zip(labels, pairs, strict=True) if y is not None]
    pr = precision_recall([y for y, _ in kept], [p for _, p in kept])
    p_ci = wilson_interval(pr["tp"], pr["tp"] + pr["fp"])
    r_ci = wilson_interval(pr["tp"], pr["tp"] + pr["fn"])
    return {"pairs_scored": len(kept), "pairs_unsure_or_pending": len(pairs) - len(kept),
            "same_firm": sum(y for y, _ in kept), "tp": pr["tp"], "fp": pr["fp"], "fn": pr["fn"],
            "precision": round(pr["precision"], 3), "precision_95ci": [round(x, 2) for x in p_ci],
            "recall": round(pr["recall"], 3), "recall_95ci": [round(x, 2) for x in r_ci]}


def brief_rows(final: list[dict]) -> list[dict]:
    by_brief: dict[str, dict] = {}
    for r in final:
        if r["item_type"] == "brief":
            row = by_brief.setdefault(r["item_id"], {"review_id": r["item_id"]})
            row[r["field"]] = r["final_value"] or None
            if r["field"] == "precedents_relevant":
                row["n_precedents"] = int(float(r["n_listed"] or 0))
    return list(by_brief.values())


def with_pairs_from(final: list[dict], pairs_path: str) -> list[dict]:
    """The pair rows of an earlier final_labels file, then the briefs of `final` (which must hold no pairs)."""
    if any(r["item_type"] == "pair" for r in final):
        raise ValueError("--pairs-from is for a briefs-only panel file, but this one has pair rows")
    pairs = [{k: r.get(k, "") for k in FIELDS} for r in read_csv(pairs_path) if r["item_type"] == "pair"]
    if not pairs:
        raise ValueError(f"no pair rows in {pairs_path}")
    return pairs + final


def main(decisions_path: str = os.path.join(HERE, "adjudication_decisions.csv"),
         panel_path: str = os.path.join(HERE, "panel_labels.csv"),
         out_path: str = os.path.join(HERE, "final_labels.csv"),
         pairs_from: str | None = None) -> dict:
    panel_rows = read_csv(panel_path)
    decisions = read_csv(decisions_path) if os.path.exists(decisions_path) else []
    final = merge(panel_rows, decisions)
    if pairs_from:
        final = with_pairs_from(final, pairs_from)
    with open(out_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(final)

    sources = Counter((r["item_type"], r["source"]) for r in final)
    earlier = {f"{t} {f}": agreement_with([r["earlier_label"] or None for r in final if (r["item_type"], r["field"]) == (t, f)],
                                          [r["final_value"] or None for r in final if (r["item_type"], r["field"]) == (t, f)])
               for t, f in sorted({(r["item_type"], r["field"]) for r in final}) if f != "risks_relevant"}
    result = {"decisions_file": decisions_path if decisions else "(none yet)", "panel_file": panel_path,
              "pairs_from": pairs_from or "(this panel file)",
              "fields_by_source": {f"{t} {s}": n for (t, s), n in sorted(sources.items())},
              "entity_resolution_at_0.70": er_metrics(final),
              "review_pack": review_summary(brief_rows(final)),
              "agreement_with_earlier_automated_labels": earlier}
    print(json.dumps(result, indent=1, default=str))
    pending = sum(n for (_, s), n in sources.items() if s == "pending")
    if pending:
        print(f"\n{pending} field(s) still pending: decide them on adjudicate.html, download the CSV and run again.")
    print(f"wrote {out_path} ({len(final)} rows)")
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Merge adjudication decisions with the panel labels into a final_labels file.")
    ap.add_argument("decisions", nargs="?", default=os.path.join(HERE, "adjudication_decisions.csv"))
    ap.add_argument("panel", nargs="?", default=os.path.join(HERE, "panel_labels.csv"))
    ap.add_argument("--out", default=os.path.join(HERE, "final_labels.csv"))
    ap.add_argument("--pairs-from", default=None, help="final_labels file whose pair rows are reused (briefs-only runs)")
    a = ap.parse_args()
    main(a.decisions, a.panel, a.out, a.pairs_from)
