"""Edge families for the association graph (spec 0012 §3, T10-T12).

Two undirected weighted edge families:
  1. content_similar — token-set Jaccard over niche + hashtag tokens from 03-features.json
  2. collaborated    — mutual @mentions, co-tagged posts, co-sponsored brands from 02/03 corpus

Each edge: {u, v, edge_type, weight, method, signals[]}
"""
from __future__ import annotations

import json
from pathlib import Path

from pipeline.models import Profile

CONTENT_SIM_THRESHOLD: float = 0.60

try:
    from sklearn.feature_extraction.text import TfidfVectorizer  # type: ignore
    from sklearn.metrics.pairwise import cosine_similarity  # type: ignore
    import numpy as np  # type: ignore
    _HAS_SKLEARN = True
except ImportError:
    _HAS_SKLEARN = False


# ── helpers ───────────────────────────────────────────────────────────────────

def _load_features(profile: Profile, projects_dir: Path) -> dict:
    path = projects_dir / profile.handle / "03-features.json"
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def _niche_hashtag_tokens(profile: Profile, feat: dict) -> set[str]:
    tokens: set[str] = set()
    for feature in feat.get("features", []):
        fid = feature.get("feature_id", "")
        val = feature.get("value")
        if fid in {"niche", "sub_niche", "content_pillars"} and isinstance(val, (str, list)):
            if isinstance(val, list):
                tokens.update(t.lower() for t in val if isinstance(t, str))
            else:
                tokens.add(val.lower())
    for media in profile.media:
        tokens.update(h.lower().lstrip("#") for h in media.hashtags)
    return tokens


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _tfidf_cosine(doc_a: str, doc_b: str) -> float:
    try:
        vec = TfidfVectorizer().fit_transform([doc_a, doc_b])
        return float(cosine_similarity(vec[0], vec[1])[0, 0])
    except Exception:
        return 0.0


# ── edge family 1: content_similar ───────────────────────────────────────────

def content_similar_edges(
    cohort: list[Profile],
    projects_dir: Path,
) -> list[dict]:
    """Compute content-similarity edges (Jaccard; TF-IDF cosine if scikit-learn available)."""
    features_map = {p.handle: _load_features(p, projects_dir) for p in cohort}
    tokens_map = {p.handle: _niche_hashtag_tokens(p, features_map[p.handle]) for p in cohort}

    edges: list[dict] = []
    handles = [p.handle for p in cohort]
    for i, u in enumerate(handles):
        for v in handles[i + 1:]:
            tok_u = tokens_map[u]
            tok_v = tokens_map[v]
            shared = tok_u & tok_v

            if _HAS_SKLEARN and (tok_u or tok_v):
                doc_u = " ".join(sorted(tok_u)) or "empty"
                doc_v = " ".join(sorted(tok_v)) or "empty"
                sim = _tfidf_cosine(doc_u, doc_v)
            else:
                sim = _jaccard(tok_u, tok_v)

            if sim >= CONTENT_SIM_THRESHOLD:
                signals = [f"shared token: {t}" for t in sorted(shared)[:10]]
                if not signals:
                    signals = [f"similarity={sim:.3f} (no overlapping tokens but TF-IDF match)"]
                edges.append({
                    "u": u,
                    "v": v,
                    "edge_type": "content_similar",
                    "weight": round(sim, 4),
                    "method": "computed",
                    "signals": signals,
                })
    return edges


# ── edge family 2: collaborated ───────────────────────────────────────────────

def _collaboration_signals(profile_a: Profile, feat_a: dict,
                            profile_b: Profile, feat_b: dict) -> list[str]:
    signals: set[str] = set()

    # mutual @mentions
    handles_a = {m.lower().lstrip("@") for media in profile_a.media for m in media.mentions}
    handles_b = {m.lower().lstrip("@") for media in profile_b.media for m in media.mentions}
    if profile_b.handle.lower() in handles_a:
        signals.add(f"{profile_a.handle} mentions @{profile_b.handle}")
    if profile_a.handle.lower() in handles_b:
        signals.add(f"{profile_b.handle} mentions @{profile_a.handle}")

    # co-sponsored brands
    brands_a: set[str] = set()
    brands_b: set[str] = set()
    for media in profile_a.media:
        if media.paid_partner_handle:
            brands_a.add(media.paid_partner_handle.lower())
    for media in profile_b.media:
        if media.paid_partner_handle:
            brands_b.add(media.paid_partner_handle.lower())
    shared_brands = brands_a & brands_b
    for brand in sorted(shared_brands):
        signals.add(f"co-sponsored: @{brand}")

    return list(signals)


def collaborated_edges(
    cohort: list[Profile],
    projects_dir: Path,
) -> list[dict]:
    """Compute collaboration edges from mutual mentions / co-sponsored brands."""
    features_map = {p.handle: _load_features(p, projects_dir) for p in cohort}

    edges: list[dict] = []
    handles = [p.handle for p in cohort]
    profile_map = {p.handle: p for p in cohort}

    for i, u in enumerate(handles):
        for v in handles[i + 1:]:
            pa, pb = profile_map[u], profile_map[v]
            fa, fb = features_map[u], features_map[v]
            sigs = _collaboration_signals(pa, fa, pb, fb)
            if sigs:
                weight = min(1.0, len(sigs) / 5.0)
                edges.append({
                    "u": u,
                    "v": v,
                    "edge_type": "collaborated",
                    "weight": round(weight, 4),
                    "method": "computed",
                    "signals": sigs,
                })
    return edges
