"""Agreement between the owner's labels in review_briefs.csv and the automatic scores (judges and rules).

Fill the columns timeline_ok (1/0), precedents_relevant (0-5), risks_relevant (0-5), any_unsupported_claim (1/0)
and notes in review_briefs.csv, then run from the repository root:

    .venv/Scripts/python data/human_review/score_labels.py

Only rows with at least one label are counted. The same computation runs in p11 section 5b.
"""
import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "src"))

from proc_intel.backtest import review_agreement  # noqa: E402


def main(path: str = os.path.join(HERE, "review_briefs.csv")) -> dict:
    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    result = review_agreement(rows)
    print(json.dumps(result, indent=1, default=str))
    return result


if __name__ == "__main__":
    main(*sys.argv[1:])
