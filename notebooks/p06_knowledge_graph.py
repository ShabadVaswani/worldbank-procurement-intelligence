# Databricks notebook source
# MAGIC %md
# MAGIC # p06_knowledge_graph — the procurement knowledge graph as Delta node and edge tables
# MAGIC
# MAGIC Connects the structured procurement model to the outcome project's documents and risk scores in one typed graph:

# COMMAND ----------

# MAGIC %md-sandbox
# MAGIC <img src="data:image/png;base64,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" alt="kg_topology diagram" style="max-width:100%; width:1213px"/>
# MAGIC

# COMMAND ----------

# MAGIC %md
# MAGIC | Table | Grain | Key |
# MAGIC |---|---|---|
# MAGIC | `proc_gold.kg_nodes` | one node: project, contract, supplier_entity, country, notice, document_chunk | `node_id` (`<type>:<natural key>`) |
# MAGIC | `proc_gold.kg_edges` | one typed, directed relationship | `src_id, edge_type, dst_id` |
# MAGIC
# MAGIC Every node id is `<type>:<key of the source table>`, so any node can be traced back to its silver row, and any document chunk to its passage in `silver.rag_chunks` (text and embedding stay there, joined by `chunk_id`).

# COMMAND ----------

# MAGIC %md
# MAGIC ## Why a graph in the lakehouse, not a separate graph database
# MAGIC
# MAGIC - **One copy, one governance model.** Nodes and edges are Delta tables in Unity Catalog: the same permissions, lineage, time travel and audit as the silver tables they are built from. A separate graph store (Neo4j, Neptune) would need a sync pipeline, its own access control and its own backups, and would drift from the source.
# MAGIC - **The questions are batch and few-hop.** Analysts and the phase-2 agent ask 2-4 hop questions over a few million edges ("suppliers of high-risk projects and their other contracts"). Spark joins and GraphFrames motifs answer these in seconds; the low-latency deep traversals a graph database is built for are not needed.
# MAGIC - **It feeds models and retrieval directly.** Graph features (supplier history, co-bidding, project risk) join straight into the phase-2 training table, and the agent can expand a retrieved document chunk to its project, contracts and suppliers with SQL.
# MAGIC - **Upgrade path.** If interactive deep traversal becomes a requirement, the same node/edge tables can be exported to a graph database as a read replica, with Delta remaining the system of record.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Key design decisions
# MAGIC
# MAGIC | Decision | Rationale | Evidence |
# MAGIC |---|---|---|
# MAGIC | Supplier nodes are resolved `supplier_entities` from `p04`; notices and contracts keep their own grain | An id-level graph would split a firm's history | Ernst & Young India alone holds many ids |
# MAGIC | Document chunks from the outcome project's `silver.rag_chunks` (453 projects), linked by `project_id`, become nodes only for projects that appear in the procurement data | Only chunks connected to procurement records belong in the graph | The printed count shows the overlap |
# MAGIC | One node table: common columns (`node_id`, `node_type`, `name`) plus a `properties` map of strings; exact numeric types stay one join away in silver | Six node types must share one queryable table | A wide table would be mostly empty; one table per type would make generic traversals awkward |
# MAGIC | Demo questions written as DataFrame joins; one repeated as a GraphFrames motif when the library is available | Joins work on any runtime; the motif shows both styles give the same answer | The GraphFrames Python package ships with the ML runtime (checked in `p00`); loading of its JVM library is tested in the notebook |
# MAGIC
# MAGIC Full reasoning: docs/decision_log.md

# COMMAND ----------

# MAGIC %run ./proc_common

# COMMAND ----------

import json

from pyspark.sql import DataFrame, Window

NODES, EDGES = f"{GOLD}.kg_nodes", f"{GOLD}.kg_edges"


def props(*cols: str):
    """String map of the given columns, dropping nulls."""
    pairs = [x for c in cols for x in (F.lit(c), F.col(c).cast("string"))]
    # a map<string,string> lets six node types share one table; nulls are dropped so absent properties stay absent
    return F.map_filter(F.create_map(*pairs), lambda k, v: v.isNotNull())


def node(df: DataFrame, node_type: str, key: str, name, *prop_cols: str) -> DataFrame:
    return df.select(F.concat(F.lit(f"{node_type}:"), F.col(key)).alias("node_id"), F.lit(node_type).alias("node_type"),
                     name.alias("name"), props(*prop_cols).alias("properties"))


def edge(df: DataFrame, src_type: str, src_key: str, edge_type: str, dst_type: str, dst_key: str, *prop_cols: str) -> DataFrame:
    # an edge needs both ends; e.g. regional-programme projects have no country, so they get no IN_COUNTRY edge
    return (df.filter(F.col(src_key).isNotNull() & F.col(dst_key).isNotNull())
            .select(F.concat(F.lit(f"{src_type}:"), F.col(src_key)).alias("src_id"), F.lit(edge_type).alias("edge_type"),
                    F.concat(F.lit(f"{dst_type}:"), F.col(dst_key)).alias("dst_id"), props(*prop_cols).alias("properties")))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Nodes
# MAGIC
# MAGIC **What:** one DataFrame per node type with its display name and key properties, unioned into `kg_nodes`.
# MAGIC
# MAGIC **Why:** projects carry the outcome-model risk band, contracts their method/category/amount, supplier entities their activity, chunks their document type and section — the attributes the demo questions filter on.

# COMMAND ----------

S = {t: spark.table(f"{SILVER}.{t}") for t in
     ["dim_project", "dim_country", "contracts", "supplier_entities", "supplier_entity_map", "contract_suppliers",
      "notices", "notice_bidders", "notice_contract_links"]}
# chunks of projects that appear in the procurement data; the others have no procurement node to describe
all_chunks = spark.table(RAG_CHUNKS).select("chunk_id", "project_id", "doc_id", "doc_type", "section", "chunk_index")
chunks = all_chunks.join(S["dim_project"].select("project_id"), "project_id", "left_semi")
print(f"document chunks: {chunks.count():,} of {all_chunks.count():,} kept "
      f"({chunks.select('project_id').distinct().count()} of {all_chunks.select('project_id').distinct().count()} "
      f"indexed projects have procurement data)")
# a short display name only; the full description stays in silver.contracts
contract_view = S["contracts"].withColumn("description_short", F.substring("contract_description", 1, 200))
nodes = (node(S["dim_project"], "project", "project_id", F.col("project_name"),
              "region", "major_sector", "approval_fy", "status", "outcome_risk_band", "outcome_risk_of_failure", "country_code")
         .unionByName(node(S["dim_country"], "country", "country_code", F.col("country_name"), "kind", "has_country_indicators"))
         .unionByName(node(contract_view, "contract", "contract_id", F.col("description_short"),
                           "procurement_method_name", "procurement_category_code", "review_type", "contract_amount_usd",
                           "signing_date", "is_joint_venture", "borrower_reference"))
         .unionByName(node(S["supplier_entities"], "supplier_entity", "supplier_entity_id", F.col("canonical_name"),
                           "country_code", "n_supplier_ids", "n_contracts", "value_won_usd", "n_times_not_awarded",
                           "is_individual_consultant"))
         .unionByName(node(S["notices"], "notice", "notice_id", F.col("bid_description"),
                           "notice_type", "notice_date", "procurement_method_name", "procurement_category_code",
                           "bid_reference", "submission_deadline"))
         .unionByName(node(chunks, "document_chunk", "chunk_id", F.concat_ws(" / ", "doc_type", "section"),
                           "project_id", "doc_id", "doc_type", "section", "chunk_index")))
n_nodes = publish_table(
    nodes, NODES,
    "Knowledge-graph nodes. Grain: one row per node. node_id = '<type>:<natural key>' (project_id, country_code, "
    "contract_id, supplier_entity_id, notice_id, chunk_id).",
    {"node_id": "PK. '<node_type>:<key in the source table>'",
     "node_type": "project, country, contract, supplier_entity, notice or document_chunk",
     "name": "Display name (project name, country, contract description, canonical supplier name, notice description, doc type / section)",
     "properties": "Type-specific attributes as strings"},
    primary_key=["node_id"])
display(spark.table(NODES).groupBy("node_type").count().orderBy(F.desc("count")))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Edges
# MAGIC
# MAGIC **What:** the relationships of the diagram, each from its bridge or foreign key:
# MAGIC
# MAGIC | Edge | From | Source |
# MAGIC |---|---|---|
# MAGIC | contract `PART_OF` project | contracts.project_id | FK |
# MAGIC | contract `AWARDED_TO` supplier_entity | contract_suppliers + supplier_entity_map | bridge (one edge per entity, joint ventures give several) |
# MAGIC | notice `ADVERTISES` contract | notice_contract_links, role tender | p05 (property: match tier) |
# MAGIC | notice `ANNOUNCES` contract | notice_contract_links, role award | p05 |
# MAGIC | notice `FOR_PROJECT` project | notices.project_id | FK |
# MAGIC | supplier_entity `BID_ON` notice | notice_bidders + supplier_entity_map | award notice HTML (property: role) |
# MAGIC | project `IN_COUNTRY` country | dim_project.country_code | FK |
# MAGIC | supplier_entity `REGISTERED_IN` country | supplier_entities.country_code | FK |
# MAGIC | document_chunk `DESCRIBES` project | silver.rag_chunks.project_id | outcome project |
# MAGIC
# MAGIC **Why:** edges are derived only from keys that the earlier notebooks checked for orphans, so the graph inherits their integrity; edges whose end node is missing are counted below (expected 0).

# COMMAND ----------

# distinct: two ids of the same resolved firm on one joint venture would otherwise give a duplicate edge
awarded_to = (S["contract_suppliers"].join(S["supplier_entity_map"], "supplier_id")
              .select("contract_id", "supplier_entity_id").distinct())
# same rule as in p03, now at entity level: two ids of one firm on a notice keep the strongest role
bid_on = (S["notice_bidders"].join(S["supplier_entity_map"], "supplier_id")
          .withColumn("_rank", F.when(F.col("role") == "awarded", 0).when(F.col("role") == "evaluated", 1).otherwise(2))
          .withColumn("_rn", F.row_number().over(Window.partitionBy("supplier_entity_id", "notice_id").orderBy("_rank")))
          .filter("_rn = 1").select("supplier_entity_id", "notice_id", "role"))
links = S["notice_contract_links"]
edges = (edge(S["contracts"], "contract", "contract_id", "PART_OF", "project", "project_id")
         .unionByName(edge(awarded_to, "contract", "contract_id", "AWARDED_TO", "supplier_entity", "supplier_entity_id"))
         .unionByName(edge(links.filter("link_role = 'tender'"), "notice", "notice_id", "ADVERTISES", "contract", "contract_id",
                           "match_tier", "notice_before_signing", "days_notice_to_signing"))
         .unionByName(edge(links.filter("link_role = 'award'"), "notice", "notice_id", "ANNOUNCES", "contract", "contract_id",
                           "match_tier", "supplier_confirmed"))
         .unionByName(edge(S["notices"], "notice", "notice_id", "FOR_PROJECT", "project", "project_id"))
         .unionByName(edge(bid_on, "supplier_entity", "supplier_entity_id", "BID_ON", "notice", "notice_id", "role"))
         .unionByName(edge(S["dim_project"], "project", "project_id", "IN_COUNTRY", "country", "country_code"))
         .unionByName(edge(S["supplier_entities"], "supplier_entity", "supplier_entity_id", "REGISTERED_IN", "country", "country_code"))
         .unionByName(edge(chunks, "document_chunk", "chunk_id", "DESCRIBES", "project", "project_id", "doc_type", "section")))
n_edges = publish_table(
    edges, EDGES,
    "Knowledge-graph edges. Grain: one row per (src_id, edge_type, dst_id); directed and typed.",
    {"src_id": "PK, FK kg_nodes", "edge_type": "PK. PART_OF, AWARDED_TO, ADVERTISES, ANNOUNCES, FOR_PROJECT, BID_ON, "
     "IN_COUNTRY, REGISTERED_IN, DESCRIBES", "dst_id": "PK, FK kg_nodes", "properties": "Edge attributes as strings"},
    primary_key=["src_id", "edge_type", "dst_id"])
add_foreign_key(EDGES, ["src_id"], NODES, ["node_id"])
add_foreign_key(EDGES, ["dst_id"], NODES, ["node_id"])
display(spark.table(EDGES).groupBy("edge_type").count().orderBy(F.desc("count")))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Integrity
# MAGIC
# MAGIC **What:** duplicate keys and dangling edges (an end that is not a node).
# MAGIC
# MAGIC **Why:** a dangling edge would make traversals silently lose paths.

# COMMAND ----------

N, E = spark.table(NODES), spark.table(EDGES)
display(dq_report([
    (NODES, "duplicate node_id", duplicate_keys(N, ["node_id"]), "== 0"),
    (EDGES, "duplicate edge key", duplicate_keys(E, ["src_id", "edge_type", "dst_id"]), "== 0"),
    (EDGES, "edges with unknown src_id", orphan_count(E, "src_id", N, "node_id"), "== 0"),
    (EDGES, "edges with unknown dst_id", orphan_count(E, "dst_id", N, "node_id"), "== 0"),
    (NODES, "nodes", N.count(), "info"), (EDGES, "edges", E.count(), "info"),
]))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Question 1 — suppliers of civil works in high-risk projects, and their other contracts
# MAGIC
# MAGIC **What:** path `supplier_entity <-AWARDED_TO- contract -PART_OF-> project` where the project is flagged **High** risk by the outcome model and the contract is civil works; then, for each such supplier, all its other contracts and projects.
# MAGIC
# MAGIC **Why:** a supervisor of a risky project wants to know whether its contractors are stretched across many other contracts (capacity risk) or concentrated in other risky projects.

# COMMAND ----------

def nodes_of(node_type: str) -> DataFrame:
    return N.filter(F.col("node_type") == node_type)


def edges_of(edge_type: str) -> DataFrame:
    return E.filter(F.col("edge_type") == edge_type).select("src_id", "dst_id")


# the risk band comes from the outcome project's model (gold.active_project_scores), copied into dim_project
high_risk = nodes_of("project").filter(F.col("properties")["outcome_risk_band"] == "High").select(F.col("node_id").alias("project"))
cw = nodes_of("contract").filter(F.col("properties")["procurement_category_code"] == "CW").select(F.col("node_id").alias("contract"))
part_of = edges_of("PART_OF").toDF("contract", "project")
awarded = edges_of("AWARDED_TO").toDF("contract", "supplier")
# grain here is contract x supplier (joint ventures give several rows), hence countDistinct below
risky_cw = (cw.join(part_of, "contract").join(high_risk, "project").join(awarded, "contract"))
all_work = awarded.join(part_of, "contract").join(nodes_of("project").select(
    F.col("node_id").alias("project"), F.col("properties")["outcome_risk_band"].alias("band")), "project")
q1 = (risky_cw.groupBy("supplier").agg(F.countDistinct("contract").alias("high_risk_cw_contracts"),
                                       F.countDistinct("project").alias("high_risk_projects"))
      .join(all_work.groupBy("supplier").agg(F.countDistinct("contract").alias("all_contracts"),
                                             F.countDistinct("project").alias("all_projects"),
                                             F.countDistinct(F.when(F.col("band") == "High", F.col("project"))).alias("all_high_risk_projects")),
            "supplier")
      .join(nodes_of("supplier_entity").select(F.col("node_id").alias("supplier"), F.col("name").alias("supplier_name"),
                                                F.col("properties")["country_code"].alias("country")), "supplier")
      .withColumn("other_contracts", F.col("all_contracts") - F.col("high_risk_cw_contracts"))
      .orderBy(F.desc("high_risk_cw_contracts"), F.desc("other_contracts")))
print(f"suppliers with civil-works contracts in High-risk projects: {q1.count():,}")
display(q1.select("supplier_name", "country", "high_risk_cw_contracts", "high_risk_projects", "other_contracts",
                  "all_projects", "all_high_risk_projects").limit(10))

# COMMAND ----------

# MAGIC %md
# MAGIC **What:** the same path as a GraphFrames motif, if the GraphFrames library loads on this cluster.
# MAGIC
# MAGIC **Why:** shows the declarative graph-pattern style on the same tables; the count must equal the join version.

# COMMAND ----------

try:
    from graphframes import GraphFrame
    # sub-graph with the two edge types of the pattern: a motif over all edges would expand every pair of
    # out-edges of every node (suppliers have thousands of BID_ON edges)
    sub_edges = E.filter(F.col("edge_type").isin("PART_OF", "AWARDED_TO"))
    g = GraphFrame(N.withColumnRenamed("node_id", "id"),
                   sub_edges.withColumnRenamed("src_id", "src").withColumnRenamed("dst_id", "dst"))
    motif = (g.find("(c)-[e1]->(p); (c)-[e2]->(s)")
             .filter("e1.edge_type = 'PART_OF' AND e2.edge_type = 'AWARDED_TO'")
             .filter("p.properties['outcome_risk_band'] = 'High' AND c.properties['procurement_category_code'] = 'CW'"))
    motif_suppliers = motif.select("s.id").distinct().count()
    print(f"GraphFrames motif: {motif_suppliers:,} suppliers (join version: {q1.count():,})")
    GRAPHFRAMES = True
except Exception as exc:  # the JVM package is not on every runtime
    print("GraphFrames not usable on this cluster:", type(exc).__name__, str(exc)[:200])
    GRAPHFRAMES = False

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Question 2 — a new road tender in Kenya: similar past contracts and what the project documents say
# MAGIC
# MAGIC **What:** past civil-works contracts in Kenya whose description mentions roads, with their project; then, for those projects that have documents in the outcome project's index, the chunks that mention procurement, contractors, bidding, delays or implementation arrangements most often (`contract <-` `-PART_OF-> project <-DESCRIBES- document_chunk`).
# MAGIC
# MAGIC **Why:** this is the retrieval path the phase-2 assistant will use: structured precedent (amounts, methods, durations) plus the narrative evidence from the same projects. Keyword matching stands in for semantic search here (no model calls in this phase).

# COMMAND ----------

COUNTRY, KEYWORD = "KE", "road"
EVIDENCE_TERMS = "procurement|contractor|bidding|delay|implementation arrangement"
# the country comes from the project node (IN_COUNTRY), so the path is contract -> project -> country
in_country = edges_of("IN_COUNTRY").toDF("project", "country").filter(F.col("country") == f"country:{COUNTRY}")
road_contracts = (nodes_of("contract")
                  .filter((F.col("properties")["procurement_category_code"] == "CW") & F.lower("name").contains(KEYWORD))
                  .select(F.col("node_id").alias("contract"), F.col("name").alias("description"),
                          F.col("properties")["contract_amount_usd"].cast("double").alias("amount_usd"),
                          F.col("properties")["procurement_method_name"].alias("method"),
                          F.col("properties")["signing_date"].alias("signed"))
                  .join(part_of, "contract").join(in_country, "project"))
# prefix the key so it joins on graph node ids
timeline = spark.table(f"{GOLD}.tender_timelines").select(F.concat(F.lit("contract:"), "contract_id").alias("contract"),
                                                           "days_notice_to_signing", "n_tender_notices")
precedents = road_contracts.join(timeline, "contract", "left")
print(f"past road works contracts in {COUNTRY}: {precedents.count():,}; timed: {precedents.filter('days_notice_to_signing IS NOT NULL').count():,}; "
      f"median days notice->signing: {precedents.agg(F.expr('percentile_approx(days_notice_to_signing, 0.5)')).first()[0]}")
display(precedents.orderBy(F.desc("amount_usd")).select("project", "description", "amount_usd", "method", "signed",
                                                         "days_notice_to_signing").limit(8))
describes = edges_of("DESCRIBES").toDF("chunk", "project")
evidence = (precedents.select("project").distinct().join(describes, "project")
            .join(spark.table(RAG_CHUNKS).select(F.concat(F.lit("document_chunk:"), "chunk_id").alias("chunk"),
                                                 "doc_type", "section", "chunk_text"), "chunk")
            # counts every occurrence, not just presence, so chunks that discuss procurement at length rank first
            .withColumn("keyword_hits", F.size(F.expr(f"regexp_extract_all(lower(chunk_text), '{EVIDENCE_TERMS}', 0)")))
            .filter("keyword_hits > 0")
            .withColumn("excerpt", F.substring("chunk_text", 1, 240)))
print(f"projects with documents: {evidence.select('project').distinct().count()} | matching chunks: {evidence.count():,}")
display(evidence.withColumn("rn", F.row_number().over(Window.partitionBy("project").orderBy(F.desc("keyword_hits"), "chunk")))
        .filter("rn <= 3").select("project", "doc_type", "section", "keyword_hits", "excerpt").limit(9))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Question 3 — who keeps bidding against whom?
# MAGIC
# MAGIC **What:** pairs of supplier entities named together in many award notices (`supplier -BID_ON-> notice <-BID_ON- supplier`), with how often each of them won.
# MAGIC
# MAGIC **Why:** repeated co-bidding where the same firm always loses is a classic red flag for cover bidding or bid rotation. This is a screening signal for phase 2, not a finding: frequent co-bidding is also what a small, specialised market looks like.

# COMMAND ----------

bids = (E.filter("edge_type = 'BID_ON'")
        .select(F.col("src_id").alias("supplier"), F.col("dst_id").alias("notice"), F.col("properties")["role"].alias("role")))
pairs = (bids.alias("a").join(bids.alias("b"), "notice")
         # "<" keeps each unordered pair once and drops self-pairs
         .filter(F.col("a.supplier") < F.col("b.supplier"))
         .groupBy(F.col("a.supplier").alias("supplier_a"), F.col("b.supplier").alias("supplier_b"))
         .agg(F.count("*").alias("shared_notices"),
              F.sum((F.col("a.role") == "awarded").cast("int")).alias("a_won"),
              F.sum((F.col("b.role") == "awarded").cast("int")).alias("b_won"))
         # a screening cut-off, not a statistical test: it keeps only pairs that met often enough to be worth a look
         .filter("shared_notices >= 10"))
names = nodes_of("supplier_entity").select(F.col("node_id"), F.col("name"), F.col("properties")["country_code"].alias("country"))
q3 = (pairs.join(names.toDF("supplier_a", "name_a", "country_a"), "supplier_a")
      .join(names.toDF("supplier_b", "name_b", "country_b"), "supplier_b")
      .withColumn("one_side_never_wins", (F.col("a_won") == 0) | (F.col("b_won") == 0)))
print(f"supplier pairs named together in >= 10 award notices: {q3.count():,}; of which one side never won: "
      f"{q3.filter('one_side_never_wins').count():,}")
display(q3.orderBy(F.desc("shared_notices")).select("name_a", "name_b", "country_a", "shared_notices", "a_won", "b_won").limit(10))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. Question 4 — supplier entities winning across many borrower countries
# MAGIC
# MAGIC **What:** `supplier_entity <-AWARDED_TO- contract -PART_OF-> project -IN_COUNTRY-> country`, counting distinct borrower countries per supplier entity.
# MAGIC
# MAGIC **Why:** multi-country firms are where entity resolution matters most (one firm, many registrations) and where cross-country lessons (performance in one country) can inform another. The supplier's own registration country is shown for contrast.

# COMMAND ----------

q4 = (awarded.join(part_of, "contract").join(edges_of("IN_COUNTRY").toDF("project", "country"), "project")
      .groupBy("supplier").agg(F.countDistinct("country").alias("borrower_countries"),
                               F.countDistinct("contract").alias("contracts"))
      .join(nodes_of("supplier_entity").select(F.col("node_id").alias("supplier"), F.col("name").alias("supplier_name"),
                                               F.col("properties")["country_code"].alias("registered_in"),
                                               F.col("properties")["n_supplier_ids"].alias("supplier_ids")), "supplier")
      # anonymised individuals all share this name; they are not one firm
      .filter(~F.col("supplier_name").isin("INDIVIDUAL CONSULTANT")))
print(f"supplier entities with contracts in 10+ borrower countries: {q4.filter('borrower_countries >= 10').count():,}")
display(q4.orderBy(F.desc("borrower_countries"), F.desc("contracts")).limit(10))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Run summary
# MAGIC
# MAGIC **What:** node and edge counts by type and the headline answers.
# MAGIC
# MAGIC **Why:** a job run shows them without opening the notebook.

# COMMAND ----------

summary = {"nodes": n_nodes, "edges": n_edges,
           "nodes_by_type": {r["node_type"]: r["count"] for r in N.groupBy("node_type").count().collect()},
           "edges_by_type": {r["edge_type"]: r["count"] for r in E.groupBy("edge_type").count().collect()},
           "q1_suppliers": q1.count(), "q3_pairs": q3.count(), "graphframes": GRAPHFRAMES}
print(summary)
dbutils.notebook.exit(json.dumps(summary))
