"""In-memory fake graph session for stage-7 tests without a running Neo4j.

Implements the same write/read/run interface as pipeline.graph.GraphSession using
plain Python dicts. Each Cypher pattern from stage7_load.py and queries.py is
dispatched by string matching and mutates the internal state, making A2 (idempotency)
and A7 (versioning) tests genuinely meaningful rather than trivially mocked.
"""
from __future__ import annotations

from typing import Any


class FakeGraphSession:
    """Stateful in-memory replica of GraphSession for spec-0002 integration tests.

    Node stores keyed by natural key; edge store keyed by (from_key, rel_type, to_key)
    so MERGE is naturally idempotent — a second MERGE on the same key just overwrites
    props, never duplicates. Signal/Score keys are (creator_user_id, name/type, run_id)
    so supersede-by-run_id maps to simple dict comprehensions.
    """

    def __init__(self) -> None:
        self.database = "fake"
        # entity stores: natural-key → props
        self._creators: dict[str, dict] = {}       # user_id
        self._media: dict[str, dict] = {}          # media_id
        self._comments: dict[str, dict] = {}       # comment_id
        self._users: dict[str, dict] = {}          # username
        # versioned stores: (creator_user_id, name|type, run_id) → props
        self._signals: dict[tuple, dict] = {}
        self._scores: dict[tuple, dict] = {}
        # edge store: (from_key, rel_type, to_key) → props  — idempotent by key
        self._edges: dict[tuple, dict] = {}

    # ── context manager ───────────────────────────────────────────────────────

    def __enter__(self) -> "FakeGraphSession":
        return self

    def __exit__(self, *_: object) -> None:
        pass

    # ── schema (no-op) ────────────────────────────────────────────────────────

    def run(self, cypher: str, **_: Any) -> None:  # CREATE CONSTRAINT / INDEX
        pass

    # ── writes ────────────────────────────────────────────────────────────────

    def write(self, cypher: str, **params: Any) -> list[dict]:
        # supersede prior-run signals
        if "HAS_SIGNAL" in cypher and "DETACH DELETE" in cypher:
            return self._supersede(self._signals, params["uid"], params["rid"])

        # supersede prior-run scores
        if "CONTRIBUTED_TO" in cypher and "DETACH DELETE" in cypher:
            return self._supersede(self._scores, params["uid"], params["rid"])

        # MERGE Creator
        if "MERGE (c:Creator" in cypher:
            row: dict = params["row"]
            uid: str = row["user_id"]
            is_new = uid not in self._creators
            self._creators[uid] = {**self._creators.get(uid, {}), **row}
            ts_key = "first_seen" if is_new else "last_seen"
            self._creators[uid][ts_key] = params["loaded_at"]
            return []

        # MERGE Media + HAS_MEDIA edges
        if "MERGE (m:Media" in cypher:
            uid = params["uid"]
            for row in params.get("rows", []):
                mid: str = row["media_id"]
                is_new = mid not in self._media
                self._media[mid] = {**self._media.get(mid, {}), **row}
                ts_key = "first_seen" if is_new else "last_seen"
                self._media[mid][ts_key] = params["loaded_at"]
                self._merge_edge(uid, "HAS_MEDIA", mid, {})
            return []

        # MERGE Comments + HAS_COMMENT + FROM_USER edges
        if "MERGE (cm:Comment" in cypher:
            for row in params.get("rows", []):
                cid: str = row["comment_id"]
                self._comments[cid] = dict(row)
                self._merge_edge(row["media_id"], "HAS_COMMENT", cid, {})
                uname = row.get("author_username")
                if uname:
                    self._users.setdefault(uname, {"username": uname, "is_bot_score": None})
                    self._merge_edge(cid, "FROM_USER", uname, {})
            return []

        # MERGE Users
        if "MERGE (u:User" in cypher:
            for row in params.get("rows", []):
                uname = row["username"]
                self._users.setdefault(uname, {})
                self._users[uname].update(row)
            return []

        # MERGE Signals + HAS_SIGNAL edges
        if "MERGE (sig:Signal" in cypher:
            uid = params["uid"]
            rid: str = params["rid"]
            for row in params.get("rows", []):
                key = (uid, row["name"], rid)
                self._signals[key] = {**row, "run_id": rid, "creator_user_id": uid}
                weight = row.get("confidence") or 0.0
                self._merge_edge(uid, "HAS_SIGNAL", key, {"weight": weight})
            return []

        # MERGE Scores + CONTRIBUTED_TO edges
        if "MERGE (sc:Score" in cypher:
            uid = params["uid"]
            rid = params["rid"]
            for row in params.get("rows", []):
                key = (uid, row["type"], rid)
                self._scores[key] = {**row, "run_id": rid, "creator_user_id": uid}
                weight = row.get("confidence") or 0.0
                self._merge_edge(uid, "CONTRIBUTED_TO", key, {"weight": weight})
            return []

        # MERGE SHARES_AUDIENCE edges
        if "SHARES_AUDIENCE" in cypher:
            for row in params.get("rows", []):
                self._merge_edge(
                    row["source_user_id"], "SHARES_AUDIENCE", row["target_user_id"],
                    {"overlap_pct": row["overlap_pct"]},
                )
            return []

        raise ValueError(
            f"FakeGraphSession: unrecognised write pattern — add a handler or fix the query.\n"
            f"Cypher (first 200 chars): {cypher[:200]!r}"
        )

    # ── reads ─────────────────────────────────────────────────────────────────

    def read(self, cypher: str, **params: Any) -> list[dict]:
        # AQ1: explain_score — must check before simpler CONTRIBUTED_TO or HAS_SIGNAL patterns
        if "CONTRIBUTED_TO" in cypher and "HAS_SIGNAL" in cypher:
            return self._aq1_explain_score(params)

        # AQ3: art9_signals
        if "art9_risk" in cypher and "HAS_SIGNAL" in cypher:
            return self._aq3_art9_signals(params)

        # count(c:Creator)
        if "count(c)" in cypher and ":Creator" in cypher:
            return [{"n": len(self._creators)}]

        # count all nodes
        if "count(n) AS c" in cypher:
            total = (len(self._creators) + len(self._media) + len(self._comments)
                     + len(self._users) + len(self._signals) + len(self._scores))
            return [{"c": total}]

        # count all edges — used by A2 (idempotency).
        # Edge idempotency here is structural (dict upsert), not Cypher MERGE semantics.
        # A2 validates loader orchestration; duplicate-relationship prevention via Neo4j
        # MERGE must be verified separately against a live database.
        if "count(x) AS c" in cypher:
            return [{"c": len(self._edges)}]

        # count SHARES_AUDIENCE edges (test_a6 deferred-associations check)
        if "SHARES_AUDIENCE" in cypher and "count(r)" in cypher:
            n = sum(1 for k in self._edges if k[1] == "SHARES_AUDIENCE")
            return [{"n": n}]

        # AQ2: audience_overlap — returns empty until [v2]; handler prevents ValueError
        if "SHARES_AUDIENCE" in cypher:
            uid = params.get("user_id")
            rows = []
            for (from_key, rel_type, to_key), props in self._edges.items():
                if rel_type != "SHARES_AUDIENCE" or from_key != uid:
                    continue
                rows.append({
                    "source": self._creators.get(from_key, {}).get("username"),
                    "target": self._creators.get(to_key, {}).get("username"),
                    "overlap_pct": props.get("overlap_pct"),
                })
            return sorted(rows, key=lambda r: r["overlap_pct"] or 0, reverse=True)

        # AQ4: undisclosed_sponsored — returns media with ftc_disclosure_status == 'undisclosed'
        if "ftc_disclosure_status" in cypher:
            uid = params.get("user_id")
            creator = self._creators.get(uid, {})
            return [
                {
                    "username": creator.get("username"),
                    "media_id": v["media_id"],
                    "permalink": v.get("permalink"),
                    "timestamp": v.get("timestamp"),
                }
                for v in self._media.values()
                if v.get("ftc_disclosure_status") == "undisclosed"
            ]

        # DISTINCT signal run_ids (A7 versioning check)
        if "DISTINCT s.run_id" in cypher:
            run_ids = {k[2] for k in self._signals}
            return [{"rid": rid} for rid in run_ids]

        # AQ5: creator_profile — return Creator node properties
        if "c.username AS username" in cypher and ":Creator" in cypher:
            uid = params.get("user_id")
            c = self._creators.get(uid)
            if not c:
                return []
            return [{
                "username": c.get("username"),
                "followers_count": c.get("followers_count"),
                "media_count": c.get("media_count"),
                "verified": c.get("verified"),
            }]

        # AQ6: creator_media_count — count HAS_MEDIA edges for a creator
        if "HAS_MEDIA" in cypher and "count(m) AS n" in cypher:
            uid = params.get("user_id")
            n = sum(1 for (from_key, rel_type, _) in self._edges
                    if rel_type == "HAS_MEDIA" and from_key == uid)
            return [{"n": n}]

        # AQ7: primary_niche — return primary_niche signal value
        if "'primary_niche'" in cypher and "s.value AS niche" in cypher:
            uid = params.get("user_id")
            run_id = params.get("run_id")
            for k, v in self._signals.items():
                if k[0] == uid and k[1] == "primary_niche" and k[2] == run_id:
                    return [{"niche": v.get("value")}]
            return []

        # AQ8: related_by_niche — creators sharing the same primary_niche value
        if "c2.user_id <> c1.user_id" in cypher and "primary_niche" in cypher:
            uid = params.get("user_id")
            run_id = params.get("run_id")
            source_niche = None
            for k, v in self._signals.items():
                if k[0] == uid and k[1] == "primary_niche" and k[2] == run_id:
                    source_niche = v.get("value")
                    break
            if not source_niche:
                return []
            results = []
            for k, v in self._signals.items():
                if k[1] == "primary_niche" and k[2] == run_id and k[0] != uid:
                    if v.get("value") == source_niche:
                        creator = self._creators.get(k[0], {})
                        results.append({"user_id": k[0], "username": creator.get("username")})
            return sorted(results, key=lambda r: r.get("username") or "")

        raise ValueError(
            f"FakeGraphSession: unrecognised read pattern — add a handler or fix the query.\n"
            f"Cypher (first 200 chars): {cypher[:200]!r}"
        )

    # ── query helpers ─────────────────────────────────────────────────────────

    def _aq1_explain_score(self, params: dict) -> list[dict]:
        uid = params.get("user_id")
        score_type = params.get("score_type")
        run_id = params.get("run_id")
        score_key = (uid, score_type, run_id)
        if score_key not in self._scores:
            return []
        score = self._scores[score_key]
        creator = self._creators.get(uid, {})
        signal_entries = [
            {
                "signal": v["name"],
                "weight": self._edges.get((uid, "HAS_SIGNAL", k), {}).get("weight", 0.0),
                "value": v.get("value"),
                "source": v.get("source"),
                "confidence": v.get("confidence"),
                "method": v.get("method"),
                "art9_risk": v.get("art9_risk"),
            }
            for k, v in self._signals.items()
            if k[0] == uid and k[2] == run_id
        ]
        return [{
            "username": creator.get("username"),
            "type": score.get("type"),
            "value": score.get("value"),
            "model_version": score.get("model_version"),
            "signals": signal_entries,
        }]

    def _aq3_art9_signals(self, params: dict) -> list[dict]:
        uid = params.get("user_id")
        run_id = params.get("run_id")
        creator = self._creators.get(uid, {})
        return [
            {
                "username": creator.get("username"),
                "name": v["name"],
                "value": v.get("value"),
                "method": v.get("method"),
                "confidence": v.get("confidence"),
            }
            for k, v in self._signals.items()
            if k[0] == uid and k[2] == run_id and v.get("art9_risk")
        ]

    # ── internal helpers ──────────────────────────────────────────────────────

    def _supersede(self, store: dict, uid: str, rid: str) -> list[dict]:
        """DETACH DELETE nodes whose run_id != rid, return count removed.

        Only cleans edges pointing TO deleted nodes (ek[2] == k). Signal and Score
        nodes are currently only edge targets in the spec-0002 schema; no edges
        originate FROM them. If a future migration adds outbound edges from Signal
        or Score, extend cleanup to ``ek[0] == k`` as well.
        """
        old_keys = [k for k in store if k[0] == uid and k[2] != rid]
        for k in old_keys:
            del store[k]
            for ek in [ek for ek in list(self._edges) if ek[2] == k]:
                del self._edges[ek]
        return [{"removed": len(old_keys)}]

    def _merge_edge(self, from_key: Any, rel_type: str, to_key: Any, props: dict) -> None:
        """Idempotent edge upsert — same (from, type, to) key just overwrites props."""
        key = (from_key, rel_type, to_key)
        self._edges[key] = {**self._edges.get(key, {}), **props}
