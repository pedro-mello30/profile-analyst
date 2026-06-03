"""Content analysis and diagnostic classifiers for Layer 3 Creator Diagnostics (spec 0016)."""
from __future__ import annotations

from pipeline.models import ThemeMix, TopicEntry, ContentFormatMix, EditorialConsistencyScore

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
    "all", "any", "both",
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
        media_type = item.get("media_type", "").lower()
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

    for item in media_items:
        media_id = str(item.get("media_id", ""))
        hashtags = [h.lower() for h in item.get("hashtags", [])]
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

    for item in media_items:
        media_id = str(item.get("media_id", ""))

        # Hashtag tokens
        for h in item.get("hashtags", []):
            token = h.lower()
            if token not in _NOISE_TAGS and len(token) >= 3:
                topic_posts.setdefault(token, set()).add(media_id)

        # Caption word tokens
        caption = item.get("caption", "") or ""
        for word in caption.split():
            token = word.lower()
            if len(token) >= 4 and token not in _STOP_WORDS:
                topic_posts.setdefault(token, set()).add(media_id)

    # Sort by share descending, take top_n
    ranked = sorted(
        topic_posts.items(),
        key=lambda kv: len(kv[1]),
        reverse=True,
    )[:top_n]

    return [
        TopicEntry(
            topic=token,
            share=len(post_ids) / total_posts,
            evidence_media_ids=sorted(post_ids)[:5],
        )
        for token, post_ids in ranked
    ]
