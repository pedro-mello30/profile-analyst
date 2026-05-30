"""NL→Cypher graph query tool (spec 0003 §4.1, §6, §7).

`--ask "<question>"` → load graph schema → Ollama generates read-only Cypher → validate (§6) →
execute in a read-only transaction → Ollama phrases an answer grounded *only* in the rows →
write a query manifest. The manifest is **always** written (including on rejection). Creator data
never leaves the host (`data_egress: local-only`).
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import jsonschema

from pipeline.graph.connection import graph_config
from pipeline.llm.ollama_client import OllamaClient, OllamaError
from tools.cypher_safety import (
    GraphSchema,
    QueryRejectedError,
    positive_int,
    validate_and_sanitize_cypher,
)

_MANIFEST_SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "08-query.schema.json"


# ── read-only graph access (S3) ───────────────────────────────────────────────

class ReadOnlyGraph:
    """A read-only Neo4j session (spec §6 S3). Reuses 0002 connection config.

    Opened with ``READ_ACCESS`` and every query runs in a read transaction, so a write Cypher is
    rejected by the server even if it somehow passed validation (A3).
    """

    def __init__(self, cfg: dict | None = None) -> None:
        cfg = cfg or graph_config()
        self.uri = cfg["uri"]
        self.user = cfg["user"]
        self.password = cfg["password"]
        self.database = cfg["database"]
        self._driver = None
        self._session = None

    def __enter__(self) -> "ReadOnlyGraph":
        import neo4j
        from neo4j import GraphDatabase

        self._driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
        self._session = self._driver.session(
            database=self.database, default_access_mode=neo4j.READ_ACCESS
        )
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._session is not None:
            self._session.close()
        if self._driver is not None:
            self._driver.close()
        self._session = self._driver = None

    def _read_scalar(self, cypher: str, key: str) -> list[str]:
        def work(tx):
            return [rec[key] for rec in tx.run(cypher)]

        return self._session.execute_read(work)

    def labels(self) -> list[str]:
        return self._read_scalar("CALL db.labels() YIELD label RETURN label", "label")

    def relationship_types(self) -> list[str]:
        return self._read_scalar(
            "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType",
            "relationshipType",
        )

    def property_keys(self) -> list[str]:
        return self._read_scalar(
            "CALL db.propertyKeys() YIELD propertyKey RETURN propertyKey", "propertyKey"
        )

    def run_read(self, cypher: str, params: dict, timeout_ms: int, max_rows: int) -> list[dict]:
        """Execute *cypher* in a read transaction with a statement timeout + client-side row roof."""
        timeout_s = timeout_ms / 1000.0
        with self._session.begin_transaction(timeout=timeout_s) as tx:
            result = tx.run(cypher, **(params or {}))
            rows: list[dict] = []
            for i, rec in enumerate(result):
                if i >= max_rows:
                    break
                rows.append(rec.data())
            return rows


# ── schema grounding (§4.1 step 1) ─────────────────────────────────────────────

_SCHEMA_CACHE: dict[tuple, GraphSchema] = {}


def load_graph_schema(graph: ReadOnlyGraph) -> GraphSchema:
    """Read the live graph schema, cached per (uri, database) for the process."""
    key = (graph.uri, graph.database)
    cached = _SCHEMA_CACHE.get(key)
    if cached is not None:
        return cached
    schema = GraphSchema.of(
        graph.labels(), graph.relationship_types(), graph.property_keys()
    )
    _SCHEMA_CACHE[key] = schema
    return schema


# ── Cypher generation (§4.1 step 2) ────────────────────────────────────────────

_SYSTEM_RULES = """You translate a natural-language question into ONE read-only Neo4j Cypher query.

Hard rules (the query is rejected if any is violated):
- READ ONLY. Never use CREATE, MERGE, DELETE, DETACH, SET, REMOVE, DROP, FOREACH, LOAD CSV,
  CALL {...} IN TRANSACTIONS, or any dbms.*/apoc write procedure. Only MATCH / OPTIONAL MATCH /
  WHERE / WITH / RETURN / ORDER BY / SKIP / LIMIT / UNWIND and read CALLs are allowed.
- A SINGLE statement (no ';'-separated batches).
- Reference ONLY labels, relationship types, and properties that exist in the schema below.
- Bind any literal from the question as a Cypher PARAMETER ($name); never concatenate it into the
  query text. Put those values in "params".

Respond with ONLY a JSON object, no prose, no code fences:
{"cypher": "<single read-only statement>", "params": {<bound parameters>}, "rationale": "<one line>"}
"""

# Few-shot derived from spec 0002 audit queries AQ1–AQ4.
_FEW_SHOT = """Examples (schema-grounded, parameterized, read-only):

Q: explain the brand_fit score for creator user_42
A: {"cypher": "MATCH (c:Creator {user_id:$user_id})-[r:CONTRIBUTED_TO]->(s:Score {type:$score_type}) RETURN c.username AS username, s.type AS type, s.value AS value", "params": {"user_id":"user_42","score_type":"brand_fit"}, "rationale": "score with contributing signals"}

Q: which creators share audience with user_42
A: {"cypher": "MATCH (a:Creator {user_id:$user_id})-[r:SHARES_AUDIENCE]->(b:Creator) RETURN b.username AS creator, r.overlap_pct AS overlap_pct ORDER BY r.overlap_pct DESC", "params": {"user_id":"user_42"}, "rationale": "audience overlap edges"}

Q: list Art. 9 sensitive signals for user_42
A: {"cypher": "MATCH (c:Creator {user_id:$user_id})-[:HAS_SIGNAL]->(s:Signal {art9_risk:true}) RETURN s.name AS name, s.value AS value, s.method AS method, s.confidence AS confidence, s.art9_risk AS art9_risk", "params": {"user_id":"user_42"}, "rationale": "special-category inferences"}

Q: show undisclosed sponsored posts for user_42
A: {"cypher": "MATCH (c:Creator {user_id:$user_id})-[:HAS_MEDIA]->(m:Media) WHERE m.ftc_disclosure_status = 'undisclosed' RETURN m.media_id AS media_id, m.permalink AS permalink, m.timestamp AS timestamp", "params": {"user_id":"user_42"}, "rationale": "FTC undisclosed media"}
"""


def _schema_block(schema: GraphSchema) -> str:
    return (
        "Graph schema:\n"
        f"- Labels: {', '.join(sorted(schema.labels)) or '(none)'}\n"
        f"- Relationship types: {', '.join(sorted(schema.relationship_types)) or '(none)'}\n"
        f"- Property keys: {', '.join(sorted(schema.properties)) or '(none)'}\n"
    )


def build_cypher_generation_messages(
    schema: GraphSchema, question: str, prior_error: str | None = None
) -> list[dict]:
    system = f"{_SYSTEM_RULES}\n{_schema_block(schema)}\n{_FEW_SHOT}"
    user = question
    if prior_error:
        user = (
            f"{question}\n\nYour previous query was rejected: {prior_error}\n"
            "Return a corrected single read-only query as JSON."
        )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def generate_cypher(
    ollama: OllamaClient,
    model: str,
    schema: GraphSchema,
    question: str,
    prior_error: str | None = None,
) -> dict:
    """Ask the model for ``{cypher, params, rationale}`` (temperature=0 for determinism)."""
    messages = build_cypher_generation_messages(schema, question, prior_error)
    text = ollama.chat(model, messages, options={"temperature": 0, "seed": 0}, fmt="json")
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    data = json.loads(text)
    return {
        "cypher": data.get("cypher", ""),
        "params": data.get("params") or {},
        "rationale": data.get("rationale", ""),
    }


# ── execution (§4.1 step 4) ────────────────────────────────────────────────────

def execute_readonly_query(
    graph: ReadOnlyGraph, cypher: str, params: dict, max_rows: int, timeout_ms: int
) -> list[dict]:
    return graph.run_read(cypher, params, timeout_ms=timeout_ms, max_rows=max_rows)


# ── answering (§4.1 step 5; C3, C5) ────────────────────────────────────────────

def _rows_have_art9(rows: list[dict]) -> bool:
    for row in rows:
        for k, v in row.items():
            if "art9" in k.lower() and v in (True, "true", "True"):
                return True
    return False


_ANSWER_SYSTEM = """You answer a question using ONLY the JSON rows provided — never outside knowledge.
- If the rows are empty, say plainly that the graph returned no matching data; assert no facts.
- Be concise and factual; do not invent fields, counts, or names not present in the rows.
"""


def build_answer_messages(question: str, rows: list[dict], art9_present: bool) -> list[dict]:
    note = ""
    if art9_present:
        note = (
            "\nNOTE: these results include GDPR Art. 9 special-category (sensitive) inferences. "
            "Begin the answer with: 'Art. 9 notice: results include special-category inferences.'"
        )
    user = (
        f"Question: {question}\n\n"
        f"Rows ({len(rows)}):\n{json.dumps(rows, ensure_ascii=False, default=str)}{note}"
    )
    return [
        {"role": "system", "content": _ANSWER_SYSTEM},
        {"role": "user", "content": user},
    ]


def generate_answer_text(
    ollama: OllamaClient, model: str, question: str, rows: list[dict]
) -> str:
    art9 = _rows_have_art9(rows)
    messages = build_answer_messages(question, rows, art9)
    answer = ollama.chat(model, messages, options={"temperature": 0, "seed": 0}).strip()
    if art9 and "art. 9" not in answer.lower() and "art.9" not in answer.lower():
        answer = "Art. 9 notice: results include special-category inferences. " + answer
    return answer


# ── manifest (§7 C1) ────────────────────────────────────────────────────────────

def _manifest_schema() -> dict:
    with open(_MANIFEST_SCHEMA_PATH) as fh:
        return json.load(fh)


def write_manifest(handle: str, manifest: dict, projects_root: Path = Path("projects")) -> Path:
    """Validate and atomically write the query manifest (always called, incl. on rejection)."""
    jsonschema.validate(manifest, _manifest_schema())
    out_dir = projects_root / handle / "queries"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    out_path = out_dir / f"{ts}-query.json"
    tmp_path = out_path.with_suffix(".tmp")
    with open(tmp_path, "w") as fh:
        json.dump(manifest, fh, indent=2)
    os.replace(tmp_path, out_path)
    return out_path


# ── orchestrator (§4.1) ─────────────────────────────────────────────────────────

class AskResult:
    def __init__(self, exit_code: int, manifest: dict, manifest_path: Path | None) -> None:
        self.exit_code = exit_code
        self.manifest = manifest
        self.manifest_path = manifest_path


def ask(
    handle: str,
    question: str,
    *,
    graph: ReadOnlyGraph | None = None,
    ollama: OllamaClient | None = None,
    cypher_model: str | None = None,
    projects_root: Path = Path("projects"),
) -> AskResult:
    """Run one NL→Cypher interaction. Returns an :class:`AskResult` (exit_code 0 on success).

    A bounded one-shot repair is attempted on a validation rejection (OQ1).
    """
    max_rows = positive_int(os.environ.get("ASK_MAX_ROWS"), "ASK_MAX_ROWS", 200)
    timeout_ms = positive_int(os.environ.get("ASK_TIMEOUT_MS"), "ASK_TIMEOUT_MS", 5000)
    ollama = ollama or OllamaClient()
    model = cypher_model or os.environ.get("OLLAMA_CYPHER_MODEL", "qwen2.5-coder:32b")

    started = time.monotonic()

    def _manifest(*, cypher, params, validation, row_count, answer) -> dict:
        return {
            "question": question,
            "cypher": cypher,
            "params": params or {},
            "model": model,
            "model_role": "cypher",
            "ollama_host": ollama.host,
            "validation": validation,
            "row_count": row_count,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "answer": answer,
            "asked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "read_only": True,
            "data_egress": "local-only",
        }

    own_graph = graph is None
    graph_cm = graph if graph is not None else ReadOnlyGraph()
    if own_graph:
        graph_cm.__enter__()
    try:
        schema = load_graph_schema(graph_cm)

        # Generate → validate, with one bounded repair (OQ1).
        gen = generate_cypher(ollama, model, schema, question)
        result = None
        last_reason: dict | None = None
        for attempt in range(2):
            try:
                result = validate_and_sanitize_cypher(
                    gen["cypher"], gen["params"], schema, max_rows
                )
                break
            except QueryRejectedError as exc:
                last_reason = exc.as_reason()
                if attempt == 0:
                    gen = generate_cypher(ollama, model, schema, question, prior_error=exc.message)

        if result is None:  # rejected even after repair → record and exit non-zero
            manifest = _manifest(
                cypher=gen.get("cypher") or None,
                params=gen.get("params"),
                validation={"passed": False, "reasons": [last_reason] if last_reason else []},
                row_count=0,
                answer=f"Query rejected by safety validation: {last_reason['message'] if last_reason else 'unknown'}",
            )
            path = write_manifest(handle, manifest, projects_root)
            return AskResult(2, manifest, path)

        rows = execute_readonly_query(
            graph_cm, result.cypher, result.params, max_rows, timeout_ms
        )
        answer = generate_answer_text(ollama, model, question, rows)
        manifest = _manifest(
            cypher=result.cypher,
            params=result.params,
            validation={"passed": True, "reasons": result.reasons},
            row_count=len(rows),
            answer=answer,
        )
        path = write_manifest(handle, manifest, projects_root)
        return AskResult(0, manifest, path)
    finally:
        if own_graph:
            graph_cm.__exit__(None, None, None)
