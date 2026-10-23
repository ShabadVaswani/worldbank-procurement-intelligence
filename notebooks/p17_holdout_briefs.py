# Databricks notebook source
# MAGIC %md
# MAGIC # p17_holdout_briefs — the phase-5 agent on 10 packages it was not tuned on
# MAGIC
# MAGIC The phase-5 changes to the agent (a `facts` line on every contract record, writer rule 10, the code fact-check, writer thinking on, and the second-round changes of p16) were designed by reading the 30 review briefs of p11 and checked on the same 30. A change tuned on a set can look better on that set than it is. This notebook replays **10 fresh packages** that no one has read, with the same agent, the same replay and the same scoring, so the two packs can be compared.
# MAGIC
# MAGIC ```
# MAGIC  p11 test period (notices from 2023-07-01, openly competed, timed)
# MAGIC    minus p11's 300-package sample (its contracts, notices and projects; the 30 review packages are inside it)
# MAGIC    minus packages without a usable notice description
# MAGIC        |
# MAGIC        v
# MAGIC  pick_holdout: 10 slots cycling CW, GO, CS, NC; fixed hash order (seed 11); prefer a new region,
# MAGIC  then a new region x category, then a new method; one package per notice and per project
# MAGIC        |
# MAGIC        v
# MAGIC  replay exactly as p11 / p16: tools as of the notice date, own project held out, cutoff benchmarks
# MAGIC  and cutoff model A  -->  writer (thinking on)  -->  validate_brief  -->  factcheck_brief
# MAGIC        |
# MAGIC        v
# MAGIC  p16's scoring: timeline range vs actual, relevance judge, groundedness judge, fact-check counts
# MAGIC ```
# MAGIC
# MAGIC Outputs: `data/human_review/review_briefs_holdout.csv` (the columns of `review_briefs.csv`, review ids h01-h10, owner label columns empty) and `review_briefs_holdout_full.csv` (the same, with each cited record's text starting with its facts line, for the labeller).

# COMMAND ----------

# MAGIC %md
# MAGIC ## How it was built and tested
# MAGIC
# MAGIC | Step | Question | What we found | Decision |
# MAGIC |---|---|---|---|
# MAGIC | What "fresh" means | Which packages could the phase-5 changes have been fitted to? | The 30 review packages, which are part of p11's 300-package sample; packages of the same projects share precedents and lessons with them | Exclude every contract, tender notice and project of the 300, not only the 30 |
# MAGIC | Usable description | Can every candidate be searched as a planner would? | Some notices have no description and fall back to the award-time contract description, which can name the winner | Only packages whose own notice text has at least 40 characters and four words |
# MAGIC | Spread over 10 packages | How to cover regions, categories and methods with only 10? | A plain stratified draw of 10 over 28 strata leaves categories or regions out by chance | `pick_holdout` (`proc_intel.holdout`, unit-tested): slots cycle the four categories, and within a category the first package in hash order from a new region, then a new region x category, then a new method |
# MAGIC | Same replay | Is the replay the one p16 scored? | The cohort, the 300-package sample, model A, the cutoff benchmarks, `as_of` and the judges are executed from p11's source at run time, and the groundedness rubric from p16's | No copy of the replay code here |

# COMMAND ----------

# MAGIC %md
# MAGIC ## Setup
# MAGIC
# MAGIC **What:** shared settings, the agent (`proc_rag_core`), and p11's replay code, executed from p11's own source cell by cell exactly as p16 does it (only the definitions needed here are taken from cells that also run evaluations). p16's own definitions (the groundedness rubric of the second round) are taken from p16's source the same way.
# MAGIC
# MAGIC **Why:** the holdout must be scored by the same code as the pack it is compared with; reading both notebooks at run time means a later change to either is picked up here.

# COMMAND ----------

# MAGIC %run ./proc_common

# COMMAND ----------

# MAGIC %run ./proc_rag_core

# COMMAND ----------

import ast
import base64
import pickle
import statistics

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.workspace import ExportFormat

from proc_intel.holdout import full_cited_text, pick_holdout, usable_description

dbutils.widgets.text("stage", "all")
STAGE = dbutils.widgets.get("stage")                          # "select" stops after the selection (a dry run)
N_HOLDOUT = 10
WRITER_THREADS = 3                                            # the cluster and endpoints are shared
_here = os.path.dirname(dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get())


def notebook_cells(name):
    """Code cells of a workspace notebook in this folder, from its source export (markdown lines dropped)."""
    src = base64.b64decode(WorkspaceClient().workspace.export(f"{_here}/{name}", format=ExportFormat.SOURCE).content).decode()
    return ["\n".join(line for line in c.split("\n") if not line.startswith("# MAGIC") and line != "# Databricks notebook source")
            for c in src.split("# COMMAND ----------")]


P11_CELLS, P16_CELLS = notebook_cells("p11_backtest"), notebook_cells("p16_brief_factcheck")


def _defined(node):
    if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
        return {node.name}
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        return {n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name)}
    if isinstance(node, (ast.Try, ast.With, ast.If)):
        inner = node.body + getattr(node, "orelse", []) + [n for h in getattr(node, "handlers", []) for n in h.body]
        return set().union(*(_defined(n) for n in inner))
    return set()


def run_cell(cells, marker, names=None, source="p11_backtest"):
    """Execute the cell of `cells` containing `marker` in this notebook's namespace (p16's run_p11, for any
    notebook); with `names`, only the top-level statements that define those names."""
    hits = [c for c in cells if marker in c]
    assert len(hits) == 1, f"{source} cell '{marker}': {len(hits)} matches"
    tree = ast.parse(hits[0])
    if names is not None:
        tree.body = [n for n in tree.body if _defined(n) & set(names)]
        missing = set(names) - set().union(*(_defined(n) for n in tree.body))
        assert not missing, f"{source} cell '{marker}' does not define {missing}"
    exec(compile(tree, f"{source}[{marker[:30]}]", "exec"), globals())


def run_p11(marker, names=None):
    run_cell(P11_CELLS, marker, names)


run_p11("_CORE_NAMES = ")                                     # p11 setup: imports, seed, dates, paths
run_p11('tl = spark.table(f"{GOLD}.tender_timelines")')       # 1a cohort features
run_p11("def slow_thresholds(")                               # 1b slow label and package texts
run_p11('test["stratum"] = ')                                 # 1c the 300-package sample
run_p11("GROUND_SCHEMA = ", ["order", "first", "review", "GROUND_SCHEMA", "GROUND_SYSTEM", "HAS_FORECAST_TOOL"])
print(f"writer reasoning effort: {WRITER_REASONING_EFFORT} | planner reasoning effort: {PLANNER_REASONING_EFFORT} | "
      f"writer threads {WRITER_THREADS} | per-call timeout {CALL_TIMEOUT_S} s, one retry")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Selecting the 10 holdout packages
# MAGIC
# MAGIC **What:** the candidates are p11's test contracts (notices from 2023-07-01, openly competed, with a measured notice-to-signing duration) that share no contract, tender notice or project with p11's 300-package sample, and whose own notice has a usable description. `pick_holdout` then fills 10 slots, cycling CW, GO, CS, NC, in the hash order `sha1("11|holdout|contract_id")` (p11's seed), preferring a new region, then a new region x category, then a new method.
# MAGIC
# MAGIC **Why:** the holdout must be disjoint from everything the phase-5 changes could have been fitted to, and still cover every category, most regions and several methods; a fixed hash order gives the same 10 on every run.

# COMMAND ----------

excluded = {"row_id": set(sample["row_id"]), "notice_id": set(sample["notice_id"]), "project_id": set(sample["project_id"])}
assert set(review["row_id"]) <= excluded["row_id"], "the 30 review packages must be inside p11's sample"
cand = test[~test["row_id"].isin(excluded["row_id"]) & ~test["notice_id"].isin(excluded["notice_id"])
            & ~test["project_id"].isin(excluded["project_id"]) & test["days_notice_to_signing"].notna()
            & (test["query_source"] == "notice") & test["query"].map(usable_description)].copy()
rows = cand.rename(columns={"procurement_category_code": "category", "procurement_method_name": "method"})[
    ["row_id", "notice_id", "project_id", "region", "category", "method"]].to_dict("records")
picked = pick_holdout(rows, N_HOLDOUT, seed=SEED)
holdout = cand.set_index("row_id").loc[[p["row_id"] for p in picked]].reset_index()
assert len(holdout) == N_HOLDOUT and holdout["project_id"].is_unique and holdout["notice_id"].is_unique
assert not set(holdout["row_id"]) & excluded["row_id"] and not set(holdout["project_id"]) & excluded["project_id"]
assert set(holdout["procurement_category_code"]) == {"CW", "GO", "CS", "NC"} and holdout["region"].nunique() >= 4
print(f"test contracts {len(test):,} | outside p11's sample (contract, notice and project) with a usable notice "
      f"description: {len(cand):,} from {cand['project_id'].nunique():,} projects | picked {len(holdout)}: "
      f"{holdout['region'].nunique()} regions, {holdout['procurement_method_name'].nunique()} methods, "
      f"{holdout['country_code'].nunique()} countries")
print(holdout[["row_id", "notice_id", "project_id", "country_code", "region", "procurement_category_code",
               "procurement_method_name", "notice_date", "days_notice_to_signing"]].astype(str).to_string(index=False))
if STAGE == "select":
    dbutils.notebook.exit("selection only")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. The replay, as p11 and p16 run it
# MAGIC
# MAGIC **What:** model A refitted at the cutoff (with p11's check that it reproduces p07's test metrics), the cutoff benchmark table, `as_of`, the judges and `short_text`, all from p11's source; then the groundedness rubric from p16's source when p16 defines its own.
# MAGIC
# MAGIC **Why:** the same replay and judges as the 30-package pack, so the two can be compared.

# COMMAND ----------

run_p11("model_a = fit_recipe(train, CAL_START)")             # model A at the cutoff (+ p07 reproduction check)
run_p11("def benchmark_table(", ["benchmark_table", "cutoff_bench"])
run_p11("def as_of(")                                         # hiding the future
run_p11("def judge_json(", ["_JUDGE_LOCK", "JCACHE", "save_judge_cache", "judge_json", "REL_SCHEMA", "REL_SYSTEM",
                            "judge_relevance"])
run_p11("def short_text(", ["short_text"])
run_cell(P16_CELLS, "GROUND_SYSTEM_V2 = ", ["GROUND_SYSTEM_V2"], source="p16_brief_factcheck")   # p16's round-2 rubric
assert GROUND_SYSTEM_V2 != GROUND_SYSTEM, "p16's round-2 rubric must extend p11's"
print(f"groundedness rubric: p16 round 2 ({len(GROUND_SYSTEM_V2)} chars; p11's {len(GROUND_SYSTEM)} chars, also run for comparison)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Generating the 10 briefs
# MAGIC
# MAGIC **What:** for each package, the tool half (`gather_evidence`) inside `as_of(notice date, project)` with the cutoff benchmark table and model A, one package at a time; then the writer half (`run_agent_on_evidence`: writer with thinking, citation validation, fact-check) three at a time, a failed writer retried alone after the pass. p11's leak check runs on every brief's cited precedents and lessons.
# MAGIC
# MAGIC **Why:** p16's two-half run, so the latencies are comparable; the tool half is saved to the volume so a writer failure does not repeat it.

# COMMAND ----------

STATES_FILE = f"{BT_ROOT}/p17_holdout_gathered.pkl"
ids = holdout["row_id"].astype(str).tolist()
t0 = time.time()
cached = None
if os.path.exists(STATES_FILE):
    with open(STATES_FILE, "rb") as fh:
        cached = pickle.load(fh)
if cached and cached["contract_ids"] == ids and cached["core"] == WRITER_SYSTEM:
    states, t_gather = cached["states"], cached["t_gather"]
    print(f"tool half loaded from {STATES_FILE} (gathered in {t_gather:.0f} s)")
else:
    states = []
    for pkg in holdout.itertuples():
        package = {"description": pkg.query, "country": pkg.country_code, "category": pkg.procurement_category_code,
                   "method": pkg.procurement_method_name, "_exclude_projects": [pkg.project_id]}
        if HAS_FORECAST_TOOL:
            package.update(project_id=pkg.project_id, planned_notice_date=str(pkg.notice_date.date()))
        with as_of(pkg.notice_date, pkg.project_id, bench=cutoff_bench,
                   forecast_model=CutoffModel() if HAS_FORECAST_TOOL else None):
            states.append(gather_evidence(package))
    t_gather = time.time() - t0
    with open(STATES_FILE, "wb") as fh:
        pickle.dump({"contract_ids": ids, "core": WRITER_SYSTEM, "states": states, "t_gather": t_gather}, fh)


def write_one(state):
    try:
        return run_agent_on_evidence(state)
    except RuntimeError as e:
        print(f"writer failed, retried later: {str(e)[:160]}")
        return None


t1 = time.time()
with ThreadPoolExecutor(max_workers=WRITER_THREADS) as pool:
    outs = list(pool.map(write_one, states))
retried = [i for i, o in enumerate(outs) if o is None]
for i in retried:
    time.sleep(30)
    outs[i] = run_agent_on_evidence(states[i])
t_write = time.time() - t1
briefs = []
for pkg, out in zip(holdout.itertuples(), outs, strict=True):
    recs_ = out.get("cited_records") or {}
    check_no_leak([r for r in recs_.values() if r["type"] != "contract" or r.get("close_precedent", True)],
                  pkg.notice_date, pkg.project_id)
    out["_kg_future"] = leak_violations([r for r in recs_.values() if r["type"] == "contract" and not r.get("close_precedent", True)],
                                        str(pkg.notice_date.date()), [])
    briefs.append((pkg, out))
print(f"{len(briefs)} briefs: tool half {t_gather:.0f} s (one at a time), writer half {t_write:.0f} s "
      f"({WRITER_THREADS} at a time), writer retries after the pass {len(retried)}; statuses "
      f"{pd.Series([o['status'] for o in outs]).value_counts().to_dict()}; writer reasoning effort "
      f"{sorted({str((o.get('writer') or {}).get('reasoning_effort')) for o in outs})}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. The holdout review files, scored as p16 scores its pack
# MAGIC
# MAGIC **What:** one row per brief with exactly the columns of `review_briefs.csv` (timeline range vs the actual duration, the relevance judge on the precedents, the groundedness judge on the whole brief; owner label columns empty), review ids h01-h10. The `_full` file is the same with each cited record's text starting with its facts line (project, country, region, method, year, firms in the award notice).
# MAGIC
# MAGIC **Why:** the same columns let p15's labelling and the scoring scripts run on the holdout unchanged; the facts line lets a labeller check a relation ("same project", "1 to 6 firms") without a query.

# COMMAND ----------

pred_a_of = dict(zip(test["row_id"], pred_a.to_dict("records")))
v1 = pd.read_csv(os.path.join(DATA_DIR, "human_review", "review_briefs.csv") if not os.path.exists(f"{REVIEW_DIR}/review_briefs.csv")
                 else f"{REVIEW_DIR}/review_briefs.csv", dtype={"contract_id": str}, nrows=1)
rows_out, full_cited, extra = [], [], []
for i, (pkg, out) in enumerate(briefs, 1):
    package = {"description": pkg.query, "country": pkg.country_code, "category": pkg.procurement_category_code,
               "method": pkg.procurement_method_name, "project_id": pkg.project_id,
               "planned_notice_date": str(pkg.notice_date.date())}
    brief, recs, cited = out.get("brief") or {}, out.get("cited_records") or {}, out.get("cited_ids") or []
    tl_out = out.get("timeline") or {}
    model_tl, peer_tl = tl_out.get("model") or {}, tl_out.get("peer_group") or {}
    range_rec = model_tl if model_tl.get("p10_days") is not None else (peer_tl or None)
    auto_tl = None if not range_rec else bool(range_rec["p10_days"] <= pkg.days_notice_to_signing <= range_rec["p90_days"])
    prec_recs = [recs.get(p["record_id"]) or {"label": p.get("label")} for p in out.get("precedents", [])]
    auto_prec = sum(bool(judge_relevance(pkg.query, pkg.procurement_category_code, r)[0]) for r in prec_recs[:5])
    ev = "\n\n".join(_evidence_block(r)[:1600] for r in recs.values())[:40000]
    facts = " | ".join(f"{k}: {v or 'not given'}" for k, v in package_facts(package).items())
    g, _ = judge_json(GROUND_SYSTEM_V2, f"PACKAGE:\n{package_text(package)}\nPACKAGE FACTS: {facts}\n\nRECORDS:\n{ev}\n\n"
                                        f"BRIEF:\n{out.get('text', '')}", GROUND_SCHEMA, max_tokens=1500) if brief else (None, False)
    g_old, _ = judge_json(GROUND_SYSTEM, f"PACKAGE:\n{package_text(package)}\n\nRECORDS:\n{ev}\n\nBRIEF:\n{out.get('text', '')}",
                          GROUND_SCHEMA, max_tokens=1500) if brief else (None, False)      # p11's rubric, for comparison
    pa = pred_a_of[pkg.row_id]
    actual = (f"signed {str(pkg.signing_date)[:10]}, {int(pkg.days_notice_to_signing)} days from notice to signing "
              f"(slow for its peer group: {'yes' if pkg.slow else 'no'}); model A range P10-P90 "
              f"{pa['p10']:.0f}-{pa['p90']:.0f} days, P50 {pa['p50']:.0f}")
    rid = f"h{i:02d}"
    rows_out.append({"review_id": rid, "contract_id": pkg.row_id, "notice_id": pkg.notice_id, "project_id": pkg.project_id,
                     "country": pkg.country_code, "region": pkg.region, "category": pkg.procurement_category_code,
                     "method": pkg.procurement_method_name, "notice_date": str(pkg.notice_date.date()), "description": pkg.query,
                     "status": out.get("status"), "brief_text": out.get("text", ""),
                     "cited_records": json.dumps([{"record_id": c, "text": short_text(recs[c])[:400]} for c in cited if c in recs]),
                     "actual_days": int(pkg.days_notice_to_signing), "actual_outcome": actual,
                     "model_p50_days": model_tl.get("p50_days"), "peer_p50_days": peer_tl.get("p50_days"),
                     "auto_timeline_ok": auto_tl, "auto_precedents_relevant": auto_prec,
                     "auto_unsupported_claim": None if g is None else bool(g["any_unsupported"]),
                     "auto_unsupported_examples": "" if g is None else "; ".join(g["unsupported_claims"])[:400],
                     "model_range_days": (f"{model_tl['p10_days']:.0f}-{model_tl['p90_days']:.0f}" if model_tl.get("p10_days") is not None else ""),
                     "peer_range_days": (f"{peer_tl['p10_days']:.0f}-{peer_tl['p90_days']:.0f}" if peer_tl else ""),
                     "n_precedents": out.get("n_precedents"), "kg_records_after_notice": len(out.get("_kg_future") or []),
                     "n_tool_calls": len(out.get("tool_calls") or []), "latency_s": out.get("latency_s"),
                     "timeline_ok": "", "precedents_relevant": "", "risks_relevant": "", "any_unsupported_claim": "", "notes": ""})
    full_cited.append(json.dumps([{"record_id": c, "text": full_cited_text(recs[c], short_text(recs[c])[:400])}
                                  for c in cited if c in recs]))           # as p16's review_briefs_v2_full
    fc, w = out.get("factcheck") or {}, out.get("writer") or {}
    extra.append({"review_id": rid, "factcheck_removed": int(fc.get("n_removed") or 0), "factcheck_fixed": int(fc.get("n_fixed") or 0),
                  "factcheck_claims_checked": int(fc.get("n_claims_checked") or 0),
                  "factcheck_events": json.dumps(fc.get("events") or []), "citation_validity": out.get("citation_validity"),
                  "auto_unsupported_p11_rubric": None if g_old is None else bool(g_old["any_unsupported"]),
                  "auto_unsupported_examples_p11_rubric": "" if g_old is None else "; ".join(g_old["unsupported_claims"])[:400],
                  "writer_latency_s": w.get("latency_s"), "writer_completion_tokens": w.get("completion_tokens"),
                  "flags": ", ".join(out.get("flags") or []), "dbu": out.get("dbu")})
save_judge_cache()
hold = pd.DataFrame(rows_out)
assert list(hold.columns) == list(v1.columns), "review_briefs_holdout must have the columns of review_briefs.csv"
hold.to_csv(f"{REVIEW_DIR}/review_briefs_holdout.csv", index=False)
hold.assign(cited_records=full_cited).to_csv(f"{REVIEW_DIR}/review_briefs_holdout_full.csv", index=False)
fc_df = pd.DataFrame(extra)
fc_df.to_csv(f"{REVIEW_DIR}/review_briefs_holdout_factcheck.csv", index=False)
print(f"written to {REVIEW_DIR}: review_briefs_holdout.csv, review_briefs_holdout_full.csv ({len(hold)} rows), "
      f"review_briefs_holdout_factcheck.csv")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Holdout vs the 30 tuned packages
# MAGIC
# MAGIC **What:** the automatic numbers of the holdout next to those of the 30-package pack written by the same agent (`review_briefs_v2.csv`, when it is on the volume): groundedness-judge flags, fact-check removals and corrections with every event, citation validity, the actual duration inside the cited range, precedents, statuses and latency.
# MAGIC
# MAGIC **Why:** if the changes only fitted the 30, the holdout would show more judge flags or fact-check corrections; the final word is the same labelling as the 30.

# COMMAND ----------

ev_rows = [{"review_id": r.review_id, **e} for r in fc_df.itertuples() for e in json.loads(r.factcheck_events)]
print(f"briefs changed by the fact-check: {int(((fc_df.factcheck_removed + fc_df.factcheck_fixed) > 0).sum())} of {len(fc_df)}; "
      f"sentences removed {int(fc_df.factcheck_removed.sum())}, counts corrected {int(fc_df.factcheck_fixed.sum())}; "
      f"checkable claims read {int(fc_df.factcheck_claims_checked.sum())}")
for e in ev_rows[:15]:
    print(f"- {e['review_id']} {e['field']} [{e['action']}] {e['before'][:220]!r}\n    -> {str(e['after'])[:220]!r}\n    because {e['reason'][:200]}")


def pack_stats(df, extra_df=None):
    lat = df["latency_s"].astype(float)
    s = {"briefs": len(df), "statuses": str(df["status"].value_counts().to_dict()),
         "groundedness judge: briefs with an unsupported claim": int(df["auto_unsupported_claim"].astype(str).eq("True").sum()),
         "actual duration inside the cited P10-P90": f"{int(df['auto_timeline_ok'].astype(str).eq('True').sum())} of "
                                                     f"{int(df['auto_timeline_ok'].notna().sum())}",
         "precedents per brief": round(float(df["n_precedents"].astype(float).mean()), 2),
         "relevant precedents per brief (judge)": round(float(df["auto_precedents_relevant"].astype(float).mean()), 2),
         "median latency, s": round(statistics.median(lat), 1)}
    if extra_df is not None:
        cv = extra_df["citation_validity"].dropna().astype(float)
        s.update({"groundedness judge, p11's rubric": int(extra_df["auto_unsupported_p11_rubric"].astype(str).eq("True").sum()),
                  "fact-check: briefs changed": int(((extra_df.factcheck_removed + extra_df.factcheck_fixed) > 0).sum()),
                  "fact-check: sentences removed / counts corrected": f"{int(extra_df.factcheck_removed.sum())} / {int(extra_df.factcheck_fixed.sum())}",
                  "fact-check: checkable claims read": int(extra_df.factcheck_claims_checked.sum()),
                  "citation validity (mean / min)": f"{cv.mean():.3f} / {cv.min():.3f}",
                  "median writer latency, s": round(statistics.median(extra_df["writer_latency_s"].astype(float)), 1)})
    return s


cols = {"holdout (10 fresh packages)": pack_stats(hold, fc_df)}
if spark.catalog.tableExists(f"{GOLD}.review_briefs_v2"):          # p16's pack: 30 rows, review and fact-check columns
    v2 = spark.table(f"{GOLD}.review_briefs_v2").toPandas()
    cols["the 30 tuned packages (p16, review_briefs_v2)"] = pack_stats(v2, v2 if "auto_unsupported_p11_rubric" in v2 else None)
print(pd.DataFrame(cols).astype(str).to_string())
print(hold[["review_id", "country", "region", "category", "method", "status", "actual_days", "model_range_days",
            "peer_range_days", "auto_timeline_ok", "n_precedents", "auto_precedents_relevant", "auto_unsupported_claim",
            "latency_s"]].astype(str).to_string(index=False))
for r in hold[hold["auto_unsupported_claim"].astype(str).eq("True")].itertuples():
    print(f"- {r.review_id} ({r.country} {r.category}): {r.auto_unsupported_examples[:400]}")
led = ledger_frame()
print(led.astype(str).to_string(index=False))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Results and limits
# MAGIC
# MAGIC | Measure | Holdout: 10 fresh packages (p17) | The 30 tuned packages, round 2 (p16) |
# MAGIC |---|---|---|
# MAGIC | Packages | 10, in 7 regions, 10 countries, all 4 categories, 4 methods; no contract, notice or project shared with p11's 300 | the 30 of p11's review pack |
# MAGIC | Status | 9 complete / 1 partial | 21 complete / 9 partial |
# MAGIC | Groundedness judge, round-2 rubric: briefs with an unsupported statement | 1 | 6 |
# MAGIC | Groundedness judge, p11's rubric | 2 | 8 |
# MAGIC | Code fact-check: briefs changed / sentences removed / counts corrected | 1 / 0 / 1, over 108 checkable claims | 4 / 3 / 1, over 211 |
# MAGIC | Citation validity (mean / min) | 1.000 / 1.000 | 0.994 / 0.900 |
# MAGIC | Actual duration inside the cited P10-P90 | 7 of 10 | 20 of 30 |
# MAGIC | Precedents per brief / judged relevant | 4.0 / 3.1 | 2.87 / 2.57 |
# MAGIC | Median latency (tool half + writer) / writer | 37.5 s / 18.6 s | 34.5 s / 18.1 s |
# MAGIC
# MAGIC - **No sign that the changes only fit the 30:** on packages nobody had read, the judge flags fewer briefs, every citation is valid and the fact-check had little to change. With 10 briefs the uncertainty is large (1 of 10 flagged is compatible with the 6 of 30 of the tuned pack); the labelling of the holdout is the real test.
# MAGIC - **The one flagged brief (h02) is half right.** The judge says contract 1705055 "used Request for Quotations": the brief says Request for Proposals, which is what the record says (a judge error). Its second quote is a real small overstatement: "contracts 1760388, 1747630 and 1641903 ... with 3 to 5 firms" when 1641903 has no award notice (counts 5, 3, not recorded; checked by SQL). The round-2 fact-check adds "(among the K with a recorded count)" to such ranges, but did not catch this sentence, where the range follows a list of contract ids.
# MAGIC - **The one fact-check correction (h06) was not needed:** "1 firm in award notice for 4 of 5 contracts (1 not recorded)" was already exact, and the inserted "(among the 4 with a recorded count)" only repeats it. The quantifier rule reads the range, not the writer's own qualification.
# MAGIC - **Timeline misses are tails:** h04 (Liberia) signed 1 day after its notice (in the data the tender notice is dated the day before signing, so the measured duration says little about the tender), h08 (Mozambique) took 477 days, h01 (Turkey) 54 days against a P10 of 76. h10 (Mauritania goods) found no close precedent and is the one partial brief.
# MAGIC - **h02's country is "99"**: the contract has no borrower country (multi-country notice), so country-level evidence is thin for it.
