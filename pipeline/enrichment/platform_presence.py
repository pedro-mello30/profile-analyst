"""Dossier cross-platform synthesis — Track B (spec 0015 §5.1).

Pure function: reads an enrichment_map dict and produces a PlatformPresenceBlock
with structured rows and a narrative paragraph.  No I/O, no side effects.
"""
from __future__ import annotations

from dataclasses import dataclass


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class PlatformRow:
    platform: str          # slug: "youtube", "podcast", "github", etc.
    handle_or_id: str      # display identifier
    key_metric: str        # assembled display string, e.g. "4,200 subscribers · 61 videos"
    confidence: float      # max confidence across contributing signals
    sources: list[str]     # sorted list of all contributing adapter IDs


@dataclass
class PlatformPresenceBlock:
    platforms_found: list[str]   # platform slugs with ≥1 qualifying row
    uplift_advisory: bool        # True when rows is non-empty
    rows: list[PlatformRow]      # one per platform, ordered by tier
    narrative: str               # human-readable paragraph for report.md


# ── Signal → Platform Mapping ────────────────────────────────────────────────

# Maps signal key → (platform_slug, metric_template).
# Order within this mapping determines assembly order for key_metric.
SIGNAL_MAP: dict[str, tuple[str, str]] = {
    "youtube_subscriber_count": ("youtube",  "{value:,} subscribers"),
    "youtube_video_count":      ("youtube",  "{value:,} videos"),
    "podcast_episode_count":    ("podcast",  "{value} episodes"),
    "podcast_last_episode_at":  ("podcast",  "Last: {value}"),
    "spotify_follower_count":   ("spotify",  "{value:,} followers"),
    "github_public_repos":      ("github",   "{value} public repos"),
    "github_followers":         ("github",   "{value} followers"),
    "twitch_follower_count":    ("twitch",   "{value:,} followers"),
    "reddit_karma_total":       ("reddit",   "{value:,} karma"),
    "substack_post_count":      ("substack", "{value} posts"),
}

# Maps signal key → platform slug, for handle/id resolution.
# Listed in preference order (first found wins per platform).
HANDLE_SIGNAL_MAP: dict[str, tuple[str, str]] = {
    "youtube_handle":      ("youtube",  "value"),
    "youtube_channel_id":  ("youtube",  "value"),
    "podcast_itunes_id":   ("podcast",  "itunes"),
    "spotify_artist_id":   ("spotify",  "value"),
    "github_handle":       ("github",   "value"),
    "twitch_handle":       ("twitch",   "value"),
    "reddit_username":     ("reddit",   "value"),
    "substack_url":        ("substack", "value"),
}

# Tier order for row ordering.  Lower index = higher tier.
_PLATFORM_TIER: list[str] = [
    "podcast", "youtube", "github", "substack", "spotify", "twitch", "reddit",
]


# ── Narrative templates ───────────────────────────────────────────────────────

PLATFORM_SENTENCES: dict[str, str] = {
    "podcast":  "Podcast: {count} episodes published (iTunes).",
    "youtube":  "YouTube: {subs} subscribers, {videos} videos.",
    "github":   "GitHub: {repos} public repos, {followers} followers.",
    "twitch":   "Twitch: {followers} followers.",
    "substack": "Substack: {posts} posts published.",
    "spotify":  "Spotify: {followers} followers.",
    "reddit":   "Reddit: {karma} karma.",
}


# ── Template rendering helpers ────────────────────────────────────────────────

def _render_metric(template: str, value: object) -> str | None:
    """Render a metric template, returning None on any failure."""
    try:
        return template.format(value=value)
    except (ValueError, KeyError, IndexError):
        return None


# Maps each platform's template variable names to their signal keys.
# Declared at module level so it is allocated once, not on every call.
_KEY_MAP: dict[str, dict[str, str]] = {
    "podcast":  {"count": "podcast_episode_count"},
    "youtube":  {"subs": "youtube_subscriber_count", "videos": "youtube_video_count"},
    "github":   {"repos": "github_public_repos", "followers": "github_followers"},
    "twitch":   {"followers": "twitch_follower_count"},
    "substack": {"posts": "substack_post_count"},
    "spotify":  {"followers": "spotify_follower_count"},
    "reddit":   {"karma": "reddit_karma_total"},
}


def _render_sentence(platform: str, signal_values: dict[str, object]) -> str | None:
    """Render a PLATFORM_SENTENCES entry for the given platform.

    Returns None if the platform has no template or a required placeholder
    is missing from signal_values.
    """
    template = PLATFORM_SENTENCES.get(platform)
    if template is None:
        return None

    mapping = _KEY_MAP.get(platform, {})
    kwargs: dict[str, object] = {}
    for var_name, sig_key in mapping.items():
        if sig_key not in signal_values:
            return None
        raw = signal_values[sig_key]
        # Format numbers with commas for narrative consistency.
        if isinstance(raw, (int, float)):
            kwargs[var_name] = f"{raw:,}"
        else:
            kwargs[var_name] = str(raw)[:7] if platform == "podcast" and var_name == "last" else str(raw)
    try:
        return template.format(**kwargs)
    except (KeyError, ValueError):
        return None


# Sentinel returned when there are no qualifying signals.
# Allocated once at module level; callers must not mutate the returned block.
_EMPTY = PlatformPresenceBlock(
    platforms_found=[], uplift_advisory=False, rows=[], narrative=""
)


def _tier_key(platform: str) -> tuple[int, str]:
    try:
        return (_PLATFORM_TIER.index(platform), "")
    except ValueError:
        return (len(_PLATFORM_TIER), platform)


# ── Extractor ─────────────────────────────────────────────────────────────────

class PlatformPresenceExtractor:
    """Pure, stateless extractor.  Call extract() directly."""

    @staticmethod
    def extract(
        enrichment_map: dict | None,
        *,
        expose_osint: bool = False,
        min_confidence: float = 0.7,
        handle: str = "This creator",
    ) -> PlatformPresenceBlock:
        """Read enrichment_map["signals"] and produce a PlatformPresenceBlock.

        Parameters
        ----------
        enrichment_map:
            The dict produced by the enrichment engine (spec 0014).  May be None.
        expose_osint:
            When False (default), signals with osint_risk=True are excluded.
        min_confidence:
            Signals with confidence strictly below this threshold are excluded.
        """
        if enrichment_map is None:
            return _EMPTY

        signals: list[dict] = enrichment_map.get("signals", [])

        # Step 1: collect qualifying metric signals, grouped by platform.
        # per_platform[slug] = list of (signal_key, signal_dict)
        per_platform: dict[str, list[tuple[str, dict]]] = {}
        for sig in signals:
            key = sig.get("key", "")
            if key not in SIGNAL_MAP:
                continue
            if sig.get("confidence", 0.0) < min_confidence:
                continue
            if sig.get("osint_risk", False) and not expose_osint:
                continue
            platform_slug = SIGNAL_MAP[key][0]
            per_platform.setdefault(platform_slug, []).append((key, sig))

        if not per_platform:
            return _EMPTY

        # Step 2: build handle lookup from ALL signals (any confidence).
        # handle_lookup[platform_slug] = display string
        handle_lookup: dict[str, str] = {}
        for sig in signals:
            key = sig.get("key", "")
            if key not in HANDLE_SIGNAL_MAP:
                continue
            platform_slug, fmt = HANDLE_SIGNAL_MAP[key]
            if platform_slug in handle_lookup:
                continue  # first found wins
            raw_value = str(sig.get("value", ""))
            if fmt == "itunes":
                handle_lookup[platform_slug] = f"{raw_value} (iTunes)"
            else:
                handle_lookup[platform_slug] = raw_value

        # Step 3: build one PlatformRow per platform.
        rows: list[PlatformRow] = []
        # signal_values_for_narrative: platform → {sig_key: value}
        signal_values_for_narrative: dict[str, dict[str, object]] = {}

        for platform_slug, sig_pairs in per_platform.items():
            # Assemble key_metric in SIGNAL_MAP order.
            fragments: list[str] = []
            sv: dict[str, object] = {}
            for sig_key in SIGNAL_MAP:  # iterate in declaration order
                if SIGNAL_MAP[sig_key][0] != platform_slug:
                    continue
                # find the matching signal (there may be multiple from different sources)
                matching = [s for (k, s) in sig_pairs if k == sig_key]
                if not matching:
                    continue
                # pick highest confidence among duplicates
                best_sig = max(matching, key=lambda s: s.get("confidence", 0.0))
                template = SIGNAL_MAP[sig_key][1]
                raw_val = best_sig.get("value")
                # Truncate full ISO timestamps to YYYY-MM for display.
                if sig_key == "podcast_last_episode_at":
                    raw_val = str(raw_val)[:7]
                rendered = _render_metric(template, raw_val)
                if rendered is not None:
                    fragments.append(rendered)
                sv[sig_key] = best_sig.get("value")

            key_metric = " · ".join(fragments)
            confidence = max(s.get("confidence", 0.0) for (_, s) in sig_pairs)
            sources = sorted({s.get("source", "") for (_, s) in sig_pairs})
            handle_or_id = handle_lookup.get(platform_slug, platform_slug)

            rows.append(PlatformRow(
                platform=platform_slug,
                handle_or_id=handle_or_id,
                key_metric=key_metric,
                confidence=confidence,
                sources=sources,
            ))
            signal_values_for_narrative[platform_slug] = sv

        # Step 4: sort rows by tier.
        rows.sort(key=lambda r: _tier_key(r.platform))

        # Step 5: build narrative.
        n_platforms = len(rows)
        intro = (
            f"{handle} has a confirmed presence on {n_platforms} "
            f"platform(s) beyond Instagram."
        )
        sentences: list[str] = [intro]
        for row in rows:
            sv = signal_values_for_narrative.get(row.platform, {})
            sentence = _render_sentence(row.platform, sv)
            if sentence is not None:
                sentences.append(sentence)
        narrative = "  ".join(sentences)

        return PlatformPresenceBlock(
            platforms_found=[r.platform for r in rows],
            uplift_advisory=len(rows) > 0,
            rows=rows,
            narrative=narrative,
        )
