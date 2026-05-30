"""Cypher safety layer (spec 0003 §6 / §6.1).

Pure, DB-free, fully unit-testable. The single point through which any model-generated
Cypher must pass before execution. Implements gates S1, S2, S4, S5, S6 (S3 — the read-only
transaction — is enforced at the driver level in ``tools/ask.py``).

Design notes
------------
* **Scan stripped text, not raw.** S1/S2 keyword and ``;`` detection run against a copy with
  string literals and ``//`` / ``/* */`` comments blanked out, so a denied keyword *inside a
  string literal* (e.g. a caption containing "CREATE") is not a false reject, and a keyword
  *hidden* in a comment cannot smuggle past the scan.
* **Positive CALL allowlist.** Any ``CALL`` whose procedure is not on the read allowlist is
  rejected — closing the gap where a new/unknown write procedure isn't on a denylist.
* **Schema grounding (S4)** validates dotted property access (``var.prop``) and ``:Label`` /
  ``:REL_TYPE`` references against the live schema. Map-projection / inline-map keys are *not*
  treated as graph properties (they are arbitrary output keys), to avoid false rejects.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


# ── data types ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class GraphSchema:
    """The live graph schema used for grounding (from ``tools/ask.load_graph_schema``)."""
    labels: frozenset[str]
    relationship_types: frozenset[str]
    properties: frozenset[str]

    @classmethod
    def of(
        cls,
        labels: list[str] | set[str],
        relationship_types: list[str] | set[str],
        properties: list[str] | set[str],
    ) -> "GraphSchema":
        return cls(frozenset(labels), frozenset(relationship_types), frozenset(properties))


@dataclass
class CypherValidationResult:
    """A sanitized, single, read-only statement ready for a read transaction."""
    cypher: str
    params: dict
    passed: bool = True
    reasons: list[dict] = field(default_factory=list)
    limit_injected: bool = False


class QueryRejectedError(Exception):
    """Raised when generated Cypher fails any safety gate.

    Carries a machine-readable ``reason_code`` recorded in the query manifest's
    ``validation.reasons[]`` (spec §6.1 / §7 C1).
    """

    def __init__(self, reason_code: str, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.message = message
        self.details = details or {}

    def as_reason(self) -> dict:
        return {"reason_code": self.reason_code, "message": self.message, "details": self.details}


# ── denylists / allowlists (S1) ──────────────────────────────────────────────

# Whole-token, case-insensitive write/admin keywords (S1).
_WRITE_KEYWORDS = frozenset({
    "CREATE", "MERGE", "DELETE", "DETACH", "SET", "REMOVE", "DROP", "FOREACH", "LOAD",
})

# Positive CALL allowlist (S1 / §6.1) — read-only schema procedures only.
_ALLOWED_CALLS = frozenset({
    "db.schema.visualization", "db.labels", "db.relationshiptypes", "db.propertykeys",
})

# Dotted-token prefixes that are always write/admin namespaces (defense in depth).
_ADMIN_PREFIXES = ("dbms.", "db.create", "apoc.create", "apoc.merge", "apoc.refactor")

# Left-hand identifiers in ``ns.member`` that are procedure namespaces, never node variables.
_NAMESPACE_SKIP = frozenset({"db", "dbms", "apoc", "gds", "cypher", "schema"})


# ── text stripping ────────────────────────────────────────────────────────────

def _strip_strings_and_comments(cypher: str) -> str:
    """Blank string literals and ``//`` / ``/* */`` comments (preserving length/structure).

    String *contents* are replaced with spaces (quotes kept) so the scanned text has the same
    layout but cannot hide a keyword. Comments are replaced with spaces.
    """
    out: list[str] = []
    i, n = 0, len(cypher)
    state = "normal"  # normal | s_single | s_double | s_backtick | line_comment | block_comment
    while i < n:
        ch = cypher[i]
        nxt = cypher[i + 1] if i + 1 < n else ""
        if state == "normal":
            if ch == "'":
                state, _ = "s_single", out.append(ch)
            elif ch == '"':
                state, _ = "s_double", out.append(ch)
            elif ch == "`":
                state, _ = "s_backtick", out.append(ch)
            elif ch == "/" and nxt == "/":
                state = "line_comment"
                out.append("  ")
                i += 2
                continue
            elif ch == "/" and nxt == "*":
                state = "block_comment"
                out.append("  ")
                i += 2
                continue
            else:
                out.append(ch)
        elif state in ("s_single", "s_double", "s_backtick"):
            quote = {"s_single": "'", "s_double": '"', "s_backtick": "`"}[state]
            if ch == "\\" and state != "s_backtick":  # escaped char inside '...'/"..."
                out.append("  ")
                i += 2
                continue
            if ch == quote:
                out.append(ch)
                state = "normal"
            else:
                out.append(" ")
        elif state == "line_comment":
            if ch == "\n":
                out.append(ch)
                state = "normal"
            else:
                out.append(" ")
        elif state == "block_comment":
            if ch == "*" and nxt == "/":
                out.append("  ")
                i += 2
                state = "normal"
                continue
            out.append(" " if ch != "\n" else ch)
        i += 1
    return "".join(out)


# ── individual gates ──────────────────────────────────────────────────────────

def _strip_trailing_semicolon(cypher: str) -> str:
    return re.sub(r";\s*$", "", cypher.rstrip()).rstrip()


def _check_single_statement(stripped: str) -> None:
    """S2 — reject any non-trailing ``;`` (no ``;``-separated batches)."""
    without_trailing = re.sub(r";\s*$", "", stripped.rstrip())
    if ";" in without_trailing:
        raise QueryRejectedError(
            "MULTI_STATEMENT",
            "Multiple statements are not allowed; submit a single read-only query.",
        )


def _check_write_keywords(stripped: str) -> None:
    """S1 — whole-token write/admin keyword denylist + admin-namespace prefixes."""
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_.]*", stripped)
    for tok in tokens:
        if tok.upper() in _WRITE_KEYWORDS:
            raise QueryRejectedError(
                "WRITE_KEYWORD",
                f"Write/admin keyword '{tok.upper()}' is not permitted (read-only).",
                {"keyword": tok.upper()},
            )
        low = tok.lower()
        if any(low.startswith(p) for p in _ADMIN_PREFIXES):
            raise QueryRejectedError(
                "WRITE_KEYWORD",
                f"Admin/write procedure namespace '{tok}' is not permitted.",
                {"procedure": tok},
            )
    # CALL {...} IN TRANSACTIONS (batched write construct)
    if re.search(r"\bIN\s+TRANSACTIONS\b", stripped, re.IGNORECASE):
        raise QueryRejectedError(
            "WRITE_KEYWORD",
            "'IN TRANSACTIONS' (batched write) is not permitted.",
        )


def _check_call_allowlist(stripped: str) -> None:
    """S1 — positive CALL allowlist. Subquery ``CALL { ... }`` is allowed; named procedures
    must be on the read allowlist."""
    for m in re.finditer(r"\bCALL\b\s*(\{|[A-Za-z_][A-Za-z0-9_.]*)", stripped, re.IGNORECASE):
        target = m.group(1)
        if target == "{":  # read-only subquery (IN TRANSACTIONS already rejected)
            continue
        if target.lower() not in _ALLOWED_CALLS:
            raise QueryRejectedError(
                "DISALLOWED_CALL",
                f"CALL {target} is not on the read-only procedure allowlist.",
                {"procedure": target},
            )


def _check_schema_grounding(stripped: str, schema: GraphSchema) -> None:
    """S4 — every referenced label / rel-type / dotted property must exist in the schema."""
    known_node_or_rel = schema.labels | schema.relationship_types
    # A label / rel-type ``:Name`` follows ``(``, ``[``, ``|`` or a chained ``:`` (optionally with a
    # bound variable in between). This deliberately does NOT match a map-key colon (``{k: v}``),
    # whose ``:`` is preceded by ``{`` / ``,`` — so literals like ``{art9_risk: true}`` are not
    # mistaken for labels.
    for label in re.findall(
        r"[(\[|:]\s*(?:[A-Za-z_][A-Za-z0-9_]*)?\s*:([A-Za-z_][A-Za-z0-9_]*)", stripped
    ):
        if label not in known_node_or_rel:
            raise QueryRejectedError(
                "UNKNOWN_LABEL",
                f"Unknown label or relationship type ':{label}' (not in graph schema).",
                {"identifier": label},
            )
    for var, prop in re.findall(
        r"(?<![A-Za-z0-9_.])([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)", stripped
    ):
        if var.lower() in _NAMESPACE_SKIP:  # procedure namespace, not a node variable
            continue
        if prop not in schema.properties:
            raise QueryRejectedError(
                "UNKNOWN_PROPERTY",
                f"Unknown property '{var}.{prop}' (not in graph schema).",
                {"variable": var, "property": prop},
            )


def _check_parameterization(stripped: str, params: dict) -> None:
    """S6 — every ``$param`` referenced must be supplied in *params* (literals are bound,
    never string-concatenated)."""
    referenced = set(re.findall(r"\$([A-Za-z_][A-Za-z0-9_]*)", stripped))
    missing = sorted(referenced - set(params or {}))
    if missing:
        raise QueryRejectedError(
            "MISSING_PARAM",
            f"Query references unbound parameter(s): {missing}.",
            {"missing": missing},
        )


def _inject_limit(cypher_norm: str, stripped: str, max_rows: int) -> tuple[str, bool, bool]:
    """S5 — ensure a ``LIMIT <= max_rows``.

    Returns ``(cypher, injected, clamped)``. If no LIMIT is present, append one. If a trailing
    numeric LIMIT exceeds *max_rows*, clamp it. A parameterized/non-numeric LIMIT is left as-is
    (the client-side row roof in ask.py still enforces the cap).
    """
    if not re.search(r"\bLIMIT\b", stripped, re.IGNORECASE):
        return f"{cypher_norm}\nLIMIT {max_rows}", True, False

    # Clamp the last numeric LIMIT literal if it exceeds the cap.
    matches = list(re.finditer(r"\bLIMIT\s+(\d+)\b", cypher_norm, re.IGNORECASE))
    if matches:
        last = matches[-1]
        if int(last.group(1)) > max_rows:
            start, end = last.span()
            return cypher_norm[:start] + f"LIMIT {max_rows}" + cypher_norm[end:], False, True
    return cypher_norm, False, False


# ── config bounds (S5) ──────────────────────────────────────────────────────

def positive_int(value: str | int | None, name: str, default: int) -> int:
    """Parse a positive-integer config value; fail fast on bad input (§6.1)."""
    if value is None or value == "":
        return default
    try:
        iv = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a positive integer, got {value!r}")
    if iv <= 0:
        raise ValueError(f"{name} must be a positive integer, got {iv}")
    return iv


# ── public entry point ──────────────────────────────────────────────────────

def validate_and_sanitize_cypher(
    cypher: str,
    params: dict,
    schema: GraphSchema,
    max_rows: int,
) -> CypherValidationResult:
    """Run gates S1–S2, S4–S6 over *cypher*; raise :class:`QueryRejectedError` on any violation.

    On success returns a single sanitized statement with a ``LIMIT <= max_rows`` (S5).
    """
    if not cypher or not cypher.strip():
        raise QueryRejectedError("EMPTY_QUERY", "Empty Cypher statement.")
    if max_rows <= 0:
        raise ValueError(f"max_rows must be a positive integer, got {max_rows}")

    params = params or {}
    stripped = _strip_strings_and_comments(cypher)

    _check_single_statement(stripped)           # S2
    _check_write_keywords(stripped)             # S1
    _check_call_allowlist(stripped)             # S1
    _check_schema_grounding(stripped, schema)   # S4
    _check_parameterization(stripped, params)   # S6

    cypher_norm = _strip_trailing_semicolon(cypher)
    stripped_norm = _strip_trailing_semicolon(stripped)
    sanitized, injected, clamped = _inject_limit(cypher_norm, stripped_norm, max_rows)  # S5

    reasons: list[dict] = []
    if injected:
        reasons.append({"reason_code": "LIMIT_INJECTED",
                        "message": f"No LIMIT present; injected LIMIT {max_rows}."})
    if clamped:
        reasons.append({"reason_code": "LIMIT_CLAMPED",
                        "message": f"LIMIT exceeded cap; clamped to {max_rows}."})

    return CypherValidationResult(
        cypher=sanitized,
        params=params,
        passed=True,
        reasons=reasons,
        limit_injected=injected,
    )
