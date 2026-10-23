"""Export an executed Databricks job-run notebook (with its outputs) as a Jupyter .ipynb file.

    python tools/export_executed.py <task_run_id> executed/p01_ingest_awards.ipynb

`databricks jobs export-run` returns the run as a self-contained HTML page whose notebook model
(commands + results) is embedded as base64 / URL-encoded JSON. This script decodes that model
and writes markdown cells for %md commands and code cells with their text, table, HTML and
image outputs. Uses the Databricks CLI profile `wb`.
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import urllib.parse

PROFILE = "wb"


def run_html(task_run_id: str) -> str:
    env = {**os.environ, "MSYS_NO_PATHCONV": "1"}
    out = subprocess.run(["databricks", "-p", PROFILE, "jobs", "export-run", task_run_id,
                          "--views-to-export", "CODE", "-o", "json"],
                         capture_output=True, text=True, check=True, env=env).stdout
    return json.loads(out)["views"][0]["content"]


def notebook_model(html: str) -> dict:
    encoded = re.search(r"__DATABRICKS_NOTEBOOK_MODEL = '([^']+)'", html).group(1)
    return json.loads(urllib.parse.unquote(base64.b64decode(encoded).decode("utf-8")))


_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _lines(text: str) -> list[str]:
    parts = _ANSI.sub("", text).split("\n")
    return [p + "\n" for p in parts[:-1]] + [parts[-1]]


def _table_text(results: dict) -> str:
    cols = [c["name"] for c in results.get("schema", [])]
    rows = results.get("data", [])
    widths = [max([len(str(c))] + [len(str(r[i])) for r in rows]) for i, c in enumerate(cols)]
    fmt = " | ".join(f"{{:<{w}}}" for w in widths)
    body = [fmt.format(*cols), "-+-".join("-" * w for w in widths)] + [fmt.format(*map(str, r)) for r in rows]
    return "\n".join(body)


def outputs(command: dict) -> list[dict]:
    results = command.get("results") or {}
    kind, data = results.get("type"), results.get("data")
    out: list[dict] = []
    if kind == "table":
        out.append({"output_type": "execute_result", "execution_count": None, "metadata": {},
                    "data": {"text/plain": _lines(_table_text(results))}})
    elif kind == "html" and data:
        text = re.sub(r"<[^>]+>", "", data)
        out.append({"output_type": "display_data", "metadata": {},
                    "data": {"text/html": _lines(data), "text/plain": _lines(text.strip())}})
    elif kind == "image" and data:
        out.append({"output_type": "display_data", "metadata": {}, "data": {"image/png": data.split(",")[-1]}})
    elif kind == "listResults":
        for item in data or []:
            out.extend(outputs({"results": item}))
    elif data:
        out.append({"output_type": "stream", "name": "stdout", "text": _lines(str(data))})
    if command.get("errorSummary") or command.get("error"):
        err = re.sub(r"<[^>]+>", "", command.get("errorSummary") or command.get("error") or "")
        out.append({"output_type": "stream", "name": "stderr", "text": _lines(err)})
    return out


def to_ipynb(model: dict, task_run_id: str) -> dict:
    cells = []
    for i, cmd in enumerate(sorted(model["commands"], key=lambda c: c.get("position", 0))):
        source = cmd.get("command", "")
        if not source.strip():      # sub-commands of a %run notebook: shown in that notebook, not here
            continue
        if source.lstrip().startswith("%md"):
            text = re.sub(r"^\s*%md\s?", "", source, count=1)
            cells.append({"cell_type": "markdown", "metadata": {}, "source": _lines(text), "id": f"cell-{i:03d}"})
        else:
            cells.append({"cell_type": "code", "metadata": {}, "execution_count": None, "source": _lines(source),
                          "outputs": outputs(cmd), "id": f"cell-{i:03d}"})
    return {"nbformat": 4, "nbformat_minor": 5, "cells": cells,
            "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"},
                         "language_info": {"name": "python"},
                         "databricks_run": {"task_run_id": task_run_id,
                                            "note": "Outputs captured from a Databricks job run."}}}


def main(task_run_id: str, path: str) -> None:
    notebook = to_ipynb(notebook_model(run_html(task_run_id)), task_run_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(notebook, f, indent=1, ensure_ascii=False)
    print(f"wrote {path}: {len(notebook['cells'])} cells")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
