"""Content analysis and diagnostic classifiers for Layer 3 Creator Diagnostics (spec 0016 §6)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from pipeline.models import (
    ThemeMix,
    TopicEntry,
    ContentFormatMix,
    EditorialConsistencyScore,
    LabeledInterpretation,
    CreatorSizeField,
    BrandFitEntry,
    RiskFlag,
    DerivedInsights,
    DerivedDiagnostics,
    ContentAnalysis,
    DossierScore,
)

# ── T6: Constants and lookup tables ──────────────────────────────────────────

_NOISE_TAGS: frozenset[str] = frozenset({
    "fyp",
    "viral",
    "trending",
    "explore",
    "reels",
    "instagram",
    "instagood",
    "love",
    "follow",
    "like",
    "share",
    "foryou",
    "foryoupage",
    "photooftheday",
    "picoftheday",
})

_STOP_WORDS: frozenset[str] = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "up", "about", "into", "through",
    "is", "was", "are", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did",
    "will", "would", "could", "should", "may", "might", "must", "shall", "can",
    "not", "no", "nor", "so", "yet", "both", "either", "each",
    "few", "more", "most", "other", "some", "such",
    "than", "then", "there", "this", "that", "these", "those",
    "what", "which", "who", "when", "where", "why", "how",
    "all", "any",
    "he", "she", "it", "they", "we", "you", "i",
    "me", "my", "our", "your", "his", "her", "its", "their", "us", "him",
})

_HASHTAG_THEME: dict[str, str] = {
    # ai_tools
    "ai": "ai_tools",
    "chatgpt": "ai_tools",
    "openai": "ai_tools",
    "llm": "ai_tools",
    "gpt": "ai_tools",
    "aiagents": "ai_tools",
    "artificialintelligence": "ai_tools",
    "machinelearning": "ai_tools",
    "deeplearning": "ai_tools",
    # automation
    "automation": "automation",
    # tech_general
    "tech": "tech_general",
    "technology": "tech_general",
    "programming": "tech_general",
    "coding": "tech_general",
    # fitness
    "fitness": "fitness",
    "workout": "fitness",
    "gym": "fitness",
    "homeworkout": "fitness",
    "fitlife": "fitness",
    "exercise": "fitness",
    # health
    "health": "health",
    "healthy": "health",
    # wellness
    "wellness": "wellness",
    # nutrition
    "nutrition": "nutrition",
    "diet": "nutrition",
    # food
    "food": "food",
    "recipe": "food",
    "cooking": "food",
    "mealprep": "food",
    "healthyfood": "food",
    "healthyeating": "food",
    # lifestyle
    "lifestyle": "lifestyle",
    "motivation": "lifestyle",
    "mindset": "lifestyle",
    # travel
    "travel": "travel",
    "wanderlust": "travel",
    "adventure": "travel",
    # fashion
    "fashion": "fashion",
    "style": "fashion",
    "ootd": "fashion",
    # beauty
    "beauty": "beauty",
    "makeup": "beauty",
    "skincare": "beauty",
    # finance
    "finance": "finance",
    "investing": "finance",
    "crypto": "finance",
    "money": "finance",
    "personalfinance": "finance",
    # education
    "education": "education",
    "learning": "education",
    "study": "education",
}


# ── T7: compute_content_format_mix ───────────────────────────────────────────

def compute_content_format_mix(media_items: list[dict]) -> ContentFormatMix | None:
    """Compute the distribution of media formats across all media items.

    Returns None for empty input. Values are proportions summing to 1.0.
    """
    if not media_items:
        return None

    counts: dict[str, int] = {}
    for item in media_items:
        media_type = (item.get("media_type") or "").lower()
        counts[media_type] = counts.get(media_type, 0) + 1

    total = len(media_items)
    values = {k: v / total for k, v in counts.items()}
    return ContentFormatMix(values=values, method="computed")


# ── T8: compute_theme_mix ────────────────────────────────────────────────────

def compute_theme_mix(media_items: list[dict]) -> ThemeMix | None:
    """Map post hashtags to themes via the static lookup table.

    Per-post proportion: values[theme] = posts_with_theme / total_posts.
    unmapped_ratio = unmapped non-noise hashtag count / total non-noise hashtag count.
    confidence = 1.0 - unmapped_ratio.

    Returns None for empty input.
    """
    if not media_items:
        return None

    total_posts = len(media_items)
    # theme → set of media_ids that carry ≥1 hashtag mapped to that theme
    theme_posts: dict[str, set[str]] = {}
    total_mapped = 0
    total_unmapped = 0
    total_raw = 0

    for idx, item in enumerate(media_items):
        media_id = str(item.get("media_id") or idx)
        hashtags = [h.lower() for h in (item.get("hashtags") or [])]
        total_raw += len(hashtags)
        non_noise = [h for h in hashtags if h not in _NOISE_TAGS]

        for tag in non_noise:
            theme = _HASHTAG_THEME.get(tag)
            if theme is not None:
                total_mapped += 1
                theme_posts.setdefault(theme, set()).add(media_id)
            else:
                total_unmapped += 1

    total_non_noise = total_mapped + total_unmapped
    if total_non_noise > 0:
        unmapped_ratio = total_unmapped / total_non_noise
    elif total_raw > 0:
        # All hashtags were noise — spec §5.5: unmapped_ratio=1.0, confidence=0.0
        unmapped_ratio = 1.0
    else:
        unmapped_ratio = 0.0

    confidence = 1.0 - unmapped_ratio
    values = {theme: len(post_ids) / total_posts for theme, post_ids in theme_posts.items()}

    return ThemeMix(
        values=values,
        unmapped_ratio=unmapped_ratio,
        confidence=confidence,
        method="heuristic",
        version="v1",
    )


# ── T9: compute_editorial_consistency ────────────────────────────────────────

def compute_editorial_consistency(
    theme_mix: ThemeMix | None,
) -> EditorialConsistencyScore | None:
    """Derive thematic concentration score (0–100) from a ThemeMix.

    score = int(round(max_concentration * mapped_ratio * 100)), clamped to [0, 100].
    Returns None when theme_mix is None.
    Returns value=0 when theme_mix.values is empty.
    """
    if theme_mix is None:
        return None

    if not theme_mix.values:
        return EditorialConsistencyScore(value=0, method="heuristic")

    max_concentration = max(theme_mix.values.values())
    mapped_ratio = 1.0 - theme_mix.unmapped_ratio
    raw = max_concentration * mapped_ratio * 100
    score = max(0, min(100, int(round(raw))))
    return EditorialConsistencyScore(value=score, method="heuristic")


# ── T10: compute_top_topics ───────────────────────────────────────────────────

def compute_top_topics(media_items: list[dict], top_n: int = 10) -> list[TopicEntry]:
    """Identify the most-discussed topics from captions and hashtags.

    Tokens are:
      - non-noise hashtags of length ≥ 3 (lowercased)
      - caption words of length ≥ 4 that are not stop words (lowercased)

    share = posts_with_token / total_posts.
    evidence_media_ids = sorted(post_ids)[:5].

    Returns [] for empty input.
    """
    if not media_items:
        return []

    total_posts = len(media_items)
    # token → set of media_ids where token appears
    topic_posts: dict[str, set[str]] = {}

    for idx, item in enumerate(media_items):
        media_id = str(item.get("media_id") or idx)

        # Hashtag tokens
        for h in (item.get("hashtags") or []):
            token = h.lower()
            if token not in _NOISE_TAGS and len(token) >= 3:
                topic_posts.setdefault(token, set()).add(media_id)

        # Caption word tokens
        caption = item.get("caption", "") or ""
        for word in caption.split():
            token = word.lower()
            if len(token) >= 4 and token not in _STOP_WORDS:
                topic_posts.setdefault(token, set()).add(media_id)

    # Sort by share descending (then alphabetically for deterministic tie-breaking), take top_n
    ranked = sorted(
        topic_posts.items(),
        key=lambda kv: (-len(kv[1]), kv[0]),
    )[:top_n]

    return [
        TopicEntry(
            topic=token,
            share=len(post_ids) / total_posts,
            evidence_media_ids=sorted(post_ids)[:5],
        )
        for token, post_ids in ranked
    ]


# ── T11: Niche taxonomy constants ─────────────────────────────────────────────

_PROFESSIONAL_NICHES: frozenset[str] = frozenset({
    "AI/Technology", "Technology", "Finance", "Business", "Education",
    "Science", "Health", "Medicine", "Law", "Marketing", "Engineering",
})

_ENTERTAINMENT_NICHES: frozenset[str] = frozenset({
    "Entertainment", "Gaming", "Comedy", "Music", "Dance", "Sports",
})

_LIFESTYLE_NICHES: frozenset[str] = frozenset({
    "Lifestyle", "Fashion", "Beauty", "Travel", "Food/Cooking",
    "Fitness/Health", "Home/Garden", "Parenting",
})

_TIER_TO_SIZE: dict[str, str] = {
    "Nano": "nano", "Micro": "micro", "Mid": "mid",
    "Macro": "macro", "Mega": "mega",
}

_TIER_TO_LIFECYCLE_BASE: dict[str, str] = {
    "Nano": "nascent", "Micro": "early_growth", "Mid": "scaling",
    "Macro": "established", "Mega": "mature",
}


# ── T12: classify_creator_archetype ───────────────────────────────────────────

def classify_creator_archetype(
    niche: str,
    niche_conf: float,
    freq: float,
    editorial_consistency: int,
    commercial_ratio: float,
    er_vs_benchmark_ratio: float,
) -> LabeledInterpretation:
    """Classify creator archetype from niche, posting behaviour and commercial signals.

    Priority-ordered rules (first match wins).
    """
    # Rule 1: specialist_educator
    if (
        niche in _PROFESSIONAL_NICHES
        and editorial_consistency >= 70
        and commercial_ratio < 0.20
    ):
        return LabeledInterpretation(
            value="specialist_educator",
            confidence=min(0.95, niche_conf * 0.90),
            method="rule_based",
            version="v1",
            evidence=["niche_professional", "high_editorial_consistency"],
            matched_rule="specialist_educator_v1_r1",
        )

    # Rule 2: thought_leader
    if (
        niche in _PROFESSIONAL_NICHES
        and freq < 2.0
        and er_vs_benchmark_ratio >= 1.2
    ):
        return LabeledInterpretation(
            value="thought_leader",
            confidence=min(0.95, niche_conf * 0.85),
            method="rule_based",
            version="v1",
            evidence=["niche_professional", "low_posting_frequency", "high_er_ratio"],
            matched_rule="thought_leader_v1_r1",
        )

    # Rule 3: brand_builder
    if commercial_ratio >= 0.20:
        return LabeledInterpretation(
            value="brand_builder",
            confidence=min(0.95, niche_conf * 0.90),
            method="rule_based",
            version="v1",
            evidence=["high_commercial_ratio"],
            matched_rule="brand_builder_v1_r1",
        )

    # Rule 4: entertainer
    if niche in _ENTERTAINMENT_NICHES and freq >= 5.0:
        return LabeledInterpretation(
            value="entertainer",
            confidence=min(0.95, niche_conf * 0.85),
            method="rule_based",
            version="v1",
            evidence=["niche_entertainment", "high_posting_frequency"],
            matched_rule="entertainer_v1_r1",
        )

    # Rule 5: lifestyle_blogger
    if niche in _LIFESTYLE_NICHES:
        return LabeledInterpretation(
            value="lifestyle_blogger",
            confidence=min(0.95, niche_conf * 0.85),
            method="rule_based",
            version="v1",
            evidence=["niche_lifestyle"],
            matched_rule="lifestyle_blogger_v1_r1",
        )

    # Rule 6: fallback
    return LabeledInterpretation(
        value="content_creator",
        confidence=0.50,
        method="rule_based",
        version="v1",
        evidence=["no_dominant_signal"],
        matched_rule="content_creator_v1_fallback",
    )


# ── T13: classify_creator_size ────────────────────────────────────────────────

def classify_creator_size(tier: str) -> CreatorSizeField:
    """Pure lookup from follower tier to creator size label."""
    value = _TIER_TO_SIZE.get(tier, "unknown")
    return CreatorSizeField(value=value, method="computed")  # type: ignore[arg-type]


# ── T14: classify_lifecycle_stage ─────────────────────────────────────────────

def classify_lifecycle_stage(
    tier: str,
    consistency: float | None,
    er_vs_benchmark_ratio: float | None,
) -> LabeledInterpretation:
    """Classify creator lifecycle stage from tier, posting consistency, and ER ratio."""
    base_value = _TIER_TO_LIFECYCLE_BASE.get(tier, "nascent")
    value = base_value
    matched_rule: str = f"{base_value}_v1_base"
    evidence: list[str] = [f"follower_tier_{tier.lower()}"]

    # Override 1: plateaued
    if (
        er_vs_benchmark_ratio is not None
        and er_vs_benchmark_ratio < 0.5
        and tier != "Nano"
    ):
        value = "plateaued"
        matched_rule = "plateaued_v1_r1"
        evidence = ["low_er_vs_benchmark"]

    # Override 2: nascent (wins over override 1 for Micro with low consistency)
    if (
        tier == "Micro"
        and consistency is not None
        and consistency < 0.3
    ):
        value = "nascent_stalled"
        matched_rule = "nascent_stalled_v1_r1"
        evidence = ["low_posting_consistency"]

    # Confidence based on data availability
    has_er = er_vs_benchmark_ratio is not None
    has_cons = consistency is not None
    if has_er and has_cons:
        confidence = 0.80
    elif has_er or has_cons:
        confidence = 0.75
    else:
        confidence = 0.70

    return LabeledInterpretation(
        value=value,
        confidence=confidence,
        method="rule_based",
        version="v1",
        evidence=evidence,
        matched_rule=matched_rule,
    )


# ── T15: compute_sponsorship_readiness ────────────────────────────────────────

_FTC_SCORE: dict[str, int] = {
    "compliant": 100,
    "partial": 60,
    "unknown": 50,
    "at_risk": 0,
}


def compute_sponsorship_readiness(
    ftc_status: str,
    auth_score: float,
    brand_safety_score: float,
    consistency: float,
) -> LabeledInterpretation:
    """Classify sponsorship readiness from FTC compliance, authenticity, brand safety, and consistency."""
    # Hard override for at_risk FTC status
    if ftc_status == "at_risk":
        return LabeledInterpretation(
            value="low",
            confidence=0.90,
            method="score_derived",
            version="v1",
            evidence=["ftc_disclosure_at_risk"],
            matched_rule="low_v1_ftc_override",
        )

    ftc_contrib = _FTC_SCORE.get(ftc_status, 50)
    raw = (
        0.40 * auth_score
        + 0.30 * brand_safety_score
        + 0.20 * (consistency * 100)
        + 0.10 * ftc_contrib
    )

    evidence = [
        f"auth_score_{int(auth_score)}",
        f"brand_safety_{int(brand_safety_score)}",
        f"ftc_{ftc_status}",
    ]

    if raw >= 65:
        value = "high"
        matched_rule = "high_v1_r1"
    elif raw >= 40:
        value = "medium"
        matched_rule = "medium_v1_r1"
    else:
        value = "low"
        matched_rule = "low_v1_r1"

    confidence = min(0.95, 0.55 + 0.30 * (auth_score / 100) + 0.15 * (brand_safety_score / 100))

    return LabeledInterpretation(
        value=value,
        confidence=confidence,
        method="score_derived",
        version="v1",
        evidence=evidence,
        matched_rule=matched_rule,
    )


# ── T16: compute_brand_fit ────────────────────────────────────────────────────

@dataclass(frozen=True)
class _BrandFitDef:
    category: str
    fit: str        # "high" | "medium" | "low"
    base_confidence: float


_NICHE_BRAND_FIT: dict[str, list[_BrandFitDef]] = {
    "AI/Technology": [
        _BrandFitDef("ai_tools", "high", 0.95),
        _BrandFitDef("saas", "high", 0.88),
        _BrandFitDef("productivity_apps", "high", 0.82),
        _BrandFitDef("education", "high", 0.78),
        _BrandFitDef("tech_hardware", "medium", 0.70),
    ],
    "Technology": [
        _BrandFitDef("saas", "high", 0.88),
        _BrandFitDef("tech_hardware", "high", 0.82),
        _BrandFitDef("ai_tools", "high", 0.85),
    ],
    "Fitness/Health": [
        _BrandFitDef("activewear", "high", 0.90),
        _BrandFitDef("supplements", "high", 0.88),
        _BrandFitDef("health_apps", "high", 0.80),
        _BrandFitDef("wellness", "medium", 0.75),
    ],
    "Finance": [
        _BrandFitDef("fintech", "high", 0.88),
        _BrandFitDef("investment_apps", "high", 0.82),
        _BrandFitDef("insurance", "medium", 0.65),
    ],
    "Education": [
        _BrandFitDef("online_courses", "high", 0.90),
        _BrandFitDef("edtech", "high", 0.85),
        _BrandFitDef("books", "medium", 0.75),
    ],
    "Lifestyle": [
        _BrandFitDef("fmcg", "high", 0.80),
        _BrandFitDef("home_decor", "high", 0.78),
    ],
    "Fashion": [
        _BrandFitDef("fashion_brands", "high", 0.92),
        _BrandFitDef("beauty", "high", 0.85),
    ],
    "Beauty": [
        _BrandFitDef("beauty", "high", 0.95),
        _BrandFitDef("skincare", "high", 0.92),
    ],
    "Food/Cooking": [
        _BrandFitDef("food_brands", "high", 0.90),
        _BrandFitDef("kitchen_tools", "high", 0.85),
    ],
    "Travel": [
        _BrandFitDef("travel_brands", "high", 0.90),
        _BrandFitDef("hotels", "high", 0.85),
    ],
    "Gaming": [
        _BrandFitDef("gaming_hardware", "high", 0.92),
    ],
    "Entertainment": [
        _BrandFitDef("streaming_services", "high", 0.85),
    ],
}


def compute_brand_fit(
    primary_niche: str,
    primary_niche_conf: float,
    secondary_niches: list[str],
) -> list[BrandFitEntry]:
    """Compute brand fit entries from niche signals.

    Primary niche entries use full base_confidence * primary_niche_conf.
    Secondary niche entries apply a 0.60 discount on top.
    One entry per category; highest confidence wins when niches overlap.
    """
    # category -> (fit, confidence)
    best: dict[str, tuple[str, float]] = {}

    all_niches = [(primary_niche, 1.0)] + [(n, 0.60) for n in secondary_niches]

    for niche, discount in all_niches:
        for entry in _NICHE_BRAND_FIT.get(niche, []):
            conf = round(entry.base_confidence * primary_niche_conf * discount, 4)
            existing = best.get(entry.category)
            if existing is None or conf > existing[1]:
                best[entry.category] = (entry.fit, conf)

    # Sort descending by confidence
    sorted_entries = sorted(best.items(), key=lambda kv: -kv[1][1])

    return [
        BrandFitEntry(category=cat, fit=fit, confidence=conf, method="rule_based")  # type: ignore[arg-type]
        for cat, (fit, conf) in sorted_entries
    ]


# ── T17: compute_risk_flags ───────────────────────────────────────────────────

def compute_risk_flags(
    tier: str,
    pod_signal: str,
    ftc_status: str,
    brand_safety_score: float,
    auth_score: float,
    engagement_anomaly: str,
    freq: float,
) -> list[RiskFlag]:
    """Evaluate all 8 risk flags independently; multiple can fire simultaneously."""
    flags: list[RiskFlag] = []

    if tier == "Nano":
        flags.append(RiskFlag(
            flag="small_audience",
            severity="medium",
            method="rule_based",
            evidence=["follower_tier_nano"],
        ))

    if pod_signal == "detected":
        flags.append(RiskFlag(
            flag="engagement_pod_detected",
            severity="high",
            method="rule_based",
            evidence=["comment_pod_signal_detected"],
        ))

    if ftc_status == "at_risk":
        flags.append(RiskFlag(
            flag="ftc_risk",
            severity="high",
            method="rule_based",
            evidence=["ftc_disclosure_at_risk"],
        ))

    if ftc_status == "unknown":
        flags.append(RiskFlag(
            flag="unknown_commercial_history",
            severity="low",
            method="rule_based",
            evidence=["ftc_disclosure_unknown"],
        ))

    if brand_safety_score < 40:
        flags.append(RiskFlag(
            flag="low_brand_safety",
            severity="high",
            method="score_derived",
            evidence=[f"brand_safety_score_{int(brand_safety_score)}"],
        ))

    if auth_score < 40:
        flags.append(RiskFlag(
            flag="low_authenticity",
            severity="medium",
            method="score_derived",
            evidence=[f"authenticity_score_{int(auth_score)}"],
        ))

    if engagement_anomaly == "spike":
        flags.append(RiskFlag(
            flag="automation_signals",
            severity="high",
            method="rule_based",
            evidence=["engagement_anomaly_spike"],
        ))

    if freq < 1.0:
        flags.append(RiskFlag(
            flag="low_posting_frequency",
            severity="low",
            method="rule_based",
            evidence=[f"posting_frequency_{freq:.2f}_per_week"],
        ))

    return flags


# ── T18: Timestamp helper ─────────────────────────────────────────────────────

def _now_utc() -> str:
    """Return current UTC time as ISO-8601 string (e.g. '2026-06-03T10:00:00Z')."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── T18: DerivedInsights orchestrator ────────────────────────────────────────

def build_derived_insights(media_items: list[dict], feats: dict) -> DerivedInsights:
    """Compute content analysis insights from media items.

    Args:
        media_items: List of media item dicts from 02-normalized.json.
        feats: Feature index dict (accepted for API consistency; not used in v1).

    Returns:
        DerivedInsights with populated ContentAnalysis.
    """
    theme_mix = compute_theme_mix(media_items)
    editorial_consistency = compute_editorial_consistency(theme_mix)
    top_topics = compute_top_topics(media_items)
    format_mix = compute_content_format_mix(media_items)

    return DerivedInsights(
        computed_at=_now_utc(),
        content_analysis=ContentAnalysis(
            theme_mix=theme_mix,
            top_topics=top_topics,
            editorial_consistency_score=editorial_consistency,
            content_format_mix=format_mix,
        ),
    )


# ── T19: DerivedDiagnostics orchestrator ─────────────────────────────────────

from pipeline.scoring_utils import TIER_BENCHMARK_ER  # noqa: E402 — after models import


def build_derived_diagnostics(
    feats: dict,
    scores: dict,
    insights: DerivedInsights,
    tier: str,
    niche: str,
    niche_conf: float,
    secondary_niches: list[str],
    freq: float,
    consistency: float,
    ftc_status: str,
    pod_signal: str,
    engagement_anomaly: str,
    followers: int,
) -> DerivedDiagnostics:
    """Classify all diagnostic dimensions and return a DerivedDiagnostics object.

    Args:
        feats: Feature index dict from Stage 3.
        scores: Dict mapping score name → DossierScore (or plain int).
        insights: DerivedInsights produced by build_derived_insights.
        tier: Follower tier string (e.g. "Mid").
        niche: Primary niche label.
        niche_conf: Primary niche confidence (0.0–1.0).
        secondary_niches: List of secondary niche labels.
        freq: Posting frequency per week.
        consistency: Posting consistency score (0.0–1.0).
        ftc_status: FTC disclosure status string.
        pod_signal: Comment pod signal string.
        engagement_anomaly: Engagement anomaly classification string.
        followers: Follower count.

    Returns:
        DerivedDiagnostics with all classifier outputs populated.
    """
    # Engagement rate vs benchmark ratio
    er_val = feats.get("er_by_followers", {}).get("value")
    benchmark = TIER_BENCHMARK_ER.get(tier)
    if er_val is not None and benchmark:
        er_vs_benchmark_ratio = er_val / benchmark
    else:
        er_vs_benchmark_ratio = 1.0

    # Commercial content ratio — values may be counts (int) or lists of media IDs
    def _count(raw) -> int:
        if raw is None:
            return 0
        if isinstance(raw, list):
            return len(raw)
        return int(raw)

    sponsored = _count(feats.get("sponsored_posts", {}).get("value"))
    likely_undisclosed = _count(feats.get("likely_sponsored_undisclosed", {}).get("value"))
    total = max(1, feats.get("total_posts", {}).get("value") or 1)
    commercial_ratio = max(0.0, min(1.0, (sponsored + likely_undisclosed) / total))

    # Authenticity score
    _auth_raw = scores.get("authenticity", DossierScore(value=50, signals=["unavailable"], confidence=0.0))
    auth_score = float(_auth_raw.value if isinstance(_auth_raw, DossierScore) else _auth_raw)

    # Brand safety score
    _safety_raw = scores.get("brand_safety", DossierScore(value=50, signals=["unavailable"], confidence=0.0))
    brand_safety_score = float(_safety_raw.value if isinstance(_safety_raw, DossierScore) else _safety_raw)

    # Editorial consistency value
    _ec = insights.content_analysis.editorial_consistency_score
    editorial_consistency_val = _ec.value if _ec is not None else 50

    # Run all 6 classifiers
    archetype = classify_creator_archetype(
        niche, niche_conf, freq, editorial_consistency_val, commercial_ratio, er_vs_benchmark_ratio
    )
    size = classify_creator_size(tier)
    lifecycle = classify_lifecycle_stage(tier, consistency, er_vs_benchmark_ratio)
    readiness = compute_sponsorship_readiness(ftc_status, auth_score, brand_safety_score, consistency)
    brand_fit = compute_brand_fit(niche, niche_conf, secondary_niches)
    risk_flags = compute_risk_flags(
        tier, pod_signal, ftc_status, brand_safety_score, auth_score, engagement_anomaly, freq
    )

    return DerivedDiagnostics(
        computed_at=_now_utc(),
        creator_archetype=archetype,
        creator_size=size,
        lifecycle_stage=lifecycle,
        sponsorship_readiness=readiness,
        brand_fit=brand_fit,
        risk_flags=risk_flags,
    )
