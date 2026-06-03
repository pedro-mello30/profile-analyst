"""BioEntityExtractor — regex-based identity entity extraction from bio text.

Spec 0017 §4. Returns (entity_type, raw_value, confidence) tuples.
Does NOT call make_entity; deduplication is the caller's responsibility.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Module-level compiled regexes (never compiled inside extract())
# ---------------------------------------------------------------------------

_RE_EMAIL = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
)

# Formatted CNPJ: ##.###.###/####-##  → normalised to 14 digits
_RE_CNPJ_FMT = re.compile(
    r"\b(\d{2})\.(\d{3})\.(\d{3})/(\d{4})-(\d{2})\b",
)

# Raw 14-digit CNPJ (lower confidence); must NOT be part of a longer digit run
_RE_CNPJ_RAW = re.compile(
    r"(?<!\d)(\d{14})(?!\d)",
)

# +55-anchored Brazilian phone, 10–15 digits total (after stripping non-digits)
_RE_PHONE = re.compile(
    r"\+55[\s\-.]?\(?\d{2}\)?[\s\-.]?\d{4,5}[\s\-.]?\d{4}",
)

# URL (http/https)
_RE_URL = re.compile(
    r"https?://[^\s\"'<>]+",
)

# ---------------------------------------------------------------------------
# Skip domains (bio-link aggregators — already seeded via bio_url)
# ---------------------------------------------------------------------------

_SKIP_DOMAINS: frozenset[str] = frozenset({
    "linktr.ee",
    "linktree.com",
    "bio.link",
    "beacons.ai",
    "msha.ke",
    "campsite.bio",
    "carrd.co",
})


def _strip_www(netloc: str) -> str:
    if netloc.startswith("www."):
        return netloc[4:]
    return netloc


class BioEntityExtractor:
    """Extract identity entities from Instagram bio text and optional website URL."""

    def extract(
        self,
        bio: str | None,
        *,
        website: str | None = None,
    ) -> list[tuple[str, str, float]]:
        """Return ``[(entity_type, raw_value, confidence), ...]``.

        - ``None`` or empty *bio* with no *website* → ``[]``.
        - Deduplication is the caller's responsibility.
        """
        results: list[tuple[str, str, float]] = []

        # Build text sources to scan for URLs (bio text + explicit website param)
        bio_text: str = bio or ""

        # ── emails ────────────────────────────────────────────────────────────
        for m in _RE_EMAIL.finditer(bio_text):
            results.append(("email", m.group(0).lower(), 0.7))

        # Strip URLs before any CNPJ scan — prevents path segments from matching
        bio_no_urls = _RE_URL.sub(" ", bio_text)

        # ── CNPJ formatted ────────────────────────────────────────────────────
        for m in _RE_CNPJ_FMT.finditer(bio_no_urls):
            digits = re.sub(r"\D", "", m.group(0))
            results.append(("cnpj", digits, 0.85))

        # ── CNPJ raw 14-digit ─────────────────────────────────────────────────
        for m in _RE_CNPJ_RAW.finditer(bio_no_urls):
            results.append(("cnpj", m.group(1), 0.6))

        # ── phone ─────────────────────────────────────────────────────────────
        for m in _RE_PHONE.finditer(bio_text):
            # Normalise: strip everything except leading + and digits
            raw = m.group(0)
            digits_only = re.sub(r"[^\d+]", "", raw)
            results.append(("phone", digits_only, 0.6))

        # ── URLs (bio text + website field) ───────────────────────────────────
        url_sources: list[str] = []
        for m in _RE_URL.finditer(bio_text):
            raw_url = m.group(0).rstrip(".,;)!")
            url_sources.append(raw_url)
        if website:
            url_sources.append(website.rstrip(".,;)!"))

        for url in url_sources:
            results.append(("website_url", url, 0.9))
            parsed = urlparse(url)
            if not parsed.netloc or "." not in parsed.netloc:
                continue
            netloc = _strip_www(parsed.netloc.lower())
            if netloc and netloc not in _SKIP_DOMAINS:
                results.append(("domain", netloc, 0.9))

        return results
