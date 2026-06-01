"""Blocking step — narrows the candidate set before scoring (spec 0011 §3, T11).

v3a uses exact-handle blocking: only candidates whose ``candidate_handle``
matches the Instagram handle (case-insensitive) advance to scoring.
LSH is explicitly deferred to v3b.
"""
from __future__ import annotations


def block_candidates(instagram_handle: str, candidates: list[dict]) -> list[dict]:
    """Return the subset of ``candidates`` that pass the exact-handle block.

    A candidate passes when its ``candidate_handle`` equals the Instagram handle
    (case-insensitive comparison after stripping leading ``@``).
    All other candidates are retained as non_link entries — this function only
    *narrows* for scoring priority; the orchestrator keeps the full list.
    """
    handle_norm = instagram_handle.lstrip("@").lower()
    priority: list[dict] = []
    rest: list[dict] = []
    for c in candidates:
        cand_handle = c.get("candidate_handle", "").lstrip("@").lower()
        if cand_handle == handle_norm:
            priority.append(c)
        else:
            rest.append(c)
    return priority + rest
