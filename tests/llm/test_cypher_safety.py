"""Cypher safety unit tests — spec 0003 §6 (S1–S6), reason codes, stripping, LIMIT (A2, A4).

Pure / DB-free.
"""
import pytest

from tools.cypher_safety import (
    GraphSchema,
    QueryRejectedError,
    _strip_strings_and_comments,
    positive_int,
    validate_and_sanitize_cypher,
)

SCHEMA = GraphSchema.of(
    labels={"Creator", "Media", "Signal", "Score", "User", "Comment"},
    relationship_types={"HAS_MEDIA", "HAS_SIGNAL", "CONTRIBUTED_TO", "SHARES_AUDIENCE",
                        "HAS_COMMENT", "FROM_USER"},
    properties={"user_id", "username", "media_id", "ftc_disclosure_status", "caption_text",
                "name", "value", "art9_risk", "overlap_pct", "method", "confidence", "type"},
)


def _validate(cypher, params=None, max_rows=200):
    return validate_and_sanitize_cypher(cypher, params or {}, SCHEMA, max_rows)


# ── S1 write/admin denylist ────────────────────────────────────────────────────

@pytest.mark.parametrize("cypher", [
    "MATCH (c:Creator) DETACH DELETE c",
    "CREATE (c:Creator {user_id:1})",
    "MATCH (c:Creator) SET c.username = 'x' RETURN c",
    "MATCH (c:Creator) REMOVE c.username RETURN c",
    "MERGE (c:Creator {user_id:'x'})",
    "DROP CONSTRAINT creator_user_id",
    "MATCH (c:Creator) FOREACH (x IN [1] | SET c.n = x)",
    "LOAD CSV FROM 'file:///x.csv' AS row RETURN row",
])
def test_s1_write_keyword_rejected(cypher):
    with pytest.raises(QueryRejectedError) as ei:
        _validate(cypher)
    assert ei.value.reason_code == "WRITE_KEYWORD"


def test_s1_in_transactions_rejected():
    with pytest.raises(QueryRejectedError) as ei:
        _validate("MATCH (c:Creator) CALL { WITH c RETURN c } IN TRANSACTIONS RETURN c")
    assert ei.value.reason_code == "WRITE_KEYWORD"


@pytest.mark.parametrize("cypher", [
    "CALL dbms.killQueries([]) ",
    "CALL apoc.create.node(['X'], {}) YIELD node RETURN node",
])
def test_s1_admin_and_apoc_write_rejected(cypher):
    with pytest.raises(QueryRejectedError) as ei:
        _validate(cypher)
    assert ei.value.reason_code in ("WRITE_KEYWORD", "DISALLOWED_CALL")


# ── positive CALL allowlist ─────────────────────────────────────────────────────

def test_disallowed_call_rejected():
    with pytest.raises(QueryRejectedError) as ei:
        _validate("CALL gds.louvain.stream('g') YIELD nodeId RETURN nodeId")
    assert ei.value.reason_code == "DISALLOWED_CALL"


def test_allowed_schema_call_passes():
    r = _validate("CALL db.labels() YIELD label RETURN label")
    assert r.passed


# ── S2 single statement ──────────────────────────────────────────────────────

def test_s2_multi_statement_rejected():
    with pytest.raises(QueryRejectedError) as ei:
        _validate("MATCH (c:Creator) RETURN c; MATCH (m:Media) RETURN m")
    assert ei.value.reason_code == "MULTI_STATEMENT"


def test_trailing_semicolon_allowed():
    r = _validate("MATCH (c:Creator) RETURN c.username;")
    assert r.passed and ";" not in r.cypher


# ── S4 schema grounding ──────────────────────────────────────────────────────

def test_s4_unknown_label_rejected():
    with pytest.raises(QueryRejectedError) as ei:
        _validate("MATCH (b:Bot) RETURN b")
    assert ei.value.reason_code == "UNKNOWN_LABEL"


def test_s4_unknown_property_rejected():
    with pytest.raises(QueryRejectedError) as ei:
        _validate("MATCH (c:Creator) RETURN c.shoe_size")
    assert ei.value.reason_code == "UNKNOWN_PROPERTY"


def test_s4_known_property_passes():
    assert _validate("MATCH (c:Creator) RETURN c.username").passed


# ── S6 parameterization ──────────────────────────────────────────────────────

def test_s6_unbound_param_rejected():
    with pytest.raises(QueryRejectedError) as ei:
        _validate("MATCH (c:Creator) WHERE c.user_id = $uid RETURN c.username")
    assert ei.value.reason_code == "MISSING_PARAM"


def test_s6_bound_param_passes():
    assert _validate(
        "MATCH (c:Creator) WHERE c.user_id = $uid RETURN c.username", {"uid": "x"}
    ).passed


# ── string / comment stripping (no false rejects, no smuggling) ─────────────────

def test_string_literal_keyword_not_rejected():
    """A denied keyword inside a string literal must NOT be rejected."""
    r = _validate("MATCH (m:Media) WHERE m.caption_text = 'I want to CREATE art' RETURN m.media_id")
    assert r.passed


def test_comment_hidden_keyword_is_blanked_before_scan():
    stripped = _strip_strings_and_comments("MATCH (c:Creator) // DELETE everything\nRETURN c")
    assert "DELETE" not in stripped
    # and a query whose only 'DELETE' is in a comment is therefore allowed:
    assert _validate("MATCH (c:Creator) // DELETE everything\nRETURN c.username").passed


def test_block_comment_blanked():
    stripped = _strip_strings_and_comments("MATCH (c:Creator) /* SET x */ RETURN c")
    assert "SET" not in stripped


# ── S5 LIMIT injection / clamp ─────────────────────────────────────────────────

def test_s5_limit_injected_when_absent():
    r = _validate("MATCH (c:Creator) RETURN c.username", max_rows=50)
    assert r.limit_injected
    assert r.cypher.rstrip().endswith("LIMIT 50")


def test_s5_limit_clamped_when_too_large():
    r = _validate("MATCH (c:Creator) RETURN c.username LIMIT 9999", max_rows=200)
    assert "LIMIT 200" in r.cypher
    assert "9999" not in r.cypher
    assert any(x["reason_code"] == "LIMIT_CLAMPED" for x in r.reasons)


def test_s5_limit_within_cap_untouched():
    r = _validate("MATCH (c:Creator) RETURN c.username LIMIT 10", max_rows=200)
    assert "LIMIT 10" in r.cypher and not r.limit_injected


# ── config bounds ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", ["0", "-5", "abc", "1.5"])
def test_positive_int_rejects_bad(bad):
    with pytest.raises(ValueError):
        positive_int(bad, "ASK_MAX_ROWS", 200)


def test_positive_int_default_and_parse():
    assert positive_int(None, "ASK_MAX_ROWS", 200) == 200
    assert positive_int("42", "ASK_MAX_ROWS", 200) == 42


def test_empty_query_rejected():
    with pytest.raises(QueryRejectedError) as ei:
        _validate("   ")
    assert ei.value.reason_code == "EMPTY_QUERY"
