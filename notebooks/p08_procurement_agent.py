# Databricks notebook source
# MAGIC %md
# MAGIC # p08_procurement_agent — contextual retrieval for a new procurement package
# MAGIC
# MAGIC When a task team starts a new procurement package, this agent gathers the evidence a procurement specialist would look for and writes a short, cited planning brief:
# MAGIC
# MAGIC - **similar past contracts** (operational precedents and similar specifications) from the 282,890 contracts of the awards feed, only those close enough to count (0 to 5),
# MAGIC - a **realistic timeline**: the risk component's duration model scored for this package (P10 / P50 / P90 and the chance of a slow tender, with its assumptions) next to the measured tender-to-signing durations of the package's peer group,
# MAGIC - **risks and lessons learned** from appraisal documents (risks expected at design) and completion reports (what happened),
# MAGIC - **supplier context** from the knowledge graph when the same firms keep winning.
# MAGIC
# MAGIC Every statement in the brief cites the ids of the records a tool returned, and the code checks those ids.

# COMMAND ----------

# MAGIC %md-sandbox
# MAGIC <pre class="mermaid">
# MAGIC ---
# MAGIC config:
# MAGIC   layout: elk
# MAGIC ---
# MAGIC flowchart TD
# MAGIC     pkg["new package<br/>{country, category, method, description}"]
# MAGIC     guard["input guard<br/>(Llama 3.3)"]
# MAGIC     planner["planner LLM<br/>(Qwen 3.5)"]
# MAGIC     subgraph tools["tools (at most 6 calls)"]
# MAGIC         t1["similar_past_contracts<br/>TF-IDF + GTE, 282,890 contracts,<br/>only re-rank cosine at or above threshold"]
# MAGIC         t2["tender_benchmark<br/>proc_gold.tender_benchmarks"]
# MAGIC         t3["forecast_timeline<br/>ml.proc_tender_duration@champion"]
# MAGIC         t4["lessons_learned<br/>appraisal + completion passages"]
# MAGIC         t5["supplier_profile<br/>proc_gold.kg_nodes / kg_edges"]
# MAGIC     end
# MAGIC     writer["writer LLM<br/>(JSON brief)"]
# MAGIC     validate["validation in code: unknown ids dropped,<br/>uncited risks removed, timeline numbers equal to<br/>the cited forecast and benchmark, precedents only close ones"]
# MAGIC     brief["cited brief"]
# MAGIC     pkg --> guard --> planner
# MAGIC     planner -->|"tool calls (max 6)"| tools
# MAGIC     tools -->|"records with ids"| writer
# MAGIC     planner --> writer
# MAGIC     writer --> validate --> brief
# MAGIC </pre>
# MAGIC <script type="module">
# MAGIC   import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11.6.0/dist/mermaid.esm.min.mjs";
# MAGIC   import elkLayouts from "https://cdn.jsdelivr.net/npm/@mermaid-js/layout-elk@0.1.7/dist/mermaid-layout-elk.esm.min.mjs";
# MAGIC   mermaid.registerLayoutLoaders(elkLayouts);
# MAGIC   mermaid.initialize({ startOnLoad: true });
# MAGIC </script>

# COMMAND ----------

# MAGIC %md
# MAGIC | Output | Grain | Key |
# MAGIC |---|---|---|
# MAGIC | `proc_silver.lesson_documents` | one completion report (ICR) selected for the lessons corpus | `doc_id` |
# MAGIC | `proc_silver.lesson_chunks` | one procurement-relevant passage of a completion report, with its GTE embedding | `chunk_id` |
# MAGIC | `proc_gold.agent_eval_results` | one evaluation package, with the agent's output and its scores | `eval_id` |
# MAGIC | MLflow experiment `wb-procurement/proc_agent_experiment` | one trace per agent run (guard, planner rounds, each tool, writer) | trace id |
# MAGIC
# MAGIC The tools, guardrails and the loop are defined in `proc_rag_core`; this notebook builds the completion-report corpus, demonstrates the agent and evaluates it.
# MAGIC
# MAGIC **Interface for other components: `run_agent(package) -> dict`** (defined in `proc_rag_core`, available after `%run ./proc_common` and `%run ./proc_rag_core`).
# MAGIC
# MAGIC | Input key | Meaning |
# MAGIC |---|---|
# MAGIC | `description` | what is to be procured (required; any language) |
# MAGIC | `country`, `category`, `method` | borrower country (name or ISO2), CW / GO / CS / NC, procurement method (name or code) |
# MAGIC | `project_id`, `planned_notice_date`, `advertising_days`, `notice_type`, `notice_language` | optional; replace the forecast's planning-time defaults |
# MAGIC | `_exclude_projects` | optional list of project ids held out from contract search (evaluation only) |
# MAGIC
# MAGIC | Output key | Meaning |
# MAGIC |---|---|
# MAGIC | `status` | `complete`, `partial`, `insufficient_evidence`, `refused` (guard) or `fallback` (no valid brief) |
# MAGIC | `brief`, `text` | the validated JSON brief and its plain-text rendering |
# MAGIC | `timeline` | `model`: {record_id, scored, p10_days, p50_days, p90_days, slow_probability, assumptions}; `peer_group`: {record_id, level, n_contracts, p10_days, p50_days, p90_days} |
# MAGIC | `precedents`, `n_precedents` | 0 to 5 cited close precedents: {record_id, contract_id, label, rerank_cosine, why_relevant} |
# MAGIC | `cited_ids`, `cited_records`, `citation_validity` | every id the brief cites, the cited records, share of the writer's citations that were real |
# MAGIC | `flags`, `guard` | validation flags (e.g. `no_close_precedent`, `forecast_unavailable`, `timeline_corrected`) and the guard's verdict |
# MAGIC | `tool_calls`, `latency_s`, `tokens`, `dbu` | [{tool, args, n_records, forced}], wall time, tokens per endpoint, DBU of the run |

# COMMAND ----------

# MAGIC %md
# MAGIC ## Key design decisions
# MAGIC
# MAGIC | Decision | Rationale | Evidence |
# MAGIC |---|---|---|
# MAGIC | Hashed TF-IDF over all 282,890 contracts, then GTE re-ranking of only the best 30 per query | Embedding every description is too slow under the shared rate limit; a stored vocabulary inflated driver memory | Embedding all would take about five hours (about 15 texts per second); TF-IDF builds in about a minute; a stored unigram + bigram vocabulary inflated the driver process on a shared 16 GB driver; hashing keeps the index at about 70 MB; precision@5 about 0.6 with TF-IDF alone vs about 0.75 re-ranked on the 20 evaluation packages (section 5b) |
# MAGIC | Passage rules: numbered digit headings must be capitalised and comma-free (all-capitals Roman or letter headings may contain commas); cp1252 fallback; M&E sections excluded; unit tests per case | Heading and encoding errors assigned passages to the wrong sections | Initial rules kept only 3,768 passages and read numbered paragraphs ("86. The concerned government agencies were ...") as headings; a later rule rejected "IV. BANK PERFORMANCE, COMPLIANCE ISSUES, AND RISK ..."; some reports are Windows-1252; result: 4,495 passages from 300 reports |
# MAGIC | The 970,000 bid and award edges loaded once into integer-coded arrays for supplier profiles | Spark joins were too slow for an interactive loop, and caching held driver memory | Joins over the 2.3 million edges took 26 to 74 seconds per profile; with arrays (a few MB) a profile takes about 4.5 seconds; the co-bidder answer is identical to the join version |
# MAGIC | Tolerant tool interfaces: numeric strings converted for integer parameters; country names and method codes resolved by every tool; embeddings in batches of 8 paced at 10 texts per second across threads, with longer backoff; the benchmark tool reads only documented columns, casts decimals and falls back to `tender_timelines` peer groups | Model quirks, the shared rate limit and another component's table must not break tool calls | Qwen 3.5 sent numbers as strings (`"k": "5"`), rejected ten times in one run with two core tools forced (after the fix: 4 own calls, no forced tool); both models pass country names ("Kenya"); a 31-text request was refused with HTTP 429 eight times in a row; `proc_gold.tender_benchmarks` has a decimal `slow_rate` |
# MAGIC | The trace's evidence span includes the package text as a non-citable "user input" document | The groundedness judge must see everything the agent was given | In a trial the judge marked a brief ungrounded partly because it restated the package ("speedboats ... between islands") |
# MAGIC | A precedent needs re-rank cosine >= 0.68 and TF-IDF cosine >= 0.08; lower-ranked candidates fill freed places; the writer lists only genuinely similar records and the code accepts only records marked close | Always listing five precedents included irrelevant ones; the cosine level moves with the query | 200 judged pairs (74% relevant): GTE ROC-AUC 0.77, TF-IDF 0.66, same method 0.56; best candidates score 0.70 (relevant) and 0.73 (speedboats, not relevant; 0 of 5 relevant); a 0.74 cosine cut empties four packages; speedboat look-alikes have TF-IDF 0.05 to 0.07; best F0.5 on the grid: precision 0.83 vs 0.76 unfiltered, recall 0.86; leave-one-package-out picked the same pair for 19 of 20 (out-of-fold precision 0.81) |
# MAGIC | `proc_intel.forecast.planning_features` fills unknown notice facts with documented defaults listed in `assumptions`; unknown project facts stay missing; untrained methods or categories return an unscored record and the brief falls back to the peer group | A planning brief comes before the notice, but the model needs 27 notice-date features | Country, method, category, market history and governance are known at planning time; cohort medians: Request for Bids works 28 days advertising, 7,862-character notices; QCBS 18 days, expressions of interest; direct selection and individual consultants cannot be scored; section 5f measures the cost of the defaults |
# MAGIC
# MAGIC Limitations: the precedent-threshold gain is modest.
# MAGIC
# MAGIC Full reasoning: docs/decision_log.md

# COMMAND ----------

# MAGIC %md
# MAGIC ## Setup
# MAGIC
# MAGIC **What:** shared settings and Spark helpers (`proc_common`), then the agent's tools and loop (`proc_rag_core`), and this notebook's constants for the completion-report corpus.
# MAGIC
# MAGIC **Why:**
# MAGIC - **At most 300 completion reports and 15,000 passages:** enough to cover every region and the main sectors with several reports each, while the embedding run stays under 20 minutes at the workspace's rate limit (about 15 texts per second).
# MAGIC - **Completion reports are allowed here.** The outcome project never used them because they contain the outcome it predicted. This agent predicts nothing; it retrieves lessons, and the lessons are exactly what completion reports are written for.

# COMMAND ----------

# MAGIC %run ./proc_common

# COMMAND ----------

# MAGIC %run ./proc_rag_core

# COMMAND ----------

import glob
import os
from concurrent.futures import ThreadPoolExecutor

from proc_intel.agent_tools import choose_precedent_rule, is_close_precedent, precedent_rule_metrics
from proc_intel.lessons import decode_report, lesson_chunks

ICR_ROOT = f"{RAW_VOLUME}/icr_docs"
WDS_URL = "https://search.worldbank.org/api/v2/wds"
ICR_TYPE = "Implementation Completion and Results Report"
# 300 reports keep the embedding run under ~20 minutes at the shared ~15 texts/s limit
MAX_DOCS = 300
MAX_PER_DOC = 50                 # 300 x 50 = the 15,000-passage budget
EMBED_BATCH = 8                  # texts per request; the workspace limit counts every text
# stored on every passage so a later chunker change can be told apart from this corpus
CHUNKER_VERSION = "lessons-v1"
EVAL_FILE = os.path.abspath(os.path.join(os.getcwd(), "..", "data", "agent_eval_packages.json"))
LABEL_FILE = os.path.abspath(os.path.join(os.getcwd(), "..", "data", "agent_relevance_labels.csv"))
os.makedirs(f"{ICR_ROOT}/metadata", exist_ok=True)
os.makedirs(f"{ICR_ROOT}/text", exist_ok=True)
os.makedirs(f"{ICR_ROOT}/embeddings", exist_ok=True)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. The completion-report lessons corpus
# MAGIC
# MAGIC ### 1a. Catalog of completion reports and the selection
# MAGIC
# MAGIC **What:** pages through the World Bank Documents & Reports API for every *Implementation Completion and Results Report* (metadata only: project id, date, language, text URL), saving each page in the volume (a re-run reads the saved pages). Then picks one report per project (the latest English one with a text version) for projects that appear in the procurement data, and selects up to 300, spread over regions and sectors: within each region, projects are taken in turn from each major sector, those with the most openly competed contracts first.
# MAGIC
# MAGIC **Why:** lessons are most useful where the procurement data can back them up (the same projects' contracts and timelines), and a brief for a road package in Africa should be able to find lessons from roads in Africa. Spreading over region and sector avoids a corpus dominated by the few countries with the most contracts.

# COMMAND ----------

def fetch_icr_catalog():
    pages = sorted(glob.glob(f"{ICR_ROOT}/metadata/page_*.json"))
    # saved catalog pages are reused, so a re-run does not page the Documents API again
    if pages:
        print(f"catalog: reusing {len(pages)} saved pages")
        return pages
    offset, total = 0, None
    while total is None or offset < total:
        r = requests.get(WDS_URL, timeout=120, params={"format": "json", "rows": 1000, "os": offset, "docty_exact": ICR_TYPE,
                                                       "fl": "projectid,docdt,docty,lang,txturl,display_title"})
        r.raise_for_status()
        body = r.json()
        total = int(body["total"])
        # the API returns documents as a dict keyed by id, with a "facets" entry mixed in
        page = [v for k, v in body["documents"].items() if k != "facets"]
        if not page:
            break
        with open(f"{ICR_ROOT}/metadata/page_{offset:06d}.json", "w") as f:
            json.dump(page, f)
        offset += 1000
        time.sleep(0.5)
    print(f"catalog: {total} reports in {offset // 1000} pages")
    return sorted(glob.glob(f"{ICR_ROOT}/metadata/page_*.json"))


rows = []
for p in fetch_icr_catalog():
    for d in json.load(open(p)):
        rows.append({"doc_id": str(d.get("id")), "projectid": d.get("projectid") or "", "doc_date": (d.get("docdt") or "")[:10],
                     "lang": d.get("lang") or "", "txt_url": d.get("txturl"), "title": d.get("display_title")})
catalog = spark.createDataFrame(pd.DataFrame(rows))
catalog.createOrReplaceTempView("icr_catalog")
print(f"catalog rows: {catalog.count():,}")

# one report per project, then round-robin over sectors within each region so no single sector or country fills the
# corpus;
# the 7 regions share the 300 places, hence region_rank <= MAX_DOCS // 7 + 1 inside the query
selection = spark.sql(f"""
    WITH docs AS (
      SELECT doc_id, trim(pid) AS project_id, try_to_date(nullif(doc_date, '')) AS doc_date, regexp_replace(txt_url, '^http://', 'https://') AS txt_url, title
      FROM icr_catalog LATERAL VIEW explode(split(projectid, ',')) AS pid
      WHERE lang LIKE '%English%' AND txt_url IS NOT NULL),
    latest AS (
      SELECT * FROM (SELECT d.*, row_number() OVER (PARTITION BY project_id ORDER BY doc_date DESC, doc_id) AS rn FROM docs d) WHERE rn = 1),
    open_counts AS (
      SELECT project_id, count(*) AS n_open_contracts FROM {GOLD}.tender_timelines WHERE competition = 'open' GROUP BY 1),
    cand AS (
      SELECT l.doc_id, l.project_id, p.project_name, p.country_code, p.region, coalesce(p.major_sector, 'Unknown') AS major_sector,
             l.doc_date, l.txt_url, l.title, coalesce(o.n_open_contracts, 0) AS n_open_contracts
      FROM latest l JOIN {SILVER}.dim_project p USING (project_id) LEFT JOIN open_counts o USING (project_id)
      WHERE p.region IS NOT NULL AND p.region NOT IN ('Other', 'Africa')),
    one_per_doc AS (
      SELECT * FROM (SELECT c.*, row_number() OVER (PARTITION BY doc_id ORDER BY n_open_contracts DESC, project_id) AS rd FROM cand c) WHERE rd = 1),
    ranked AS (
      SELECT *, row_number() OVER (PARTITION BY region, major_sector ORDER BY n_open_contracts DESC, project_id) AS sector_turn
      FROM one_per_doc),
    turns AS (
      SELECT *, row_number() OVER (PARTITION BY region ORDER BY sector_turn, n_open_contracts DESC, project_id) AS region_rank,
             count(*) OVER () AS n_candidates FROM ranked)
    SELECT doc_id, project_id, project_name, country_code, region, major_sector, doc_date, txt_url, title, n_open_contracts,
           region_rank AS selection_rank, n_candidates
    FROM turns WHERE region_rank <= {MAX_DOCS // 7 + 1}
    ORDER BY region_rank, region LIMIT {MAX_DOCS}""").toPandas()
print(f"projects in the procurement data with an English completion report: {int(selection.n_candidates.iat[0]):,}; "
      f"selected {len(selection)}")
selection = selection.drop(columns="n_candidates")
display(selection.groupby("region").agg(reports=("doc_id", "count"), sectors=("major_sector", "nunique"),
                                        median_open_contracts=("n_open_contracts", "median")).reset_index())

# COMMAND ----------

# MAGIC %md
# MAGIC ### 1b. Download the text versions (parallel, resumable)
# MAGIC
# MAGIC **What:** downloads each selected report's `.txt` (the Bank's own text extraction) to the volume with 4 threads, skipping files already there, and records the status of every download.
# MAGIC
# MAGIC **Why:** the same pattern as the outcome project's document ingest: a re-run only fetches what is missing, and a failed download is a recorded status, not a crash.

# COMMAND ----------

session = requests.Session()


def download(row):
    path = f"{ICR_ROOT}/text/{row.project_id}__{row.doc_id}.txt"
    # resumable: a file already on the volume is not downloaded again (empty files from a failed write are retried)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return row.doc_id, path, "exists", os.path.getsize(path)
    status = "error"
    for attempt in range(3):
        try:
            r = session.get(row.txt_url, timeout=90)
            if r.status_code == 200 and r.content:
                with open(path, "wb") as f:
                    f.write(r.content)
                return row.doc_id, path, "ok", len(r.content)
            status = f"http_{r.status_code}"
        except Exception as e:
            status = f"error_{type(e).__name__}"
        time.sleep(2 * (attempt + 1))
    return row.doc_id, None, status, 0


t0 = time.time()
with ThreadPoolExecutor(max_workers=4) as pool:
    dl = pd.DataFrame(list(pool.map(download, selection.itertuples())), columns=["doc_id", "path", "download_status", "n_bytes"])
docs = selection.merge(dl, on="doc_id")
print(f"downloads in {time.time() - t0:.0f} s: {docs.download_status.value_counts().to_dict()}; "
      f"median size {docs.n_bytes[docs.n_bytes > 0].median() / 1024:.0f} KB")

# COMMAND ----------

# MAGIC %md
# MAGIC ### 1c. Procurement-relevant passages
# MAGIC
# MAGIC **What:** each report is split into sections by its headings and cut into passages of about 220 words that never cross a section; a passage is kept when it sits in a lessons / procurement / fiduciary / implementation-factor section and mentions procurement, or mentions at least three distinct procurement terms anywhere (`proc_intel.lessons`). At most 50 passages per report, the most procurement-dense first. One report's kept passages are printed for a reading check.
# MAGIC
# MAGIC **Why:** a completion report is mostly about outcomes and results indicators; embedding all of it would spend most of the budget on passages the agent never needs, and dilute the search.

# COMMAND ----------

chunk_rows, stats = [], []
for d in docs[docs.path.notna()].itertuples():
    # decode_report falls back to cp1252: some of the Bank's text extractions are not valid UTF-8
    raw = decode_report(open(d.path, "rb").read())
    kept = lesson_chunks(raw, max_per_doc=MAX_PER_DOC)
    stats.append({"doc_id": d.doc_id, "n_words": len(raw.split()), "n_kept": len(kept)})
    for c in kept:
        chunk_rows.append({"chunk_id": f"{d.project_id}-{d.doc_id}-{c['chunk_index']:04d}", "doc_id": d.doc_id,
                           "project_id": d.project_id, "chunk_index": c["chunk_index"], "section": c["section"],
                           "chunk_text": c["text"], "n_words": c["n_words"], "relevance_score": c["score"]})
chunks = pd.DataFrame(chunk_rows)
st = pd.DataFrame(stats)
docs = docs.merge(st, on="doc_id", how="left")
print(f"{len(chunks):,} passages kept from {int((st.n_kept > 0).sum())} of {len(st)} reports "
      f"(median {st.n_kept.median():.0f} per report; {int((st.n_kept == 0).sum())} reports with none)")
display(chunks.assign(section_head=chunks.section.str.split(" > ").str[0].str[:60])
        .groupby("section_head").size().sort_values(ascending=False).head(12).rename("passages").reset_index())
ex = chunks[chunks.doc_id == chunks.doc_id.iloc[0]]
for c in ex.head(4).itertuples():
    print(f"\n[{c.chunk_id}] {c.section} ({c.n_words} words, score {c.relevance_score})\n   {c.chunk_text[:400]} ...")

# COMMAND ----------

# MAGIC %md
# MAGIC ### 1d. Embeddings (checkpointed) and the two tables
# MAGIC
# MAGIC **What:** embeds each passage with `databricks-gte-large-en` (text = report type, project name and section, then the passage), one request of 8 texts at a time, normalised to unit length. Vectors are saved in the volume in groups of 1,000 keyed by a hash of the embedded text, so a re-run (or a run that stopped half-way) only embeds what is new. Then publishes `proc_silver.lesson_documents` and `proc_silver.lesson_chunks` with comments, keys and foreign keys, and checks them.
# MAGIC
# MAGIC **Why:** embedding is the only paid, slow step of the corpus; the checkpoint makes it idempotent. The section and project name in the embedded text help a query like "delays in rural road works" find the right passages even when the passage itself only says "the works".

# COMMAND ----------

proj_names = {p: r.project_name for p, r in refs()["projects"].items()}
# project name and section go into the embedded text so a query can match a passage that only says "the works"
chunks["embed_text"] = [f"Completion report | {proj_names.get(p, '')} | {s}\n{t}"
                        for p, s, t in zip(chunks.project_id, chunks.section, chunks.chunk_text)]
# checkpoint key: a vector is reused only if the exact embedded text is unchanged
chunks["text_hash"] = [hashlib.sha256(t.encode()).hexdigest()[:32] for t in chunks.embed_text]

done = {}
for f in sorted(glob.glob(f"{ICR_ROOT}/embeddings/group_*.parquet")):
    g = pd.read_parquet(f)
    done.update(zip(g.text_hash, g.embedding))
todo = chunks[~chunks.text_hash.isin(done)].drop_duplicates("text_hash")
print(f"embeddings: {len(done):,} reused, {len(todo):,} to embed")
t0, n_groups = time.time(), len(glob.glob(f"{ICR_ROOT}/embeddings/group_*.parquet"))
for start in range(0, len(todo), 1000):
    part = todo.iloc[start:start + 1000]
    V = embed_texts(part.embed_text.tolist(), batch_size=EMBED_BATCH)
    g = pd.DataFrame({"text_hash": part.text_hash.to_numpy(), "embedding": list(V)})
    # one file per 1,000 vectors: an interrupted run loses at most the group in progress
    g.to_parquet(f"{ICR_ROOT}/embeddings/group_{n_groups:04d}.parquet")
    n_groups += 1
    done.update(zip(g.text_hash, g.embedding))
    print(f"  {start + len(part):,}/{len(todo):,} embedded ({time.time() - t0:.0f} s)")
chunks["embedding"] = [np.asarray(done[h], dtype="float32").tolist() for h in chunks.text_hash]

# COMMAND ----------

doc_df = spark.createDataFrame(docs[["doc_id", "project_id", "project_name", "country_code", "region", "major_sector", "doc_date",
                                     "title", "txt_url", "n_open_contracts", "selection_rank", "download_status", "n_bytes",
                                     "n_words", "n_kept"]].assign(doc_type=ICR_TYPE, n_words=lambda x: x.n_words.fillna(0).astype(int),
                                                                  n_kept=lambda x: x.n_kept.fillna(0).astype(int)))
n_docs = publish_table(
    doc_df, LESSON_DOCS_TABLE,
    "Completion reports (ICRs) selected for the agent's lessons corpus. Grain: one row per report. Source: World Bank "
    "Documents & Reports API; one report per project, spread over regions and sectors.",
    {"doc_id": "PK. Document id in the Documents & Reports API", "project_id": "FK proc_silver.dim_project",
     "project_name": "Project name", "country_code": "FK proc_silver.dim_country (project country)",
     "region": "World Bank region", "major_sector": "Project major sector", "doc_date": "Document date",
     "title": "Document title", "txt_url": "URL of the text version", "doc_type": "Implementation Completion and Results Report",
     "n_open_contracts": "Openly competed contracts of the project in tender_timelines (selection priority)",
     "selection_rank": "Turn within its region in the region x sector round-robin", "download_status": "ok, exists or the error",
     "n_bytes": "Size of the downloaded text", "n_words": "Words in the text", "n_kept": "Procurement-relevant passages kept"},
    primary_key=["doc_id"])
add_foreign_key(LESSON_DOCS_TABLE, ["project_id"], f"{SILVER}.dim_project", ["project_id"])

meta = docs.set_index("doc_id")
lc = chunks.assign(project_name=lambda x: x.doc_id.map(meta.project_name), country_code=lambda x: x.doc_id.map(meta.country_code),
                   region=lambda x: x.doc_id.map(meta.region), major_sector=lambda x: x.doc_id.map(meta.major_sector),
                   doc_type=ICR_TYPE, doc_date=lambda x: x.doc_id.map(meta.doc_date),
                   embedding_model=EMBED_ENDPOINT, chunker_version=CHUNKER_VERSION)
lc_df = spark.createDataFrame(lc[["chunk_id", "doc_id", "project_id", "project_name", "country_code", "region", "major_sector",
                                  "doc_type", "doc_date", "chunk_index", "section", "n_words", "relevance_score", "chunk_text",
                                  "embed_text", "text_hash", "embedding", "embedding_model", "chunker_version"]],
                              schema="chunk_id string, doc_id string, project_id string, project_name string, country_code string, "
                                     "region string, major_sector string, doc_type string, doc_date date, chunk_index int, "
                                     "section string, n_words int, relevance_score int, chunk_text string, embed_text string, "
                                     "text_hash string, embedding array<float>, embedding_model string, chunker_version string")
n_chunks = publish_table(
    lc_df, LESSON_TABLE,
    "Procurement-relevant passages of completion reports (ICRs), with GTE embeddings, for the agent's lessons_learned tool. "
    "Grain: one row per passage. chunk_id = project_id-doc_id-chunk_index.",
    {"chunk_id": "PK. project_id-doc_id-chunk_index; cited by the agent as lesson_chunk:<chunk_id>",
     "doc_id": "FK proc_silver.lesson_documents", "project_id": "FK proc_silver.dim_project", "project_name": "Project name",
     "country_code": "Project country code", "region": "World Bank region", "major_sector": "Project major sector",
     "doc_type": "Implementation Completion and Results Report", "doc_date": "Report date",
     "chunk_index": "Position of the passage in the full report (0-based)", "section": "Heading path (level 1 > level 2)",
     "n_words": "Words in the passage", "relevance_score": "Distinct procurement terms (+2 in a focus section); ranking within a report",
     "chunk_text": "Passage text", "embed_text": "Text that was embedded (report type, project, section, passage)",
     "text_hash": "SHA-256 prefix of embed_text (embedding checkpoint key)", "embedding": "Unit-length GTE vector (1,024 numbers)",
     "embedding_model": "Embedding endpoint", "chunker_version": "Version of the passage rules"},
    primary_key=["chunk_id"])
add_foreign_key(LESSON_TABLE, ["doc_id"], LESSON_DOCS_TABLE, ["doc_id"])
add_foreign_key(LESSON_TABLE, ["project_id"], f"{SILVER}.dim_project", ["project_id"])

L, D = spark.table(LESSON_TABLE), spark.table(LESSON_DOCS_TABLE)
# squared length of each vector in SQL; retrieval uses dot products, which equal cosines only for unit vectors
norms = L.select(F.expr("aggregate(embedding, 0D, (a, x) -> a + x * x)").alias("n2"))
display(dq_report([
    (LESSON_DOCS_TABLE, "rows (reports selected)", n_docs, f"<= {MAX_DOCS}"),
    (LESSON_DOCS_TABLE, "duplicate doc_id", duplicate_keys(D, ["doc_id"]), "== 0"),
    (LESSON_DOCS_TABLE, "orphan project_id", orphan_count(D, "project_id", spark.table(f"{SILVER}.dim_project"), "project_id"), "== 0"),
    (LESSON_DOCS_TABLE, "reports with a failed download", D.filter("download_status NOT IN ('ok', 'exists')").count(), "info"),
    (LESSON_TABLE, "rows (passages)", n_chunks, "<= 15000"),
    (LESSON_TABLE, "duplicate chunk_id", duplicate_keys(L, ["chunk_id"]), "== 0"),
    (LESSON_TABLE, "orphan doc_id", orphan_count(L, "doc_id", D, "doc_id"), "== 0"),
    (LESSON_TABLE, "null or short embeddings", L.filter("embedding IS NULL OR size(embedding) <> 1024").count(), "== 0"),
    (LESSON_TABLE, "vectors not unit length (|n2 - 1| > 1e-3)", norms.filter("abs(n2 - 1) > 1e-3").count(), "== 0"),
    (LESSON_TABLE, "distinct projects", L.select("project_id").distinct().count(), "info"),
    (LESSON_TABLE, "distinct regions", L.select("region").distinct().count(), "info")]))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. The five tools on one package
# MAGIC
# MAGIC **What:** each tool called directly (no model) for the package used as the running example: *rehabilitation of 120 km of rural roads in Kenya, works, Request for Bids*. The outputs are what the planner and writer see. The forecast is also shown for the same package with a planned notice date, and for a method the model was not trained on (direct selection), which must fall back to the peer group.
# MAGIC
# MAGIC **Why:** a reader can check that each tool returns sensible, citable records before any model is involved; this is also the first latency check (the contract index and lesson vectors load on the first call).

# COMMAND ----------

EXAMPLE = {"description": "Rehabilitation of 120 km of rural roads, lot 2", "country": "Kenya", "category": "CW",
           "method": "Request for Bids"}
t0 = time.time()
sim = similar_past_contracts(EXAMPLE["description"], EXAMPLE["country"], EXAMPLE["category"])
print(f"similar_past_contracts ({time.time() - t0:.1f} s incl. first load), best similarity {sim['best_similarity']}")
print(f"  {len(sim['records'])} close precedents (re-rank cosine >= {MIN_PRECEDENT_COSINE}, TF-IDF >= {MIN_PRECEDENT_TFIDF}); best re-rank cosine "
      f"{sim['best_rerank_cosine']}; {sim['notes']}")
display(pd.DataFrame(sim["records"]).reindex(columns=["record_id", "label", "country_code", "method", "amount_usd",
                                                      "days_notice_to_signing", "n_firms_in_award_notice", "suppliers",
                                                      "similarity", "rerank_cosine"]))
bench = tender_benchmark(EXAMPLE["method"], EXAMPLE["category"], EXAMPLE["country"])
print(f"tender_benchmark: chosen {bench['chosen']}  {bench['notes']}")
display(pd.DataFrame(bench["records"])[["record_id", "label", "n_contracts", "p10_days", "p50_days", "p90_days", "chosen", "source"]])
t0 = time.time()
fct = forecast_timeline(EXAMPLE)
print(f"\nforecast_timeline ({time.time() - t0:.1f} s incl. loading the model and the history tables)")
print(json.dumps({k: v for k, v in fct["records"][0].items() if k != "features"}, indent=1, default=str))
for variant in ({**EXAMPLE, "planned_notice_date": "2027-03-01", "advertising_days": 60},
                {**EXAMPLE, "method": "Direct Selection"}):
    r = forecast_timeline(variant)["records"][0]
    print(f"\n{ {k: variant[k] for k in variant if k not in EXAMPLE or variant[k] != EXAMPLE[k]} } -> {r['record_id']} scored={r['scored']} "
          f"P10/P50/P90 {r['p10_days']}/{r['p50_days']}/{r['p90_days']} slow {r['slow_probability']} | {r['label'][:140]}")
t0 = time.time()
les = lessons_learned("delays and contractor performance in rural road rehabilitation works contracts", EXAMPLE["country"])
print(f"lessons_learned ({time.time() - t0:.1f} s incl. first load), best cosine {les['best_cosine']}")
display(pd.DataFrame(les["records"]).assign(text=lambda x: x.text.str[:200])[["record_id", "source", "project_name", "label", "cosine", "text"]])
top_supplier = next((r["supplier_entity_ids"][0] for r in sim["records"] if r["supplier_entity_ids"]), None)
t0 = time.time()
sup = supplier_profile(top_supplier)
print(f"supplier_profile({top_supplier}) in {time.time() - t0:.1f} s")
print(json.dumps(sup["records"][0], indent=1, default=str)[:1500])

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Choosing the planner model: Qwen 3.5 vs Llama 3.3
# MAGIC
# MAGIC **What:** the full agent (same guard, tools and writer prompt) on three packages that are *not* in the evaluation set, once with `databricks-qwen35-122b-a10b` (thinking off) and once with `databricks-meta-llama-3-3-70b-instruct` as planner and writer. Compared per run: tool calls made by the model itself, core tools the code had to add, invalid tool calls, whether the brief was valid JSON on the first try, citation validity before cleaning, risks and precedents that survived validation, latency and tokens.
# MAGIC
# MAGIC **Decision rule (in code):** fewest forced tools plus invalid citations plus invalid first replies; ties go to the lower token cost (DBU), then the lower median latency. Cost comes before latency because latency on the shared pay-per-token endpoints is noisy: in phase 2 Qwen was the faster model (15 s vs 23 s), in the first phase-3 run Llama was (21 s vs 36 s), while the cost ratio (Llama about twice Qwen per brief) is stable. Claude endpoints are not available in this workspace, so these are the two candidates with tool calling.

# COMMAND ----------

CHOICE_PACKAGES = [
    EXAMPLE,
    {"description": "Supply and installation of laboratory equipment for regional hospitals", "country": "Ghana",
     "category": "GO", "method": "Request for Bids"},
    {"description": "Consultant for the design and construction supervision of small town water supply systems",
     "country": "Uganda", "category": "CS", "method": "Quality And Cost-Based Selection"}]
CANDIDATES = ["databricks-qwen35-122b-a10b", "databricks-meta-llama-3-3-70b-instruct"]


def run_summary(r):
    v = r.get("validation") or {}
    b = r.get("brief") or {}
    return {"status": r["status"], "model_tool_calls": sum(not c["forced"] for c in r.get("calls", [])),
            "forced_tools": len(r.get("forced_tools", [])), "invalid_tool_calls": len(r.get("tool_errors", [])),
            "json_first_try": (r.get("writer") or {}).get("first_try_valid"), "n_citations": v.get("n_citations"),
            "citation_validity": v.get("citation_validity"), "n_invalid_citations": len(v.get("invalid_citations", [])),
            "risks_kept": len(b.get("risks", [])), "precedents_kept": len(b.get("precedents", [])),
            "forecast_p50_days": (b.get("timeline") or {}).get("forecast_p50_days"),
            "peer_p50_days": (b.get("timeline") or {}).get("peer_p50_days"),
            "flags": ",".join(r["flags"]), "latency_s": r["latency_s"],
            "tokens_in": sum(u[0] for u in r["usage"].values()), "tokens_out": sum(u[1] for u in r["usage"].values()),
            "dbu": r["dbu"]}


choice = []
for model in CANDIDATES:
    for i, pkg in enumerate(CHOICE_PACKAGES):
        r = procurement_brief(pkg, model=model)
        choice.append({"model": model.replace("databricks-", ""), "package": i + 1, **run_summary(r)})
choice = pd.DataFrame(choice)
display(choice)
# a fallback brief is the worst outcome, so it weighs three times a single forced tool or bad citation
score = (choice.assign(bad=lambda x: x.forced_tools + x.n_invalid_citations + (x.json_first_try == False).astype(int)
                       + (x.status == "fallback").astype(int) * 3)
         .groupby("model").agg(bad=("bad", "sum"), median_latency_s=("latency_s", "median"), dbu=("dbu", "sum")))
display(score.reset_index())
# ties go to cost before latency: latency on the shared pay-per-token endpoints changed a lot from day to day
CHOSEN_MODEL = "databricks-" + score.sort_values(["bad", "dbu", "median_latency_s"]).index[0]
PLANNER_MODEL = CHOSEN_MODEL
print(f"planner and writer model for the rest of this notebook: {CHOSEN_MODEL}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. One full brief, with its citations
# MAGIC
# MAGIC **What:** the agent on the running example with the chosen model: the tool calls it made (and whether any were forced), the validated brief as text, the validation report, and every cited record with what it is, so each citation can be followed back to a contract, a benchmark group or a document passage.
# MAGIC
# MAGIC **Why:** this is what a user would receive; showing the cited records next to it is the "verifiable" part of the requirement.
# MAGIC
# MAGIC The second cell calls the stable interface `run_agent` on the same package and prints its compact output (the timeline block and the precedents), which is what other components consume.

# COMMAND ----------

demo = procurement_brief(EXAMPLE)
print("tool calls:")
for c in demo["calls"]:
    print(f"  {'(forced) ' if c['forced'] else ''}{c['tool']}({json.dumps(c['args'])}) -> {c['n_records']} records")
print(f"\nstatus {demo['status']} | flags {demo['flags']} | {demo['latency_s']} s | evidence strength {demo['strength']}\n")
print(demo["text"])
print("\nvalidation:", json.dumps({k: v for k, v in demo["validation"].items() if k != "cited_ids"}))
cited = demo["validation"]["cited_ids"]
display(pd.DataFrame([{"record_id": c, "type": demo["records"][c]["type"], "what": demo["records"][c].get("label"),
                       "project": demo["records"][c].get("project_name"),
                       "detail": (demo["records"][c].get("text") or "; ".join(demo["records"][c].get("assumptions", [])))[:180]}
                      for c in cited]))

# COMMAND ----------

# COMMAND ----------

api_out = run_agent(EXAMPLE)
print("run_agent keys:", sorted(api_out))
print(json.dumps({k: api_out[k] for k in ("status", "timeline", "n_precedents", "precedents", "flags", "citation_validity",
                                          "latency_s")}, indent=1, default=str)[:3500])

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Evaluation
# MAGIC
# MAGIC ### 5a. The evaluation set
# MAGIC
# MAGIC **What:** 20 package descriptions written by an AI agent during the build from real, openly competed contracts across all seven regions and four categories (`data/agent_eval_packages.json`; one in French), plus 3 guard cases (an off-topic request, a direct injection, and a package description with a planted instruction). Each package keeps the country, method and category of its source contract; the **source contract's whole project is held out** from contract retrieval, so sibling lots of the same tender cannot count as easy hits.
# MAGIC
# MAGIC **Why:** realistic inputs (short, sometimes vague, not always in English) with a known origin. 20 packages give error bars of roughly 10 to 20 points on a rate; the numbers below are a sanity check of a prototype, not a benchmark.

# COMMAND ----------

ev = json.load(open(EVAL_FILE))
src = (spark.table(f"{SILVER}.contracts").filter(F.col("contract_id").isin([p["source_contract_id"] for p in ev["packages"]]))
       .select("contract_id", "project_id", "contract_description").toPandas().set_index("contract_id"))
packages = []
for p in ev["packages"]:
    pkg = {k: p[k] for k in ("description", "country", "category", "method")}
    # hold out the source contract's whole project, or the search would simply find the contract the package was written
    # from
    pkg["_exclude_projects"] = [src.project_id[p["source_contract_id"]]]
    packages.append({"eval_id": p["id"], "source_contract_id": p["source_contract_id"], "package": pkg})
guard_cases = [{"eval_id": g["id"], "expected": g["expected"],
                "package": {k: g[k] for k in ("description", "country", "category", "method")}} for g in ev["guard"]]
display(pd.DataFrame([{"eval_id": p["eval_id"], **{k: v for k, v in p["package"].items() if not k.startswith("_")},
                       "held-out project": p["package"]["_exclude_projects"][0],
                       "source contract": f"{p['source_contract_id']}: {src.contract_description[p['source_contract_id']][:80]}"}
                      for p in packages]))

# COMMAND ----------

# MAGIC %md
# MAGIC ### 5b. Retrieval: precision@5 of similar past contracts, TF-IDF vs TF-IDF + GTE re-ranking
# MAGIC
# MAGIC **What:** for every evaluation package, the top 5 contracts from TF-IDF alone and the top 10 from TF-IDF with the best 30 re-ranked by GTE embeddings (precedent threshold off, so the ranking itself is measured; ranks 6-10 serve the threshold check below). Each distinct (package, contract) pair is judged once by `gpt-oss-120b` (a different model family from the planner): *is this past contract the same kind of works, goods or services, so that its procurement experience is informative?* Precision@5 = share of the five slots judged relevant (an empty slot counts as a miss). A hash-ordered sample of 30 judged pairs is also labelled by an AI agent during the build (`data/agent_relevance_labels.csv`) to check the judge.
# MAGIC
# MAGIC **Why:** whether a precedent is relevant is a judgement about the description, not just the category (which the tool already filters on). An LLM judge scales to all pairs; 30 reference labels made by an AI agent during the build say how far to trust it. Re-ranking costs 31 embeddings per query (about 3 s at the paced rate); it is switched on for the agent only if it raises precision@5 by at least 5 points.

# COMMAND ----------

# strict JSON schema so the judge's verdict parses without free-text handling
REL_SCHEMA = {"type": "json_schema", "json_schema": {"name": "relevance", "strict": True, "schema": {
    "type": "object", "additionalProperties": False, "required": ["relevant", "reason"],
    "properties": {"relevant": {"type": "boolean"}, "reason": {"type": "string"}}}}}
REL_SYSTEM = """You judge whether a past contract is a relevant precedent for a new procurement package.
Relevant means the past contract procured the same kind of works, goods or services (for example both are rural road
rehabilitation works, both are laboratory equipment, both are supervision of building works), so its procurement
experience (method, duration, number of bidders) is informative for the new package. The country does not matter.
Not relevant: a different kind of item or service, even in the same sector (road works vs a building; design of a
strategy vs supply of computers), or a description too vague to tell. Return JSON {"relevant": bool, "reason": short}."""


def judge_relevance(pkg, rec):
    msg = (f"NEW PACKAGE ({pkg['category']}): {pkg['description']}\n\nPAST CONTRACT ({rec.get('category')}, {rec.get('method')}, "
           f"{rec.get('country_code')}): {rec.get('label')}\nProject: {rec.get('project_name')}")
    err = ""
    for attempt in (1, 2):
        try:
            r = chat([{"role": "system", "content": REL_SYSTEM}, {"role": "user", "content": msg}], JUDGE_MODEL,
                     max_tokens=900, response_format=REL_SCHEMA)
            v = json.loads(r["text"])
            return bool(v["relevant"]), str(v.get("reason", ""))[:200]
        except Exception as e:
            err = str(e)[:100]
    return None, f"judge failed: {err}"


retr = []
for p in packages:
    pkg = p["package"]
    for variant, rr_, k_ in (("tfidf", False, 5), ("tfidf_gte_rerank", True, 10)):
        # min_cosine=None switches the precedent filter off: this measures the ranking itself
        res = similar_past_contracts(pkg["description"], pkg["country"], pkg["category"], k=k_, rerank=rr_,
                                     exclude_project_ids=pkg["_exclude_projects"], min_cosine=None)
        for rank, rec in enumerate(res["records"], 1):
            retr.append({"eval_id": p["eval_id"], "variant": variant, "rank": rank, "contract_id": rec["record_id"].split(":")[1],
                         "similarity": rec["similarity"], "rerank_cosine": rec["rerank_cosine"],
                         "same_country": rec["same_country"], "rec": rec})
retr = pd.DataFrame(retr)
# a contract found by both variants is judged once, so both variants are scored with the same verdict
pairs = retr.drop_duplicates(["eval_id", "contract_id"]).reset_index(drop=True)
pkg_of = {p["eval_id"]: p["package"] for p in packages}
with ThreadPoolExecutor(max_workers=2) as pool:
    verdicts = list(pool.map(lambda r: judge_relevance(pkg_of[r.eval_id], r.rec), pairs.itertuples()))
pairs = pairs.assign(relevant=[v[0] for v in verdicts], judge_reason=[v[1] for v in verdicts])
retr = retr.merge(pairs[["eval_id", "contract_id", "relevant", "judge_reason"]], on=["eval_id", "contract_id"])
top5_retr = retr[retr["rank"] <= 5]
# a failed judge call counts as not relevant, and fewer than 5 results still divide by 5, so the figure errs low
p_at_5 = (top5_retr.groupby(["variant", "eval_id"]).relevant.apply(lambda s: s.fillna(False).astype(bool).sum() / 5)
          .rename("p_at_5").reset_index())
summary_retr = p_at_5.groupby("variant").p_at_5.agg(["mean", "min", "max"]).round(3)
summary_retr["same_country_share"] = top5_retr.groupby("variant").same_country.mean().round(3)
summary_retr["judge_failures"] = retr.groupby("variant").relevant.apply(lambda s: int(s.isna().sum()))
print(f"{len(pairs)} distinct (package, contract) pairs judged ({len(top5_retr.drop_duplicates(['eval_id', 'contract_id']))} "
      f"in the two top-5 lists, the rest at re-rank ranks 6-10)")
display(summary_retr.reset_index())
display(p_at_5.pivot(index="eval_id", columns="variant", values="p_at_5").reset_index())
gain = summary_retr.loc["tfidf_gte_rerank", "mean"] - summary_retr.loc["tfidf", "mean"]
# re-ranking costs 31 embeddings per query; keep it only if it buys at least 5 points of precision
RERANK = bool(gain >= 0.05)
print(f"re-ranking gain in precision@5: {gain:+.3f} -> RERANK = {RERANK} for the agent")

# COMMAND ----------

# MAGIC %md
# MAGIC **Judge check against agent reference labels:** the 30 judged top-5 pairs with the smallest hash of (package id, contract id), with the judge's verdict; their reference labels (made by an AI agent during the build, by reading the package and the contract description; the column is named `human_relevant` for historical reasons) are read from `data/agent_relevance_labels.csv`.

# COMMAND ----------

top5_pairs = pairs.merge(top5_retr[["eval_id", "contract_id"]].drop_duplicates(), on=["eval_id", "contract_id"])
# hash order: the same 30 pairs on every run, so the saved reference labels keep matching
sample = (top5_pairs.assign(h=[hashlib.sha1(f"{a}|{b}".encode()).hexdigest() for a, b in zip(top5_pairs.eval_id, top5_pairs.contract_id)])
          .sort_values("h").head(30))
for r in sample.itertuples():
    print(f"{r.eval_id} | {r.contract_id} | judge={r.relevant} | PACKAGE: {pkg_of[r.eval_id]['description'][:80]} "
          f"|| CONTRACT: {r.rec['label'][:110]}")
if os.path.exists(LABEL_FILE):
    labels = pd.read_csv(LABEL_FILE, dtype={"contract_id": str, "eval_id": str})
    chk = sample.merge(labels, on=["eval_id", "contract_id"], how="inner")
    agree = (chk.relevant.astype(bool) == chk.human_relevant.astype(bool)).mean()
    print(f"\nhand labels: {len(chk)} of {len(sample)} sample pairs labelled; judge agrees on {agree:.0%}; "
          f"relevant share: human {chk.human_relevant.mean():.2f}, judge {chk.relevant.astype(float).mean():.2f}")
    display(chk[chk.relevant.astype(bool) != chk.human_relevant.astype(bool)]
            [["eval_id", "contract_id", "relevant", "human_relevant", "judge_reason", "note"]])
else:
    print("no hand-label file yet")

# COMMAND ----------

# MAGIC %md
# MAGIC **The precedent rule, checked on this run's judged pairs.** The agent keeps a re-ranked contract as a precedent only when its GTE cosine is at least `MIN_PRECEDENT_COSINE` **and** its TF-IDF cosine at least `MIN_PRECEDENT_TFIDF`, filling up to 5 from lower ranks. On the judged top-10 re-ranked candidates of this run: precision and recall of that rule as the tool applies it (recall = relevant precedents listed / min(5, relevant candidates) per package), against listing the top 5 unfiltered; the pair this run would pick (best F0.5 on a grid); a leave-one-package-out estimate (the pair is chosen on 19 packages and applied to the 20th); and, per package, whether a package left with no precedent really had nothing relevant among its candidates.
# MAGIC
# MAGIC **Why:** the rule was chosen once, on the phase-3 calibration pool (same 20 packages, 200 judged pairs, best F0.5 at 0.68 / 0.08, picked by 19 of 20 leave-one-out folds); re-checking it on every run shows drift when the corpus, the embedding model or the judge changes. Precision is weighted over recall because a listed precedent that is not comparable misleads the planner, while a missed one only costs coverage.

# COMMAND ----------

rr = retr[retr.variant == "tfidf_gte_rerank"].dropna(subset=["relevant"])
cand = [{"group": r.eval_id, "rank": r.rank, "cosine": r.rerank_cosine, "tfidf": r.similarity, "relevant": bool(r.relevant)}
        for r in rr.itertuples()]
COS_GRID, TFIDF_GRID = np.round(np.arange(0.60, 0.801, 0.02), 2), np.round(np.arange(0.0, 0.201, 0.02), 2)
rule_rows = [{"rule": "top 5, no filter", **precedent_rule_metrics(cand, 0.0, 0.0)},
             {"rule": f"agent: cosine >= {MIN_PRECEDENT_COSINE} and tfidf >= {MIN_PRECEDENT_TFIDF}",
              **precedent_rule_metrics(cand, MIN_PRECEDENT_COSINE, MIN_PRECEDENT_TFIDF)},
             {"rule": f"cosine only >= {MIN_PRECEDENT_COSINE}", **precedent_rule_metrics(cand, MIN_PRECEDENT_COSINE, 0.0)}]
# beta 0.5 weights precision over recall: a listed but unrelated precedent misleads more than a missing one
best_run = choose_precedent_rule(cand, COS_GRID, TFIDF_GRID, beta=0.5)
rule_rows.append({"rule": f"best F0.5 on this run: cosine >= {best_run['min_cosine']} and tfidf >= {best_run['min_tfidf']}", **best_run})
loo_taken = loo_tp = loo_cap = 0
loo_pairs = []
# leave one package out: choose the rule on 19 packages, apply it to the 20th, to see how much the choice overfits
for e in sorted({c["group"] for c in cand}):
    b_ = choose_precedent_rule([c for c in cand if c["group"] != e], COS_GRID, TFIDF_GRID, beta=0.5)
    m_ = precedent_rule_metrics([c for c in cand if c["group"] == e], b_["min_cosine"], b_["min_tfidf"])
    loo_pairs.append((b_["min_cosine"], b_["min_tfidf"]))
    loo_taken, loo_tp = loo_taken + m_["taken"], loo_tp + m_["relevant_taken"]
    loo_cap += min(5, sum(c["relevant"] for c in cand if c["group"] == e))
rule_rows.append({"rule": "leave-one-package-out", "taken": loo_taken, "relevant_taken": loo_tp,
                  "precision": loo_tp / max(1, loo_taken), "recall": loo_tp / max(1, loo_cap)})
rules = pd.DataFrame(rule_rows)
rules["zero_groups"] = rules["zero_groups"].apply(lambda z: ",".join(z) if isinstance(z, list) else None)
print(f"{len(cand)} judged re-ranked candidates (ranks 1-10), {sum(c['relevant'] for c in cand)} relevant; leave-one-out picked "
      f"{pd.Series(loo_pairs).value_counts().to_dict()}")
display(rules[["rule", "taken", "relevant_taken", "precision", "recall", "zero_groups"]].round(3))
per_pkg = (rr.assign(close=[is_close_precedent(c, t, MIN_PRECEDENT_COSINE, MIN_PRECEDENT_TFIDF)
                            for c, t in zip(rr.rerank_cosine, rr.similarity)], relevant=rr.relevant.astype(bool))
           .groupby("eval_id").apply(lambda g: pd.Series({
               "best_cosine": g.rerank_cosine.max(), "relevant_candidates": int(g.relevant.sum()),
               "listed": int(min(5, g.close.sum())),
               "relevant_listed": int(g[g.close].sort_values("rank").head(5).relevant.sum())}), include_groups=False).reset_index())
zero = per_pkg[per_pkg.listed == 0]
print(f"packages left with no precedent: {len(zero)} ({', '.join(zero.eval_id)}); with no relevant candidate in the top 10: "
      f"{int((zero.relevant_candidates == 0).sum())}")
display(per_pkg)

# COMMAND ----------

# MAGIC %md
# MAGIC ### 5c. When is the lessons evidence weak? Cosine of the best passage
# MAGIC
# MAGIC **What:** the best lesson-passage cosine for a procurement-risk query built from each evaluation package, next to the same for five unrelated queries (one embedding each, no chat model).
# MAGIC
# MAGIC **Why:** `MIN_LESSON_COSINE` decides when the lessons are reported as weak. GTE similarities sit in a narrow band, so the threshold has to be read off real queries.

# COMMAND ----------

OFF_TOPIC = ["recipe for chocolate cake with vanilla icing", "who won the football world cup final",
             "best hiking trails in the Alps in summer", "how to fix a python import error", "poem about the ocean at night"]
cal = [{"kind": "package", "best_cosine": lessons_learned(f"procurement risks and delays: {p['package']['description']}",
                                                          p["package"]["country"])["best_cosine"]} for p in packages]
cal += [{"kind": "off_topic", "best_cosine": lessons_learned(q)["best_cosine"]} for q in OFF_TOPIC]
cal = pd.DataFrame(cal)
display(cal.groupby("kind").best_cosine.describe().round(3).reset_index())
print(f"MIN_LESSON_COSINE = {MIN_LESSON_COSINE}: packages below it "
      f"{int((cal[cal.kind == 'package'].best_cosine < MIN_LESSON_COSINE).sum())} of {len(packages)}; off-topic queries at or "
      f"above it {int((cal[cal.kind == 'off_topic'].best_cosine >= MIN_LESSON_COSINE).sum())} of {len(OFF_TOPIC)}")

# COMMAND ----------

# MAGIC %md
# MAGIC ### 5d. End to end: the agent on all 20 packages, judged for groundedness
# MAGIC
# MAGIC **What:** every package goes through the full agent inside `mlflow.genai.evaluate`, so each run is a trace, and the built-in `RetrievalGroundedness` judge (run by `gpt-oss-120b`) checks whether the brief's statements are supported by the evidence the tools returned (the trace's RETRIEVER span holds every gathered record). Next to the judge, code checks: status, citation validity before cleaning, briefs with any invented id, risks removed for lack of a valid citation, timeline numbers corrected, core tools the code had to add, tool calls, latency and tokens. The precedents the brief actually cites are matched with the relevance verdicts from 5b (new pairs are judged the same way).
# MAGIC
# MAGIC
# MAGIC **Precedents, now 0 to 5:** for each brief, the number of precedents cited and their judged precision; a brief with **no** precedent counts as *right* when none of the package's top 10 re-ranked candidates was judged relevant in 5b (there was nothing close to find), and as a *miss* otherwise.
# MAGIC
# MAGIC **Why:** the judge answers "is it supported?", the code answers "is it traceable and within the rules?"; neither alone is enough. Two agents run at a time to stay under the endpoints' rate limits. The held-out project id is passed to the agent outside the judged inputs, so the judge sees only the package.

# COMMAND ----------

from mlflow.genai.scorers import RetrievalGroundedness

# two agents at a time keep the chat and embedding endpoints under their shared rate limits
os.environ["MLFLOW_GENAI_EVAL_MAX_WORKERS"] = "2"
JUDGE_URI = f"databricks:/{JUDGE_MODEL}"
store = {}
HELD_OUT = {p["package"]["description"]: p["package"]["_exclude_projects"] for p in packages}


def predict_fn(package):
    # the held-out project travels outside the judged inputs (in phase 2 the judge read it as part of the claim)
    r = procurement_brief({**package, "_exclude_projects": HELD_OUT[package["description"]]})
    # keep the full result: the judge only sees the text, the code checks below need the brief and the records
    store[package["description"]] = r
    return r["text"]


with mlflow.start_run(run_name="procurement_agent_eval"):
    mlflow.log_params({"planner_model": PLANNER_MODEL, "guard_model": GUARD_MODEL, "judge": JUDGE_MODEL, "rerank": RERANK,
                       "max_tool_calls": MAX_TOOL_CALLS, "n_packages": len(packages)})
    t0 = time.time()
    res = mlflow.genai.evaluate(data=[{"inputs": {"package": {k: v for k, v in p["package"].items() if not k.startswith("_")}}}
                                      for p in packages], predict_fn=predict_fn,
                                scorers=[RetrievalGroundedness(model=JUDGE_URI)])
    eval_wall_s = time.time() - t0
rdf = res.result_df
print(f"{len(store)} agent runs in {eval_wall_s:.0f} s (2 in parallel); judge columns: {[c for c in rdf.columns if '/' in c]}")


def _desc_of(req):
    req = req if isinstance(req, dict) else json.loads(req)
    return req["package"]["description"]


def _as_score(v):
    if isinstance(v, (list, tuple)):
        vals = [x for x in (_as_score(y) for y in v) if x is not None]
        return sum(vals) / len(vals) if vals else None
    if isinstance(v, str):
        # the judge's value arrives as "yes"/"no", a number, a list, or NaN depending on the MLflow version
        return {"yes": 1.0, "no": 0.0}.get(v.strip().lower())
    if v is None or (isinstance(v, float) and v != v):
        return None
    return float(v)


ground = {}
for _, row in rdf.iterrows():
    rat = ""
    for a in (row.get("assessments") or []):
        name = getattr(a, "name", None) or (a.get("assessment_name") or a.get("name") if isinstance(a, dict) else None)
        if "groundedness" in (name or ""):
            r_ = getattr(a, "rationale", None) or (a.get("rationale") if isinstance(a, dict) else None)
            rat = (rat + " | " if rat else "") + (r_ or "")[:2500]
    ground[_desc_of(row["request"])] = (_as_score(row.get("retrieval_groundedness/value")), rat)

# COMMAND ----------

judged = {(r.eval_id, r.contract_id): r.relevant for r in pairs.itertuples()}
pool_relevant = (retr[retr.variant == "tfidf_gte_rerank"].groupby("eval_id").relevant
                 .apply(lambda s_: int(s_.fillna(False).astype(bool).sum())).to_dict())
rows = []
for p in packages:
    r = store[p["package"]["description"]]
    b = r.get("brief") or {}
    cited_prec = [x["record_id"].split(":")[1] for x in b.get("precedents", [])]
    rel = []
    for cid in cited_prec:
        if (p["eval_id"], cid) not in judged:
            # a precedent the agent cited that was not in the 5b pool gets judged now, with the same judge and prompt
            judged[(p["eval_id"], cid)] = judge_relevance(p["package"], r["records"][f"contract:{cid}"])[0]
        rel.append(judged[(p["eval_id"], cid)])
    g, rat = ground.get(p["package"]["description"], (None, ""))
    rows.append({"eval_id": p["eval_id"], "kind": "package", **run_summary(r), "groundedness": g, "groundedness_rationale": rat,
                 "n_precedents_cited": len(cited_prec),
                 "precedent_precision": (sum(bool(x) for x in rel) / len(rel)) if rel else None,
                 "relevant_in_pool": pool_relevant.get(p["eval_id"], 0),
                 # an empty precedent list is right only when nothing in the re-ranked top 10 was judged relevant
                 "zero_precedents_right": (pool_relevant.get(p["eval_id"], 0) == 0) if not cited_prec else None,
                 "invalid_citations": ",".join((r.get("validation") or {}).get("invalid_citations", [])),
                 "forced_tool_names": ",".join(r.get("forced_tools", [])), "brief_text": r["text"],
                 "brief_json": json.dumps(r.get("brief")), "description": p["package"]["description"],
                 "source_contract_id": p["source_contract_id"]})
e2e = pd.DataFrame(rows)
calls_total = e2e.model_tool_calls + e2e.forced_tools
agg = {"briefs": len(e2e), "status": e2e.status.value_counts().to_dict(),
       "groundedness_mean": round(e2e.groundedness.mean(), 3), "groundedness_judged": int(e2e.groundedness.notna().sum()),
       "citation_validity_mean": round(e2e.citation_validity.mean(), 3),
       "briefs_with_invented_ids": int((e2e.n_invalid_citations > 0).sum()),
       "briefs_with_uncited_risk_removed": int(e2e["flags"].str.contains("uncited_risk").sum()),
       "briefs_with_timeline_corrected": int(e2e["flags"].str.contains("timeline_corrected").sum()),
       "runs_with_forced_tools": int((e2e.forced_tools > 0).sum()), "invalid_tool_calls": int(e2e.invalid_tool_calls.sum()),
       "json_first_try_valid": int(e2e.json_first_try.fillna(False).astype(bool).sum()),
       "tool_calls_mean": round(calls_total.mean(), 2), "tool_calls_max": int(calls_total.max()),
       "precedent_precision_mean": round(e2e.precedent_precision.mean(), 3),
       "precedents_cited_total": int(e2e.n_precedents_cited.sum()),
       "precedents_relevant_total": int(sum(round(p_ * n) for p_, n in zip(e2e.precedent_precision.fillna(0), e2e.n_precedents_cited))),
       "precedent_precision_pooled": round(sum(round(p_ * n) for p_, n in zip(e2e.precedent_precision.fillna(0), e2e.n_precedents_cited))
                                           / max(1, int(e2e.n_precedents_cited.sum())), 3),
       "briefs_with_zero_precedents": int((e2e.n_precedents_cited == 0).sum()),
       "zero_precedent_briefs_right": int(e2e.zero_precedents_right.fillna(False).astype(bool).sum()),
       "briefs_with_model_forecast": int(e2e.forecast_p50_days.notna().sum()),
       "briefs_with_peer_benchmark": int(e2e.peer_p50_days.notna().sum()),
       "briefs_with_forecast_added_by_code": int(e2e["flags"].str.contains("forecast_added").sum()),
       "briefs_with_timeline_text_replaced": int(e2e["flags"].str.contains("timeline_text_replaced").sum()),
       "risks_per_brief_mean": round(e2e.risks_kept.mean(), 2),
       "latency_p50_s": round(e2e.latency_s.median(), 1), "latency_p90_s": round(e2e.latency_s.quantile(0.9), 1),
       "dbu_per_brief_mean": round(e2e.dbu.mean(), 4)}
print(json.dumps(agg, indent=1))
display(e2e[["eval_id", "status", "model_tool_calls", "forced_tool_names", "n_citations", "citation_validity", "invalid_citations",
             "risks_kept", "precedents_kept", "precedent_precision", "relevant_in_pool", "zero_precedents_right",
             "forecast_p50_days", "peer_p50_days", "groundedness", "flags", "latency_s", "dbu"]])

# COMMAND ----------

# MAGIC %md
# MAGIC **Briefs the judge did not find fully grounded,** with its rationale, for reading:

# COMMAND ----------

for r in e2e[e2e.groundedness.fillna(1) < 1].itertuples():
    print(f"--- {r.eval_id} groundedness {r.groundedness}: {r.description}\n{r.brief_text[:1500]}\nJUDGE: {r.groundedness_rationale}\n")

# COMMAND ----------

# MAGIC %md
# MAGIC ### 5e. Guard cases
# MAGIC
# MAGIC **What:** the three guard cases through the full agent. Expected: each refused before any tool runs, with the right reason.
# MAGIC
# MAGIC **Why:** the planted instruction in g03 sits inside an otherwise real package description; refusing it is the guard's job, and if the guard missed it, the planner and writer prompts and the code validation are the next lines of defence (the brief could still only cite real records).

# COMMAND ----------

grows = []
for g in guard_cases:
    r = procurement_brief(g["package"])
    got = "injection" if "injection" in r["flags"] else ("out_of_scope" if "out_of_scope" in r["flags"] else r["status"])
    grows.append({"eval_id": g["eval_id"], "kind": "guard", "expected": g["expected"], "got": got, "status": r["status"],
                  "correct": got == g["expected"], "guard_reason": r["guard"]["reason"], "latency_s": r["latency_s"],
                  "model_tool_calls": r["n_tool_calls"], "dbu": r["dbu"], "description": g["package"]["description"],
                  "brief_text": r["text"]})
guard_df = pd.DataFrame(grows)
display(guard_df[["eval_id", "expected", "got", "correct", "guard_reason", "model_tool_calls", "latency_s"]])

# COMMAND ----------

# MAGIC %md
# MAGIC ### 5f. Timeline: model forecast vs peer group vs what actually happened
# MAGIC
# MAGIC **What:** each evaluation package was written from a real contract whose tender notice and signing dates are known. For the packages whose source contract is timed (an openly competed tender with a linked notice), the tools are called directly (no LLM) with the source notice's date as the planned notice date, in three variants of what the planner knows:
# MAGIC - **A, package only:** country, method, category; every notice-level value is a planning-time default (what the agent uses);
# MAGIC - **B, + project:** the project id as well (the task team always knows it), so the project's sector, age, size and earlier tenders are real;
# MAGIC - **C, + notice facts:** also the source notice's real advertising period, notice type and language (what `p07` scores once the notice is out).
# MAGIC
# MAGIC Compared with the peer-group P50 of `tender_benchmark` and the actual days (capped at 730 like the model's target): absolute error of each P50, and whether the actual fell inside each P10-P90 range.
# MAGIC
# MAGIC **Why:** the brief shows two numbers; this says which one to trust and how much the planning-time defaults cost. Caveat: the model (refit on its whole cohort before registration) and the benchmark table were both built on contracts that include most of these source contracts, so both are scored in-sample here and the comparison is between two in-sample estimates; `p07`'s held-out test (MAE 76 vs 88 days) is the out-of-sample evidence.

# COMMAND ----------

src_ids = ", ".join(f"'{p['source_contract_id']}'" for p in ev["packages"])
src_tl = spark.sql(f"""
    SELECT t.contract_id, CAST(t.tender_notice_date AS STRING) AS notice_date, t.days_notice_to_signing AS actual_days, t.is_timed,
           c.project_id, n.notice_type, n.notice_language,
           CASE WHEN datediff(n.submission_deadline, n.notice_date) >= 0 THEN datediff(n.submission_deadline, n.notice_date) END
             AS advertising_days
    FROM {GOLD}.tender_timelines t JOIN {SILVER}.contracts c USING (contract_id)
    LEFT JOIN {SILVER}.notices n ON n.notice_id = t.tender_notice_id
    WHERE t.contract_id IN ({src_ids})""").toPandas().set_index("contract_id")
w0, w1 = _forecaster()["window"]
trows = []
for p in ev["packages"]:
    cid = p["source_contract_id"]
    if cid not in src_tl.index or not bool(src_tl.is_timed[cid]):
        trows.append({"eval_id": p["id"], "timed": False})
        continue
    s_ = src_tl.loc[cid]
    base = {k: p[k] for k in ("country", "category", "method")} | {"planned_notice_date": s_.notice_date}
    # A = what the agent knows at planning time, B adds the project, C adds the real notice facts; the gaps show what
    # each input is worth
    variants = {"A": base, "B": base | {"project_id": s_.project_id},
                "C": base | {"project_id": s_.project_id, "notice_type": s_.notice_type, "notice_language": s_.notice_language,
                             **({"advertising_days": float(s_.advertising_days)} if pd.notna(s_.advertising_days) else {})}}
    row = {"eval_id": p["id"], "timed": True, "notice_date": s_.notice_date, "in_model_cohort": w0 <= s_.notice_date <= w1,
           # capped at 730 days, like the model's training target
           "actual_days": min(float(s_.actual_days), 730.0)}
    for name, pkg in variants.items():
        rec = forecast_timeline(pkg)["records"][0]
        row.update({f"{name}_p10": rec["p10_days"], f"{name}_p50": rec["p50_days"], f"{name}_p90": rec["p90_days"],
                    f"{name}_slow": rec["slow_probability"], f"{name}_id": rec["record_id"]})
    bm = tender_benchmark(p["method"], p["category"], p["country"])
    chosen = next((r for r in bm["records"] if r["chosen"]), None)
    row.update({"peer_level": chosen["level"] if chosen else None, "peer_p10": chosen["p10_days"] if chosen else None,
                "peer_p50": chosen["p50_days"] if chosen else None, "peer_p90": chosen["p90_days"] if chosen else None})
    trows.append(row)
tcmp = pd.DataFrame(trows)
timed = tcmp[tcmp.timed].copy()
summ = []
for name, lo, mid, hi in (("model A: package only", "A_p10", "A_p50", "A_p90"), ("model B: + project", "B_p10", "B_p50", "B_p90"),
                          ("model C: + notice facts", "C_p10", "C_p50", "C_p90"), ("peer group", "peer_p10", "peer_p50", "peer_p90")):
    ok = timed[mid].notna()
    err = (timed.loc[ok, mid] - timed.loc[ok, "actual_days"]).abs()
    summ.append({"timeline": name, "scored": int(ok.sum()), "mae_days": round(err.mean(), 1), "median_ae_days": round(err.median(), 1),
                 "inside_p10_p90": int(((timed.loc[ok, "actual_days"] >= timed.loc[ok, lo]) & (timed.loc[ok, "actual_days"] <= timed.loc[ok, hi])).sum()),
                 "closer_than_peer": int((err < (timed.loc[ok, "peer_p50"] - timed.loc[ok, "actual_days"]).abs()).sum()) if name != "peer group" else None})
timeline_summary = pd.DataFrame(summ)
print(f"{len(timed)} of {len(tcmp)} source contracts are timed; {int(timed.in_model_cohort.sum())} have their notice inside the "
      f"model's training cohort ({w0} .. {w1})")
display(timeline_summary)
display(timed[["eval_id", "notice_date", "in_model_cohort", "actual_days", "peer_level", "peer_p50", "A_p50", "B_p50", "C_p50",
               "A_p10", "A_p90", "A_slow"]])

# COMMAND ----------

# MAGIC %md
# MAGIC ### 5g. Save the results and the token ledger
# MAGIC
# MAGIC **What:** one row per evaluation case in `proc_gold.agent_eval_results`; the summary metrics logged to an MLflow run; the token ledger of this notebook run (the groundedness judge runs inside MLflow, so its tokens are estimated from the size of the evidence it read).

# COMMAND ----------

tl_cols = {"actual_days": "actual_days", "peer_p50": "peer_p50_at_notice", "A_p50": "model_p50_package_only",
           "B_p50": "model_p50_with_project", "C_p50": "model_p50_with_notice"}
e2e = e2e.merge(tcmp.reindex(columns=["eval_id", *tl_cols]).rename(columns=tl_cols), on="eval_id", how="left")
keep_cols = ["eval_id", "kind", "description", "source_contract_id", "status", "expected", "got", "correct", "guard_reason",
             "model_tool_calls", "forced_tool_names", "invalid_tool_calls", "json_first_try", "n_citations", "citation_validity",
             "invalid_citations", "risks_kept", "precedents_kept", "n_precedents_cited", "precedent_precision", "groundedness",
             "groundedness_rationale", "flags", "latency_s", "dbu", "brief_text", "brief_json", "relevant_in_pool",
             "zero_precedents_right", "forecast_p50_days", "peer_p50_days", *tl_cols.values()]
save = pd.concat([e2e, guard_df], ignore_index=True).reindex(columns=keep_cols)
# pandas NaN would not fit the typed schema below; turn every missing value into None first
save = save.astype(object).where(save.notna(), None)
save_schema = ("eval_id string, kind string, description string, source_contract_id string, status string, expected string, "
               "got string, correct boolean, guard_reason string, model_tool_calls double, forced_tool_names string, "
               "invalid_tool_calls double, json_first_try boolean, n_citations double, citation_validity double, "
               "invalid_citations string, risks_kept double, precedents_kept double, n_precedents_cited double, "
               "precedent_precision double, groundedness double, groundedness_rationale string, flags string, latency_s double, "
               "dbu double, brief_text string, brief_json string, relevant_in_pool double, zero_precedents_right boolean, "
               "forecast_p50_days double, peer_p50_days double, actual_days double, peer_p50_at_notice double, "
               "model_p50_package_only double, model_p50_with_project double, model_p50_with_notice double")
num_cols = [c.split()[0] for c in save_schema.split(", ") if c.split()[1] == "double"]
for c in num_cols:
    save[c] = [None if v is None else float(v) for v in save[c]]
for c in ("correct", "json_first_try", "zero_precedents_right"):
    save[c] = [None if v is None else bool(v) for v in save[c]]
save_sdf = (spark.createDataFrame(save, schema=save_schema)
            .withColumn("planner_model", F.lit(PLANNER_MODEL)).withColumn("judge_model", F.lit(JUDGE_MODEL))
            .withColumn("rerank", F.lit(RERANK)).withColumn("evaluated_at", F.current_timestamp()))
n_saved = publish_table(
    save_sdf, f"{GOLD}.agent_eval_results",
    "Evaluation of the procurement agent (p08): one row per evaluation package or guard case, with the brief, code checks and "
    "the groundedness judge. Grain: one row per eval_id (latest run).",
    {"eval_id": "PK. e01-e20 packages, g01-g03 guard cases", "kind": "package or guard", "description": "Package description given",
     "source_contract_id": "Real contract the package was written from (its project is held out)", "status": "Agent status",
     "expected": "Guard cases: expected refusal reason", "got": "Guard cases: observed outcome", "correct": "Guard cases: got = expected",
     "guard_reason": "Input guard's reason", "model_tool_calls": "Tool calls made by the planner model",
     "forced_tool_names": "Core tools the code had to add", "invalid_tool_calls": "Tool calls rejected by the argument check",
     "json_first_try": "Writer reply valid on the first try", "n_citations": "Citations in the brief before cleaning",
     "citation_validity": "Share of citations that match a record returned by a tool", "invalid_citations": "Ids dropped",
     "risks_kept": "Risks left after validation", "precedents_kept": "Precedents left after validation",
     "n_precedents_cited": "Precedents cited in the final brief", "precedent_precision": "Share of cited precedents judged relevant",
     "groundedness": "RetrievalGroundedness judge (1 = supported by the gathered records)",
     "groundedness_rationale": "Judge rationale (truncated)", "flags": "Validation and guard flags",
     "latency_s": "Wall time of the run (s)", "dbu": "DBU of the run's planner, writer, guard and embedding calls",
     "brief_text": "Rendered brief", "brief_json": "Validated brief JSON",
     "relevant_in_pool": "Judged-relevant contracts among the package's top 10 re-ranked candidates (5b)",
     "zero_precedents_right": "Brief listed no precedent and none of the top 10 candidates was relevant (null if it listed some)",
     "forecast_p50_days": "Model forecast P50 in the brief (notice date = run date)", "peer_p50_days": "Peer-group P50 in the brief",
     "actual_days": "Source contract: actual tender notice -> signing days (capped at 730; null if not timed)",
     "peer_p50_at_notice": "Peer-group P50 for the source contract (5f)",
     "model_p50_package_only": "Model P50 at the source notice date, planning-time defaults (5f variant A)",
     "model_p50_with_project": "Model P50 with the project id as well (5f variant B)",
     "model_p50_with_notice": "Model P50 with the real notice facts as well (5f variant C)",
     "planner_model": "Planner and writer endpoint",
     "judge_model": "Judge endpoint", "rerank": "GTE re-ranking of contract search on", "evaluated_at": "Evaluation time (UTC)"},
    primary_key=["eval_id"])
with mlflow.start_run(run_name="procurement_agent_eval_summary"):
    mlflow.log_metrics({k: float(v) for k, v in agg.items() if isinstance(v, (int, float)) and v == v})
    mlflow.log_metrics({"guard_correct": float(guard_df.correct.mean()),
                        "retrieval_p_at_5_tfidf": float(summary_retr.loc["tfidf", "mean"]),
                        "retrieval_p_at_5_rerank": float(summary_retr.loc["tfidf_gte_rerank", "mean"])})
    mlflow.log_metrics({f"timeline_mae_{r.timeline.split(':')[0].replace(' ', '_')}": float(r.mae_days)
                        for r in timeline_summary.itertuples() if r.mae_days == r.mae_days})
print(f"saved {n_saved} rows to {GOLD}.agent_eval_results")

# COMMAND ----------

led = ledger_frame()
# the judge runs inside MLflow, so its tokens are not metered here; estimate ~4 characters per token and 400 output
# tokens per call
judge_in = int(sum(len(_evidence_block(x)) for r in store.values() for x in (r.get("records") or {}).values()) / 4)
led = pd.concat([led, pd.DataFrame([{"model": "gpt-oss-120b groundedness judge (estimated)", "calls": len(store),
                                     "prompt_tokens": judge_in, "completion_tokens": 400 * len(store),
                                     "dbu": round(dbu(JUDGE_MODEL, judge_in, 400 * len(store)), 3)}])], ignore_index=True)
print(led.to_string(index=False))
print(f"total {led.dbu.sum():.2f} DBU in this run")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. What the evaluation says, and its limits
# MAGIC
# MAGIC Numbers from the run shown above (20 packages, 3 guard cases, same judge `gpt-oss-120b`; LLM outputs vary from run to run). "Phase 2" is the previous version of this agent on the same cases: always five precedents, timeline from the peer group only.
# MAGIC
# MAGIC | Measure | Phase 2 | This version | How measured |
# MAGIC |---|---|---|---|
# MAGIC | Similar contracts, precision@5 (ranking only) | 0.63 TF-IDF, 0.75 re-ranked | 0.64 TF-IDF, 0.75 re-ranked | judge on 179 top-5 pairs; source project held out |
# MAGIC | Precedent rule on the judged candidates | none (top 5) | 0.82 precision vs 0.75 for the top 5; recall 0.83; leave-one-package-out 0.80 | 200 judged re-ranked candidates (5b) |
# MAGIC | Precedents cited in the briefs, judged relevant | 0.74 (always 5 per brief) | **0.82** (76 of 93; 3 to 5 per brief, 0 for e18) | same judge |
# MAGIC | Briefs with no precedent | 0 (e18 listed 5 unrelated contracts) | 1 (e18), and right: none of its 10 candidates was relevant | 5d vs 5b |
# MAGIC | Citation validity | 1.00 | 0.995 (one malformed id in 1 brief, dropped by the code) | code |
# MAGIC | Groundedness | 16 of 20 | **19 of 20** (the one "no" is a harness artefact, below) | `RetrievalGroundedness` |
# MAGIC | Briefs showing a model forecast and a peer-group range | 0 | 20 of 20, both cited; 0 numbers corrected by the code | code |
# MAGIC | Tool use | 3.7 calls per brief, 0 forced | 4.25 calls per brief (one more tool), 0 forced, 0 invalid | code |
# MAGIC | Latency per brief | median 14.9 s | median 23.1 s (13.6 s in the run before, same code path) | wall time, 2 agents in parallel |
# MAGIC | Guard cases | 3 of 3 | 3 of 3 | code |
# MAGIC
# MAGIC **Timeline against what actually happened (5f, 20 source contracts, all timed):** mean absolute error of the P50 in days.
# MAGIC
# MAGIC | Timeline | MAE | Median AE | Actual inside P10-P90 | Closer than the peer P50 |
# MAGIC |---|---|---|---|---|
# MAGIC | Peer group (`tender_benchmark`) | 85 | 52 | 16 of 20 | - |
# MAGIC | Model, package only (what the agent uses) | 91 | 62 | 16 of 20 | 11 of 20 |
# MAGIC | Model, + project id | 80 | 49 | 16 of 20 | 10 of 20 |
# MAGIC | Model, + the real notice facts | **60** | **34** | 18 of 20 | 14 of 20 |
# MAGIC
# MAGIC **Reading the timeline result:** with only country, method and category the model is no better than the peer group (91 vs 85 days on 20 tenders); its edge comes from facts the planner does not have yet. Giving the project id (always known to a task team) brings it level or slightly ahead (80); the real advertising period, notice type and language bring it to 60. So the brief shows both numbers, the forecast with its assumptions, and the package's optional fields (`project_id`, `advertising_days`, `planned_notice_date`) are worth filling in. With 20 tenders (17 of them inside the training cohort of both the model and the benchmark table) these differences are indicative only; `p07`'s held-out test (MAE 76 vs 88 days) is the out-of-sample evidence.
# MAGIC
# MAGIC **Revisions made during development:** in an earlier run the model-choice rule broke a tie on latency and picked Llama 3.3 (faster on that day, twice the cost); the rule now breaks ties on cost first. In the next run, three briefs failed groundedness because the writer had been asked to say whether the forecast was above or below the peer group and got the direction wrong ("129 days, faster than the peer median of 100"); the difference is now computed in code and a summary that compares the medians in words is rewritten (`timeline_text_replaced`, 1 brief here). The judge also could not check "no close precedent found" because an empty search leaves no record; empty searches are now logged as *tool outcome* documents in the evidence span.
# MAGIC
# MAGIC **The one "not grounded" brief (e11)** is a harness artefact: the judge read the held-out project id and the model argument from the agent span's inputs as part of the claim. The id is no longer in the judged inputs, but it still reaches the traced `procurement_brief` call; passing it through a context variable instead would remove it.
# MAGIC
# MAGIC **Model choice:** Qwen 3.5 and Llama 3.3 both called the tools correctly on the three trial packages; Qwen's briefs cost about half as much per brief, and Llama made one invalid citation in one run. Qwen plans and writes; Llama stays the input guard, so the two steps that read user text are different model families.
# MAGIC
# MAGIC **Limitations:**
# MAGIC - **Small evaluation.** 20 packages written during the build from real contracts; one LLM judge for relevance and groundedness, checked against 30 agent reference labels (90% agreement). The project's final evaluation labels come from the three-tier escalation in p15 (code checks, a panel of three LLM judges, an AI adjudicator that records evidence). The judge is not deterministic: the best precedent rule on the judged pairs was the same (0.68 / 0.08) in two runs and slightly stricter (0.72 / 0.08) in one. A rate here has an error bar of 10-20 points.
# MAGIC - **The precedent rule is a modest filter.** It removes the clearly unrelated (speedboats) and lifts precision from about 0.75 to 0.82, but packages whose candidates are mixed still list some weak ones (e06 plumbing training: 1 of 5 relevant; e16 e-procurement system: 1 of 5). A relevance classifier trained on more judged pairs would do better than two thresholds.
# MAGIC - **Planning-time forecast.** The forecast uses medians for the notice facts and, without a project id, no project facts; it says so in its assumptions. The model was refit on its whole cohort, so most evaluation tenders are in-sample for it, as they are for the peer table.
# MAGIC - **Language.** Contract descriptions are in English, French, Spanish and Portuguese; TF-IDF matches words, and GTE-large is an English model. The French package (e20) found French precedents, but a cross-language match relies on shared words such as place names and acronyms; the TF-IDF part of the precedent rule makes this stricter.
# MAGIC - **Lessons corpus.** 4,495 passages from 300 completion reports plus 16,623 appraisal passages of 397 projects; passages are retrieved by meaning, so a passage about a related but different problem can be cited for a risk.
# MAGIC - **Win rates** count only award notices that name the firm; contracts without a published award notice are missing from the denominator.
# MAGIC - **Shared rate limits.** The embedding and chat endpoints are pay-per-token with workspace-wide limits; median latency moved between 13.6 s and 23.1 s across runs of the same code.
