"""Stage 3 FEATURES — deterministic + LLM feature extraction (spec §5).

The LLM slice is produced by a pluggable backend (``anthropic`` | ``ollama``), selected by
``LLM_BACKEND`` (spec 0003). The deterministic features, schema gate, and compliance checks below
run identically regardless of backend (spec 0003 §7 C6).
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jsonschema

from pipeline.compliance import (
    assert_within_retention,
    strip_forbidden_features,
    assert_demographic_inference_humility,
    Art9Scanner,
)
from pipeline.llm import FeatureRequest, OllamaError, get_llm_backend
from pipeline.scoring_utils import TIER_BENCHMARK_ER, clamp, follower_tier, _ratio_reasonableness

logger = logging.getLogger(__name__)

_SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "03-features.schema.json"

_EXPLICIT_SPONSORED_PATTERNS = re.compile(
    r"#ad\b|#sponsored\b|#gifted\b|#collab\b|#partner\b"
    r"|thanks\s+to\s+@?\w+|sponsored\s+by|in\s+collaboration\s+with",
    re.IGNORECASE,
)

_HASHTAG_SPONSORED = {"ad", "sponsored", "gifted", "collab", "partner"}


def _load_schema() -> dict:
    with open(_SCHEMA_PATH) as fh:
        return json.load(fh)


# ── Deterministic feature computation (spec §5.1, §5.2) ─────────────────────

def _compute_er_by_followers(media: list[dict], followers: int) -> float | None:
    if followers == 0 or not media:
        return None
    total_eng = sum(
        (m.get("likes") or 0) + (m.get("comments") or 0)
        + (m.get("saves") or 0) + (m.get("shares") or 0)
        for m in media
    )
    return round((total_eng / len(media) / followers) * 100, 4)


def _compute_er_by_views(media: list[dict]) -> float | None:
    video_posts = [m for m in media if m.get("views")]
    if not video_posts:
        return None
    num = sum((m.get("likes") or 0) + (m.get("comments") or 0) + (m.get("shares") or 0)
               for m in video_posts)
    den = sum(m["views"] for m in video_posts)
    return round((num / den) * 100, 4) if den else None


def _compute_posting_stats(media: list[dict]) -> dict[str, Any]:
    """Compute frequency per week, consistency score, avg interval."""
    if len(media) < 2:
        return {
            "posting_frequency_per_week": None,
            "posting_consistency_score": None,
            "avg_post_interval_hours": None,
        }
    timestamps = []
    for m in media:
        try:
            dt = datetime.fromisoformat(m["posted_at"].replace("Z", "+00:00"))
            timestamps.append(dt)
        except Exception:
            continue
    if len(timestamps) < 2:
        return {
            "posting_frequency_per_week": None,
            "posting_consistency_score": None,
            "avg_post_interval_hours": None,
        }
    timestamps.sort(reverse=True)
    intervals_hours = [
        (timestamps[i] - timestamps[i + 1]).total_seconds() / 3600
        for i in range(len(timestamps) - 1)
    ]
    avg_interval = sum(intervals_hours) / len(intervals_hours)
    span_days = (timestamps[0] - timestamps[-1]).total_seconds() / 86400
    freq_per_week = (len(timestamps) / span_days * 7) if span_days > 0 else None

    if avg_interval > 0:
        mean_i = avg_interval
        variance = sum((x - mean_i) ** 2 for x in intervals_hours) / len(intervals_hours)
        std_i = math.sqrt(variance)
        consistency = round(max(0.0, 1.0 - std_i / mean_i), 4)
    else:
        consistency = 1.0

    return {
        "posting_frequency_per_week": round(freq_per_week, 2) if freq_per_week else None,
        "posting_consistency_score": consistency,
        "avg_post_interval_hours": round(avg_interval, 2),
    }


def _compute_hashtag_fingerprint(media: list[dict], top_n: int = 15) -> list[str]:
    counts: dict[str, int] = {}
    for m in media:
        for tag in m.get("hashtags", []):
            tag_lower = tag.lower()
            if tag_lower not in _HASHTAG_SPONSORED:
                counts[tag_lower] = counts.get(tag_lower, 0) + 1
    return [tag for tag, _ in sorted(counts.items(), key=lambda x: -x[1])[:top_n]]


def _compute_sponsored_pass1(media: list[dict]) -> list[str]:
    """Pass 1 — rule-based sponsored detection."""
    sponsored = []
    for m in media:
        if m.get("is_paid_partnership"):
            sponsored.append(m["media_id"])
            continue
        hashtags = {h.lower() for h in m.get("hashtags", [])}
        if hashtags & _HASHTAG_SPONSORED:
            sponsored.append(m["media_id"])
            continue
        caption = m.get("caption") or ""
        if _EXPLICIT_SPONSORED_PATTERNS.search(caption):
            sponsored.append(m["media_id"])
    return sponsored


def _compute_account_completeness(raw_profile: dict) -> float:
    score = 0.0
    if raw_profile.get("bio"):
        score += 0.4
    if raw_profile.get("website"):
        score += 0.3
    if raw_profile.get("display_name"):
        score += 0.2
    if raw_profile.get("is_verified"):
        score += 0.1
    return round(score, 2)


def _build_deterministic_features(
    raw_profile: dict,
    media: list[dict],
    followers: int,
    following: int,
) -> list[dict]:
    tier = follower_tier(followers)
    er = _compute_er_by_followers(media, followers)
    er_views = _compute_er_by_views(media)
    posting = _compute_posting_stats(media)
    comments_avg = (
        round(sum(m.get("comments") or 0 for m in media) / len(media), 2)
        if media else None
    )
    ratio = round(followers / max(following, 1), 4)
    completeness = _compute_account_completeness(raw_profile)
    fingerprint = _compute_hashtag_fingerprint(media)
    sponsored_pass1 = _compute_sponsored_pass1(media)
    estimated_reach = round(followers * (er / 100), 0) if er else None

    features: list[dict] = [
        {
            "feature_id": "er_by_followers",
            "value": er,
            "unit": "percent",
            "confidence": 1.0,
            "method": "computed",
            "art9_risk": False,
            "signals": ["likes", "comments", "saves", "shares", "followers"],
            "notes": None,
        },
        {
            "feature_id": "er_by_views",
            "value": er_views,
            "unit": "percent",
            "confidence": 1.0 if er_views is not None else 0.0,
            "method": "computed",
            "art9_risk": False,
            "signals": ["likes", "comments", "shares", "views"],
            "notes": "null when no video posts with views data" if er_views is None else None,
        },
        {
            "feature_id": "comments_per_post_avg",
            "value": comments_avg,
            "unit": "count",
            "confidence": 1.0 if comments_avg is not None else 0.0,
            "method": "computed",
            "art9_risk": False,
            "signals": ["comments", "post_count"],
            "notes": None,
        },
        {
            "feature_id": "follower_tier",
            "value": tier,
            "unit": None,
            "confidence": 1.0,
            "method": "computed",
            "art9_risk": False,
            "signals": [f"followers={followers}"],
            "notes": None,
        },
        {
            "feature_id": "follower_following_ratio",
            "value": ratio,
            "unit": "ratio",
            "confidence": 1.0,
            "method": "computed",
            "art9_risk": False,
            "signals": ["followers", "following"],
            "notes": None,
        },
        {
            "feature_id": "posting_frequency_per_week",
            "value": posting["posting_frequency_per_week"],
            "unit": "posts/week",
            "confidence": 1.0 if posting["posting_frequency_per_week"] is not None else 0.0,
            "method": "computed",
            "art9_risk": False,
            "signals": ["post timestamps", "media window span"],
            "notes": None,
        },
        {
            "feature_id": "posting_consistency_score",
            "value": posting["posting_consistency_score"],
            "unit": "score_0_1",
            "confidence": 1.0 if posting["posting_consistency_score"] is not None else 0.0,
            "method": "computed",
            "art9_risk": False,
            "signals": ["std(intervals)/mean(intervals)"],
            "notes": None,
        },
        {
            "feature_id": "avg_post_interval_hours",
            "value": posting["avg_post_interval_hours"],
            "unit": "hours",
            "confidence": 1.0 if posting["avg_post_interval_hours"] is not None else 0.0,
            "method": "computed",
            "art9_risk": False,
            "signals": ["post timestamps"],
            "notes": None,
        },
        {
            "feature_id": "estimated_reach_per_post",
            "value": estimated_reach,
            "unit": "users",
            "confidence": 0.6,
            "method": "inferred",
            "art9_risk": False,
            "signals": ["followers", "er_by_followers"],
            "notes": "followers × (er_by_followers / 100); rough estimate",
        },
        {
            "feature_id": "account_completeness_score",
            "value": completeness,
            "unit": "score_0_1",
            "confidence": 1.0,
            "method": "computed",
            "art9_risk": False,
            "signals": ["bio", "website", "display_name", "is_verified"],
            "notes": None,
        },
        {
            "feature_id": "hashtag_fingerprint",
            "value": fingerprint,
            "unit": None,
            "confidence": 1.0,
            "method": "computed",
            "art9_risk": False,
            "signals": ["hashtag frequency across media"],
            "notes": None,
        },
        {
            "feature_id": "sponsored_posts",
            "value": sponsored_pass1,
            "unit": None,
            "confidence": 1.0,
            "method": "computed",
            "art9_risk": False,
            "signals": ["is_paid_partnership flag", "#ad/#sponsored/#gifted hashtags", "caption patterns"],
            "notes": "Pass 1 rule-based detection",
        },
    ]
    return features


# ── LLM call (spec §5.3, §5.4, §5.5; backend swap — spec 0003 §4.0) ───────────

def _extract_llm_features(normalized: dict, *, anthropic_client: Any) -> list[dict]:
    """Run the configured LLM backend, falling back to Anthropic on an unreachable Ollama host.

    Backend selection is by ``LLM_BACKEND`` (default ``anthropic``). When the Ollama daemon is
    unreachable (``OllamaError``) and ``ASK_FALLBACK=true``, fall back to the Anthropic backend and
    log it (spec 0003 §4.0, A8). Other failures (invalid JSON, schema violation) propagate.
    """
    backend_name = os.environ.get("LLM_BACKEND", "anthropic")
    backend = get_llm_backend(backend_name, anthropic_client=anthropic_client)
    req = FeatureRequest(normalized=normalized)
    try:
        return backend.extract_features(req).features
    except OllamaError as exc:
        fallback = os.environ.get("ASK_FALLBACK", "true").strip().lower() == "true"
        if backend.name() == "ollama" and fallback:
            logger.warning(
                "Ollama backend unreachable (%s); falling back to Anthropic for Stage 3.", exc
            )
            anthropic = get_llm_backend("anthropic", anthropic_client=anthropic_client)
            return anthropic.extract_features(req).features
        raise


def _compute_ftc_status(
    sponsored_pass1: list[str],
    likely_undisclosed: list[str],
    total_posts: int,
) -> str:
    if total_posts < 3:
        return "unknown"
    if likely_undisclosed:
        disclosed = len(sponsored_pass1)
        total_commercial = len(sponsored_pass1) + len(likely_undisclosed)
        ratio = disclosed / total_commercial if total_commercial else 1.0
        return "compliant" if ratio >= 1.0 else "partial" if ratio >= 0.5 else "at_risk"
    if not sponsored_pass1:
        return "unknown"
    return "compliant"


# ── Orchestrator ──────────────────────────────────────────────────────────────

def run(handle: str, project_dir: Path, *, anthropic_client: Any = None) -> Path:
    """Run Stage 3 for *handle*, reading 02-normalized.json and writing 03-features.json."""
    norm_path = project_dir / "02-normalized.json"
    if not norm_path.exists():
        raise FileNotFoundError(f"Stage 2 artifact not found: {norm_path}")

    with open(norm_path) as fh:
        normalized = json.load(fh)

    gov = normalized.get("governance", {})
    assert_within_retention(gov, handle=handle)

    media = normalized.get("media", [])
    followers = normalized.get("followers", 0)
    following = normalized.get("following", 0)

    # Step 2: deterministic features
    det_features = _build_deterministic_features(normalized, media, followers, following)

    # Step 3: LLM features (pluggable backend — spec 0003 §4.0)
    llm_features = _extract_llm_features(normalized, anthropic_client=anthropic_client)

    # Step 4: merge + compliance
    all_features = det_features + llm_features
    all_features, dropped = strip_forbidden_features(all_features)
    if dropped:
        import warnings
        warnings.warn(f"Dropped forbidden features: {dropped}")
    assert_demographic_inference_humility(all_features)
    scanner = Art9Scanner()
    scanner.enforce(all_features)

    # Derive FTC status from LLM output
    sponsored_pass1 = next(
        (f["value"] for f in det_features if f["feature_id"] == "sponsored_posts"), []
    )
    likely_undisclosed = next(
        (f["value"] for f in llm_features if f["feature_id"] == "likely_sponsored_undisclosed"),
        [],
    )
    if isinstance(likely_undisclosed, list):
        pass
    else:
        likely_undisclosed = []

    ftc_status = _compute_ftc_status(sponsored_pass1, likely_undisclosed, len(media))
    # Ensure ftc_disclosure_status feature exists (LLM should emit it; add if missing)
    if not any(f["feature_id"] == "ftc_disclosure_status" for f in all_features):
        all_features.append({
            "feature_id": "ftc_disclosure_status",
            "value": ftc_status,
            "unit": None,
            "confidence": 0.85,
            "method": "computed",
            "art9_risk": False,
            "signals": ["sponsored_posts", "likely_sponsored_undisclosed", "post_count"],
            "notes": None,
        })

    # Step 5: validate against schema
    doc = {
        "profile_handle": handle,
        "computed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ftc_disclosure_status": ftc_status,
        "features": all_features,
    }
    schema = _load_schema()
    jsonschema.validate(doc, schema)

    # Step 6: atomic write
    out_path = project_dir / "03-features.json"
    tmp_path = out_path.with_suffix(".tmp")
    with open(tmp_path, "w") as fh:
        json.dump(doc, fh, indent=2)
    os.replace(tmp_path, out_path)

    return out_path
