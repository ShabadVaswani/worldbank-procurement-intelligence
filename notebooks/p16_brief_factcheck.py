# Databricks notebook source
# MAGIC %md
# MAGIC # p16_brief_factcheck — checking the brief's facts in code, and the 30 review briefs again
# MAGIC
# MAGIC The labelled review pack (p11 section 5, labels from p15 and the tier-3 adjudication) found an unsupported claim in **5 of 30** briefs. They were not invented records: every id was real and the citation check passed. They were small factual embellishments next to correct citations:
# MAGIC - r06: a precedent described as "under the same project ID" when its project (P146314) is not the package's (P160005);
# MAGIC - r10: "recent similar contracts in the same project attracted between 2 and 6 bidding firms" when the project's two cited contracts had 2 and 5 (the 6-firm contract is in another project);
# MAGIC - r26: "smaller similar furniture contracts in the region" for Kenyan, Malawian and West African contracts cited for a Guyana package.
# MAGIC
# MAGIC This notebook adds three changes to the agent and re-runs **the same 30 packages, replayed exactly as p11 does** (same notice texts, same "as of" date hiding, same held-out project, same cutoff benchmark table and cutoff forecast model):
# MAGIC
# MAGIC ```
# MAGIC  tools (as of the notice date)  -->  writer (Qwen 3.5, thinking on)  -->  validate_brief      -->  factcheck_brief       --> brief
# MAGIC  contract records now carry a       sees PACKAGE FACTS and each        (citations, timeline   (counts, ranges, days, %,
# MAGIC  "facts" line: project | country    contract's facts; rule 10: no      numbers, precedents)   project ids, methods,
# MAGIC  | method | year | firms in award   count, range or relation that is                          same project/country/region
# MAGIC  notice (or "not recorded")         not in a cited record's fields                            vs the cited records)
# MAGIC ```
# MAGIC
# MAGIC 1. **Records carry the facts explicitly** (`proc_rag_core`): each contract record has a `facts` line, and the number of firms is now counted exactly as the adjudication counted it (distinct firms in the award notices linked to the contract; "not recorded" when there is none).
# MAGIC 2. **Writer rule 10**: counts, ranges, methods and project / country / region relations only from a cited record's fields; "same project" only when the ids match.
# MAGIC 3. **A code fact-check** (`proc_intel.factcheck`, unit-tested on the adjudicated cases): a wrong count or range is replaced by the cited records' value (`factcheck_fixed`), any other unsupported statement is removed (`factcheck_removed`).
# MAGIC
# MAGIC The writer also runs with **Qwen 3.5 thinking on (`reasoning_effort="high"`)**, at the owner's request; the earlier pack was written with thinking off. The difference between the two packs is therefore the **combined effect** of the fact-check changes and thinking, not of either alone.
# MAGIC
# MAGIC Outputs: `proc_gold.review_briefs_v2` and `data/human_review/review_briefs_v2.csv` (the same columns as `review_briefs.csv`, owner label columns empty) for the same three-tier labelling.

# COMMAND ----------

# MAGIC %md
# MAGIC ## How it was built and tested
# MAGIC
# MAGIC | Step | Question | What we found | Decision |
# MAGIC |---|---|---|---|
# MAGIC | Reading the 5 unsupported briefs | What kind of error is it? | All five cite real records; the errors are a relation ("same project", "in the region") or a number (firm range) that the cited records contradict | Fix with explicit fields, a prompt rule and a check in code, not a new judge |
# MAGIC | Firm counts | Is the agent's firm count the one the adjudicator checked? | No: the agent read `tender_timelines.n_named_firms_in_award_notice`, which differs from "distinct firms in the award-linked notices" on 6,188 of the 189,126 contracts with an award notice | The contract tool counts firms the adjudicator's way; an award notice that names no firm counts as "not recorded" |
# MAGIC | Unit tests first | Does the check remove the real errors and keep the claims the adjudicator confirmed? | r06 removed, r10 fixed to "between 2 and 5", r26 removed; r05 "1 to 3 firms" (with two records lacking an award notice), r09 "up to 11", r18 "Request for Bids with 8 firms", r20 "1 to 8" kept; advice ("invite at least 5 firms") and "similar regional context" not checked | `tests/test_factcheck.py`, 22 tests |
# MAGIC | Thinking on | Does the endpoint accept `reasoning_effort="high"` with a JSON schema and with tools? | Yes: the reply carries a reasoning block and a text block (JSON) or tool calls | Named settings `WRITER_REASONING_EFFORT="high"`, `PLANNER_REASONING_EFFORT="none"`; completion budget raised by `THINKING_TOKENS` |
# MAGIC | Replay in parallel | p11's `as_of` swaps shared caches, so two replays cannot run at once | The tool half (guard, planner, tools) runs one package at a time inside `as_of`; the writer half runs 3 at a time | `gather_evidence` / `finish_brief` in `proc_rag_core` |
# MAGIC | Round 2: reading the judge's 7 flags on the first v2 pack | Real errors or judge errors? | One real overstatement (r30 "all five ... with 1 to 6 firms": one of the five has no award notice); "same region" unverifiable (region not in the facts line); evidence-gap lines and mitigations read as claims | Quantified claims must hold for every cited contract (else "among the 4 with a recorded count"); region in the facts line; `tool_log` records make absences citable; the judge rubric treats advice as advice and checks gaps against `tool_log` |
# MAGIC | First full run | Can four thinking writers run at once? | No: the workspace's output-tokens-per-minute limit on the Qwen endpoint (shared with other users) returned HTTP 429 until the client gave up | Three writers; throttled calls wait up to a minute between retries; a brief that still fails is retried alone after the parallel pass; the tool half is saved to the volume so a writer failure does not repeat it |
# MAGIC | Same 30 packages | Are these the p11 packages? | The 30 contract ids are checked against p11's review file, in order, before anything is written | Assertion in section 1 |

# COMMAND ----------

# MAGIC %md
# MAGIC ## Setup
# MAGIC
# MAGIC **What:** shared settings, the agent (`proc_rag_core`, now with the fact-check and the writer's thinking setting), and p11's replay code: the cohort features, the 300-package sample, the cutoff model A and benchmark table, `as_of`, the judges and the review selection, executed from p11's own source (read from the workspace) cell by cell. Only the definitions needed here are taken from the cells that also run evaluations (for example the judge functions, not p11's 2,400 relevance judgements).
# MAGIC
# MAGIC **Why:** the replay must be p11's, not a copy that could drift from it; reading the source at run time means a change to p11 is picked up here.

# COMMAND ----------

# MAGIC %run ./proc_common

# COMMAND ----------

dbutils.widgets.text("provider", "databricks")     # "openrouter": writer and judge through OpenRouter (evaluation only)
dbutils.widgets.text("suffix", "")                 # output suffix, e.g. "_or" for a parallel run
dbutils.widgets.text("writer_threads", "3")
LLM_PROVIDER = dbutils.widgets.get("provider")      # read by proc_rag_core

# COMMAND ----------

# MAGIC %run ./proc_rag_core

# COMMAND ----------

import ast
import base64
import statistics

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.workspace import ExportFormat

dbutils.widgets.text("limit", "30")
LIMIT = int(dbutils.widgets.get("limit"))                      # a smaller number for a smoke run
WRITER_THREADS = int(dbutils.widgets.get("writer_threads"))    # 3 on the shared Databricks endpoints
SUFFIX = dbutils.widgets.get("suffix")
_here = os.path.dirname(dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get())
_p11 = base64.b64decode(WorkspaceClient().workspace.export(f"{_here}/p11_backtest", format=ExportFormat.SOURCE).content).decode()
P11_CELLS = ["\n".join(line for line in c.split("\n") if not line.startswith("# MAGIC") and line != "# Databricks notebook source")
             for c in _p11.split("# COMMAND ----------")]


def _defined(node):
    if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
        return {node.name}
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        return {n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name)}
    if isinstance(node, (ast.Try, ast.With, ast.If)):            # e.g. try: with open(...): JCACHE = json.load(fh)
        inner = node.body + getattr(node, "orelse", []) + [n for h in getattr(node, "handlers", []) for n in h.body]
        return set().union(*(_defined(n) for n in inner))
    return set()


def run_p11(marker, names=None):
    """Execute the p11 cell containing `marker` in this notebook's namespace; with `names`, only the top-level
    statements that define those names."""
    cells = [c for c in P11_CELLS if marker in c]
    assert len(cells) == 1, f"p11 cell '{marker}': {len(cells)} matches"
    tree = ast.parse(cells[0])
    if names is not None:
        tree.body = [n for n in tree.body if _defined(n) & set(names)]
        missing = set(names) - set().union(*(_defined(n) for n in tree.body))
        assert not missing, f"p11 cell '{marker}' does not define {missing}"
    exec(compile(tree, f"p11_backtest[{marker[:30]}]", "exec"), globals())


run_p11("_CORE_NAMES = ")                                     # p11 setup: imports, seed, dates, paths
print(f"LLM provider for writer and judge: {LLM_PROVIDER} | output suffix '{SUFFIX}' | "
      f"writer reasoning effort: {WRITER_REASONING_EFFORT} | planner reasoning effort: {PLANNER_REASONING_EFFORT} | "
      f"writer threads {WRITER_THREADS} | per-call timeout {CALL_TIMEOUT_S} s, one retry")

# COMMAND ----------

run_p11('tl = spark.table(f"{GOLD}.tender_timelines")')       # 1a cohort features
run_p11("def slow_thresholds(")                               # 1b slow label and package texts
run_p11('test["stratum"] = ')                                 # 1c the 300-package sample
run_p11("model_a = fit_recipe(train, CAL_START)")             # 2a model A at the cutoff (+ p07 reproduction check)
run_p11("def benchmark_table(", ["benchmark_table", "cutoff_bench"])
run_p11("def as_of(")                                         # 3a hiding the future
run_p11("def judge_json(", ["_JUDGE_LOCK", "JCACHE", "save_judge_cache", "judge_json", "REL_SCHEMA", "REL_SYSTEM",
                            "judge_relevance"])
run_p11("GROUND_SCHEMA = ", ["order", "first", "review", "GROUND_SCHEMA", "GROUND_SYSTEM", "HAS_FORECAST_TOOL"])
run_p11("def short_text(", ["short_text"])

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. The same 30 packages
# MAGIC
# MAGIC **What:** p11's review selection (first package per region x category stratum in hash order, then one more per region), checked against the contract ids of p11's review file in the same order.
# MAGIC
# MAGIC **Why:** a before/after comparison is only fair on the same packages; the check makes a silent change of the sample impossible.

# COMMAND ----------

v1_path = f"{REVIEW_DIR}/review_briefs.csv"
v1 = pd.read_csv(v1_path if os.path.exists(v1_path) else os.path.join(DATA_DIR, "human_review", "review_briefs.csv"),
                 dtype={"contract_id": str})
assert review["row_id"].astype(str).tolist() == v1["contract_id"].tolist(), "p11's review selection changed"
review = review.head(LIMIT)
print(f"{len(review)} packages, identical to p11's review pack (first: {review['row_id'].iloc[0]}, "
      f"last: {review['row_id'].iloc[-1]}); held-out projects {review['project_id'].nunique()}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Re-generating the briefs
# MAGIC
# MAGIC **What:** for each package, the tool half of the agent (`gather_evidence`: guard, planner, tools) inside `as_of(notice date, project)` with the cutoff benchmark table and model A, exactly as p11 calls the agent; then the writer half (`run_agent_on_evidence`: writer with thinking, citation validation, fact-check) for all packages, three at a time. The leak check is p11's (`check_no_leak` on the cited precedents and lessons). A brief's latency is the sum of its two halves, i.e. what one sequential run would take.
# MAGIC
# MAGIC **Why:** the writer needs no tool, so it can run outside `as_of`, in parallel; the tool half cannot, because `as_of` swaps caches every tool shares.

# COMMAND ----------

import pickle

STATES_FILE = f"{BT_ROOT}/p16_gathered_{LIMIT}.pkl"      # the tool half, kept so a writer failure does not redo it
t0 = time.time()
cached = None
if os.path.exists(STATES_FILE):
    with open(STATES_FILE, "rb") as fh:
        cached = pickle.load(fh)
if cached and cached["contract_ids"] == review["row_id"].astype(str).tolist() and cached["core"] == WRITER_SYSTEM:
    states, t_gather = cached["states"], cached["t_gather"]
    print(f"tool half loaded from {STATES_FILE} (gathered in {t_gather:.0f} s)")
else:
    states = []
    for pkg in review.itertuples():
        package = {"description": pkg.query, "country": pkg.country_code, "category": pkg.procurement_category_code,
                   "method": pkg.procurement_method_name, "_exclude_projects": [pkg.project_id]}
        if HAS_FORECAST_TOOL:
            package.update(project_id=pkg.project_id, planned_notice_date=str(pkg.notice_date.date()))
        with as_of(pkg.notice_date, pkg.project_id, bench=cutoff_bench,
                   forecast_model=CutoffModel() if HAS_FORECAST_TOOL else None):
            states.append(gather_evidence(package))
    t_gather = time.time() - t0
    with open(STATES_FILE.replace(".pkl", f"{SUFFIX}.pkl"), "wb") as fh:      # a parallel run writes its own file
        pickle.dump({"contract_ids": review["row_id"].astype(str).tolist(), "core": WRITER_SYSTEM, "states": states,
                     "t_gather": t_gather}, fh)


def write_one(state):
    """The writer half; a brief that still fails after the client's retries (the endpoint's output-token limit
    per minute is shared with other users) is retried once more after the parallel pass, on its own."""
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
print(f"writer retries after the parallel pass: {len(retried)}")
briefs = []
for pkg, out in zip(review.itertuples(), outs, strict=True):
    recs_ = out.get("cited_records") or {}
    retrieved = [r for r in recs_.values() if r["type"] != "contract" or r.get("close_precedent", True)]
    check_no_leak(retrieved, pkg.notice_date, pkg.project_id)
    out["_kg_future"] = leak_violations([r for r in recs_.values() if r["type"] == "contract" and not r.get("close_precedent", True)],
                                        str(pkg.notice_date.date()), [])
    briefs.append((pkg, out))
print(f"{len(briefs)} briefs: tool half {t_gather:.0f} s (one at a time), writer half {t_write:.0f} s "
      f"({WRITER_THREADS} at a time); statuses {pd.Series([o['status'] for o in outs]).value_counts().to_dict()}; "
      f"writer reasoning effort {sorted({str((o.get('writer') or {}).get('reasoning_effort')) for o in outs})}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. The review file, scored as p11 scores it
# MAGIC
# MAGIC **What:** one row per brief with exactly the columns of `review_briefs.csv` (the same automatic scores: timeline range vs the actual duration, the relevance judge on the precedents, the groundedness judge on the whole brief; owner label columns empty), written to the volume and published as `proc_gold.review_briefs_v2` with the fact-check columns added.
# MAGIC
# MAGIC **Why:** the same columns let p15's three-tier labelling and the scoring scripts run on the new pack unchanged.

# COMMAND ----------

# Round 2 rubric: p11's rubric, plus the three things its judge got wrong on the first v2 pack (it called
# mitigations and evidence gaps "unsupported claims" and could not see the package's own region).
GROUND_SYSTEM_V2 = GROUND_SYSTEM.replace("Return JSON", """Also NOT claims, never unsupported: mitigations and
recommendations (advice on what to do). Evidence-gap statements ARE checked, but against the TOOL_LOG records (what a
search did not find, which peer groups were skipped and why) and the PACKAGE FACTS line, not against contract records.
"Same project / same country / in the region" is supported when a cited record's project, country or region equals
the PACKAGE FACTS. "All" / "each" / "all five" claim a fact for every cited contract.
Return JSON""")
assert GROUND_SYSTEM_V2 != GROUND_SYSTEM, "p11's rubric text changed: update the round-2 additions"
pred_a_of = dict(zip(test["row_id"], pred_a.to_dict("records")))


def judge_json_role(system, user, schema, max_tokens=900):
    """p11's cached judge_json, with the call marked as a judge call (so the provider switch can route it)."""
    key = hashlib.sha1(json.dumps([JUDGE_MODEL, system, user]).encode()).hexdigest()
    with _JUDGE_LOCK:
        if key in JCACHE:
            return JCACHE[key], True
    v = None
    for _ in (1, 2):
        try:
            r = chat([{"role": "system", "content": system}, {"role": "user", "content": user}], JUDGE_MODEL,
                     max_tokens=max_tokens, response_format=schema, role="judge")
            v = json.loads(r["text"])
            break
        except Exception:
            v = None
    if v is not None:
        with _JUDGE_LOCK:
            JCACHE[key] = v
    return v, False


def judge_messages(pkg, out):
    """The groundedness judge's two messages for one brief: round-2 rubric input (with PACKAGE FACTS) and p11's."""
    package = {"description": pkg.query, "country": pkg.country_code, "category": pkg.procurement_category_code,
               "method": pkg.procurement_method_name, "project_id": pkg.project_id,
               "planned_notice_date": str(pkg.notice_date.date())}
    ev = "\n\n".join(_evidence_block(r)[:1600] for r in (out.get("cited_records") or {}).values())[:40000]
    facts = " | ".join(f"{k}: {v or 'not given'}" for k, v in package_facts(package).items())
    return (f"PACKAGE:\n{package_text(package)}\nPACKAGE FACTS: {facts}\n\nRECORDS:\n{ev}\n\nBRIEF:\n{out.get('text', '')}",
            f"PACKAGE:\n{package_text(package)}\n\nRECORDS:\n{ev}\n\nBRIEF:\n{out.get('text', '')}")


t2 = time.time()
jobs = [(system, msgs[k]) for pkg, out in briefs if out.get("brief")
        for msgs in [judge_messages(pkg, out)] for k, system in ((0, GROUND_SYSTEM_V2), (1, GROUND_SYSTEM))]
with ThreadPoolExecutor(max_workers=max(3, WRITER_THREADS)) as pool:          # fills the judge cache in parallel
    list(pool.map(lambda a: judge_json_role(a[0], a[1], GROUND_SCHEMA, max_tokens=1500), jobs))
print(f"{len(jobs)} groundedness judgements in {time.time() - t2:.0f} s")
rows_out, extra, full_cited = [], [], []
for i, (pkg, out) in enumerate(briefs, 1):
    package = {"description": pkg.query, "country": pkg.country_code, "category": pkg.procurement_category_code,
               "method": pkg.procurement_method_name, "project_id": pkg.project_id,
               "planned_notice_date": str(pkg.notice_date.date())}
    brief, recs, cited = out.get("brief") or {}, out.get("cited_records") or {}, out.get("cited_ids") or []
    u_new, u_old = judge_messages(pkg, out)
    tl_out = out.get("timeline") or {}
    model_tl, peer_tl = tl_out.get("model") or {}, tl_out.get("peer_group") or {}
    range_rec = model_tl if model_tl.get("p10_days") is not None else (peer_tl or None)
    auto_tl = None if not range_rec else bool(range_rec["p10_days"] <= pkg.days_notice_to_signing <= range_rec["p90_days"])
    prec_recs = [recs.get(p["record_id"]) or {"label": p.get("label")} for p in out.get("precedents", [])]
    auto_prec = sum(bool(judge_relevance(pkg.query, pkg.procurement_category_code, r)[0]) for r in prec_recs[:5])
    g, _ = judge_json_role(GROUND_SYSTEM_V2, u_new, GROUND_SCHEMA, max_tokens=1500) if brief else (None, False)
    g_old, _ = judge_json_role(GROUND_SYSTEM, u_old, GROUND_SCHEMA, max_tokens=1500) if brief else (None, False)  # p11's rubric
    full_cited.append(json.dumps([{"record_id": c, "text": (f"{recs[c]['facts']} | " if recs[c].get("facts") else "")
                                   + short_text(recs[c])[:400]} for c in cited if c in recs]))
    pa = pred_a_of[pkg.row_id]
    actual = (f"signed {str(pkg.signing_date)[:10]}, {int(pkg.days_notice_to_signing)} days from notice to signing "
              f"(slow for its peer group: {'yes' if pkg.slow else 'no'}); model A range P10-P90 "
              f"{pa['p10']:.0f}-{pa['p90']:.0f} days, P50 {pa['p50']:.0f}")
    rid = f"r{i:02d}"
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
    fc = out.get("factcheck") or {}
    w = out.get("writer") or {}
    extra.append({"review_id": rid, "factcheck_removed": int(fc.get("n_removed") or 0), "factcheck_fixed": int(fc.get("n_fixed") or 0),
                  "factcheck_claims_checked": int(fc.get("n_claims_checked") or 0),
                  "factcheck_events": json.dumps(fc.get("events") or []), "citation_validity": out.get("citation_validity"),
                  "writer_reasoning_effort": w.get("reasoning_effort"), "writer_latency_s": w.get("latency_s"),
                  "writer_provider": w.get("provider"),
                  "writer_completion_tokens": w.get("completion_tokens"), "flags": ", ".join(out.get("flags") or []),
                  "auto_unsupported_p11_rubric": None if g_old is None else bool(g_old["any_unsupported"]),
                  "n_tool_log_cited": sum(c.startswith("tool_log:") for c in cited),
                  "dbu": out.get("dbu")})
save_judge_cache()
review_v2 = pd.DataFrame(rows_out)
assert list(review_v2.columns) == list(v1.columns), "review_briefs_v2 must have the columns of review_briefs.csv"
review_v2.to_csv(f"{REVIEW_DIR}/review_briefs_v2{SUFFIX}.csv", index=False)
review_v2.assign(cited_records=full_cited).to_csv(f"{REVIEW_DIR}/review_briefs_v2{SUFFIX}_full.csv", index=False)  # facts shown
fc_df = pd.DataFrame(extra)
table_df = review_v2.drop(columns=["timeline_ok", "precedents_relevant", "risks_relevant", "any_unsupported_claim", "notes"]).merge(fc_df, on="review_id")
for c in ("model_p50_days", "peer_p50_days", "citation_validity", "latency_s", "writer_latency_s", "dbu", "n_precedents",
          "writer_completion_tokens"):
    table_df[c] = table_df[c].astype(float)
COLS = {
    "review_id": "PK. r01..r30, the same packages and numbering as review_briefs (p11)", "contract_id": "The replayed contract; FK proc_silver.contracts",
    "notice_id": "Its tender notice", "project_id": "Its project (held out from retrieval)", "country": "Borrower country (ISO2)",
    "region": "Project region", "category": "Procurement category", "method": "Procurement method", "notice_date": "Replay date",
    "description": "Package text from the tender notice", "status": "Brief status", "brief_text": "The rendered brief",
    "cited_records": "JSON list of the cited records (id and short text)", "actual_days": "Actual notice-to-signing days",
    "actual_outcome": "Actual outcome and model A range, for the labeller", "model_p50_days": "Model forecast median in the brief",
    "peer_p50_days": "Peer-group median in the brief", "auto_timeline_ok": "Actual duration inside the cited P10-P90",
    "auto_precedents_relevant": "Precedents the relevance judge calls relevant (0-5)",
    "auto_unsupported_claim": "Groundedness judge finds an unsupported statement", "auto_unsupported_examples": "Its quotes",
    "model_range_days": "Model P10-P90 in the brief", "peer_range_days": "Peer P10-P90 in the brief", "n_precedents": "Precedents listed",
    "kg_records_after_notice": "Supplier-profile contracts signed after the notice (graph is not as-of)",
    "n_tool_calls": "Tool calls", "latency_s": "Agent latency (tool half + writer half), seconds",
    "factcheck_removed": "Sentences the code fact-check removed", "factcheck_fixed": "Sentences whose counts it corrected",
    "factcheck_claims_checked": "Checkable claims it read", "factcheck_events": "JSON: field, before, after, reason per event",
    "citation_validity": "Share of cited ids that a tool returned", "writer_reasoning_effort": "Qwen 3.5 thinking effort of the writer",
    "writer_latency_s": "Writer latency, seconds", "writer_completion_tokens": "Writer completion tokens incl. reasoning",
    "flags": "Validation and fact-check flags", "dbu": "Model-serving DBU of the brief",
    "auto_unsupported_p11_rubric": "Groundedness judge with p11's rubric (for comparison with the first pack)",
    "writer_provider": "Where the writer ran: databricks or openrouter/<serving provider>",
    "n_tool_log_cited": "tool_log records cited (evidence gaps grounded in what a tool did not find)"}
if LIMIT == len(v1):
    n_rows = publish_table(spark.createDataFrame(table_df), f"{GOLD}.review_briefs_v2{SUFFIX}",
                           "The 30 review packages of p11 re-generated with the fact-checked agent and writer thinking on (p16)",
                           COLS, primary_key=["review_id"])
    print(f"proc_gold.review_briefs_v2: {n_rows} rows; review_briefs_v2.csv and review_briefs_v2_full.csv written to {REVIEW_DIR}")
else:
    print(f"smoke run ({LIMIT} packages): nothing published")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. What the fact-check did, and before vs after
# MAGIC
# MAGIC **What:** how many briefs the fact-check changed and how (removed sentences, corrected counts), every event with its before and after text, citation validity, the latency of the two packs, the automatic groundedness verdict on both packs, and the five briefs labelled unsupported in the first pack.
# MAGIC
# MAGIC **Why:** these are the automatic numbers; whether the new briefs are actually free of unsupported claims is decided by the same three-tier labelling as the first pack.

# COMMAND ----------

ev_rows = [{"review_id": r.review_id, **e} for r in fc_df.itertuples() for e in json.loads(r.factcheck_events)]
print(f"briefs changed by the fact-check: {int(((fc_df.factcheck_removed + fc_df.factcheck_fixed) > 0).sum())} of {len(fc_df)} "
      f"(sentences removed in {int((fc_df.factcheck_removed > 0).sum())}, counts corrected in {int((fc_df.factcheck_fixed > 0).sum())}); "
      f"sentences removed {int(fc_df.factcheck_removed.sum())}, corrected {int(fc_df.factcheck_fixed.sum())}; "
      f"checkable claims read {int(fc_df.factcheck_claims_checked.sum())}")
for e in ev_rows[:15]:
    print(f"- {e['review_id']} {e['field']} [{e['action']}] {e['before'][:220]!r}\n    -> {str(e['after'])[:220]!r}\n    because {e['reason'][:200]}")
cv = fc_df["citation_validity"].dropna()
lat1, lat2 = v1["latency_s"].astype(float).head(len(review_v2)), review_v2["latency_s"].astype(float)
compare = pd.DataFrame([
    {"measure": "median latency, s", "v1 (thinking off, no fact-check)": statistics.median(lat1), "v2": statistics.median(lat2)},
    {"measure": "median writer latency, s", "v1 (thinking off, no fact-check)": None, "v2": statistics.median(fc_df["writer_latency_s"].astype(float))},
    {"measure": "citation validity (mean / min)", "v1 (thinking off, no fact-check)": None, "v2": f"{cv.mean():.3f} / {cv.min():.3f}"},
    {"measure": "groundedness judge, p11 rubric: briefs with an unsupported claim",
     "v1 (thinking off, no fact-check)": int(v1["auto_unsupported_claim"].head(len(review_v2)).astype(str).eq("True").sum()),
     "v2": int(fc_df["auto_unsupported_p11_rubric"].astype(str).eq("True").sum())},
    {"measure": "groundedness judge, round-2 rubric (advice not a claim, gaps vs tool_log, package facts)",
     "v1 (thinking off, no fact-check)": None, "v2": int(review_v2["auto_unsupported_claim"].astype(str).eq("True").sum())},
    {"measure": "briefs citing a tool_log record in an evidence gap", "v1 (thinking off, no fact-check)": None,
     "v2": int((fc_df["n_tool_log_cited"] > 0).sum())},
    {"measure": "statuses", "v1 (thinking off, no fact-check)": str(v1["status"].head(len(review_v2)).value_counts().to_dict()),
     "v2": str(review_v2["status"].value_counts().to_dict())},
    {"measure": "precedents per brief", "v1 (thinking off, no fact-check)": v1["n_precedents"].head(len(review_v2)).mean(), "v2": review_v2["n_precedents"].mean()}])
print(compare.astype(str).to_string(index=False))
watch = review_v2[review_v2["review_id"].isin(["r06", "r10", "r17", "r26", "r30"])]
for r in review_v2[review_v2["auto_unsupported_claim"].astype(str).eq("True")].itertuples():
    print(f"judge (round-2 rubric) on {r.review_id}: {r.auto_unsupported_examples[:300]}")
for r in watch.itertuples():
    t = r.brief_text
    print(f"===== {r.review_id} ({r.country}, project {r.project_id}) judge unsupported: {r.auto_unsupported_claim}")
    print(t[t.find("Market approach"):t.find("Risks and mitigations")].strip()[:600])
    print(t[t.find("Similar precedents"):t.find("Evidence gaps") if "Evidence gaps" in t else None].strip()[:700])
print(ledger_frame().to_string(index=False))
if PROVIDER_LOG:
    print(pd.DataFrame(PROVIDER_LOG).groupby(["role", "model", "provider"]).agg(calls=("latency_s", "size"), 
          median_latency_s=("latency_s", "median")).reset_index().to_string(index=False))
    print(f"OpenRouter spend this run: US${_OR['usd']:.3f}; switch disabled: {_OR['disabled']}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Results and limits
# MAGIC
# MAGIC | Measure | First pack (p11: thinking off, no fact-check) | v2 round 1 (facts line, rule 10, thinking, fact-check) | v2 round 2 (+ quantifiers, region, tool_log gaps) |
# MAGIC |---|---|---|---|
# MAGIC | Packages | 30 | the same 30, same replay | the same 30, same replay |
# MAGIC | Briefs changed by the code fact-check | (not run) | 0 (218 claims read) | 4: 3 sentences removed, 1 qualified (211 claims read) |
# MAGIC | Groundedness judge, p11 rubric | 9 | 7 | 8 |
# MAGIC | Groundedness judge, round-2 rubric (advice is not a claim, gaps checked against `tool_log`, package facts given) | | | 6 |
# MAGIC | Briefs whose evidence gaps cite a `tool_log` record | | | 21 |
# MAGIC | Citation validity (mean / min) | | 1.000 / 1.000 | 0.994 / 0.900 |
# MAGIC | Status | 22 complete / 8 partial | 22 / 8 | 21 / 9 |
# MAGIC | Median latency per brief (tool half + writer) | 28.6 s | 38.6 s | 34.5 s (writer 18.1 s) |
# MAGIC
# MAGIC - **What the round-2 fact-check did:** r29 lost "Request for Bids is the standard for this category in the region" (the cited Jamaican contract is not in the package's East Asia and Pacific region); r06 lost "4 of 5 close precedents in the same country and region ... 3 to 6 firms" (only one precedent is in Sri Lanka, and it has no award notice); r13's "1 firm" got "(among the 4 with a recorded count)".
# MAGIC - **Two mistakes of the round-2 check, found by reading its events, fixed in `factcheck.py` afterwards (4 new tests) but not re-run on this pack:** r17's correct market-approach sentence was removed, because "across all precedents" at its end was read as quantifying the methods named before it; and r13's "all 5 close precedents employed this method" (one of the five was Direct Selection) passed, because "this method" was not resolved. A quantifier now applies only to the methods after it, "this method" means the last method named, a sentence that already says "4 of 5" gets no second qualifier, and "among the N with recorded counts" is checked.
# MAGIC - **The packs differ in several things at once** (record fields, prompt rules, thinking, fact-check, judge rubric), so the comparison shows their combined effect, not the effect of any one of them.
# MAGIC - **Not checked by the code:** interpretive phrases ("similar scope"), amounts, and mitigations (advice). The judge's remaining flags are for the three-tier labelling to settle.
# MAGIC - **Thinking runs into the endpoint's per-minute output-token limit** (shared with other users): throttled writer calls succeeded when retried alone. Evaluation re-runs can send the writer and the judge to the same open-weight models through OpenRouter (`LLM_PROVIDER = "openrouter"`) for throughput; the official round-2 pack was written on the Databricks endpoints, which production uses.
