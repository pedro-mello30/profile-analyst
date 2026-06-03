"""Entity model for the enrichment engine (spec 0014 §3)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Callable
from urllib.parse import urlparse, urlunparse


class InvalidEntityTypeError(ValueError):
    pass


@dataclass(frozen=True)
class EntityTypeSpec:
    name: str
    pattern: re.Pattern
    normalizer: Callable[[str], str]
    example: str
    osint_risk: bool


# ── Normalizer helpers ────────────────────────────────────────────────────────

def _norm_handle(v: str) -> str:
    return re.sub(r"^[@u/]+", "", v.strip()).lower()

def _norm_url(v: str) -> str:
    p = urlparse(v.strip())
    return urlunparse((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"), "", "", ""))

def _norm_email(v: str) -> str:
    return v.strip().lower()

def _norm_gmail(v: str) -> str:
    v = v.strip().lower()
    if not v.endswith("@gmail.com"):
        raise ValueError(f"gmail entity must end with @gmail.com, got {v!r}")
    return v

def _norm_domain(v: str) -> str:
    v = v.strip().lower()
    if v.startswith("www."):
        v = v[4:]
    return v

def _norm_lower(v: str) -> str:
    return v.strip().lower()

def _norm_strip(v: str) -> str:
    return v.strip()

def _norm_upper(v: str) -> str:
    return v.strip().upper()

def _norm_cnpj(v: str) -> str:
    digits = re.sub(r"\D", "", v)
    if len(digits) != 14:
        raise ValueError(f"CNPJ must have 14 digits, got {len(digits)}: {v!r}")
    return digits

def _norm_phone(v: str) -> str:
    digits = re.sub(r"[^\d+]", "", v.strip())
    if not digits.startswith("+"):
        digits = "+" + digits
    return digits

def _norm_yt_handle(v: str) -> str:
    v = v.strip().lower()
    if not v.startswith("@"):
        v = "@" + v
    return v

def _norm_at_handle(v: str) -> str:
    v = v.strip().lower()
    v = v.lstrip("@")
    return "@" + v

def _norm_spotify(v: str) -> str:
    v = v.strip()
    if v.startswith("spotify:artist:"):
        return v
    return f"spotify:artist:{v}"

def _norm_linkedin(v: str) -> str:
    v = v.strip()
    if not v.startswith("http"):
        v = "https://linkedin.com/in/" + v
    return _norm_url(v)

def _norm_substack(v: str) -> str:
    v = v.strip().lower()
    if not v.endswith("/"):
        return v
    return v.rstrip("/")


# ── Registry builder ──────────────────────────────────────────────────────────

def _spec(pattern: str, normalizer: Callable, example: str, osint_risk: bool) -> dict:
    return dict(pattern=re.compile(pattern), normalizer=normalizer,
                example=example, osint_risk=osint_risk)


_RAW: dict[str, dict] = {
    "handle":             _spec(r"^[a-z0-9._]{1,64}$",             _norm_handle,   "filipelauar",               False),
    "display_name":       _spec(r"^.+$",                           _norm_strip,    "Filipe Lauar",               False),
    "bio_url":            _spec(r"^https?://.+$",                  _norm_url,      "https://linktr.ee/x",        False),
    "email":              _spec(r"^[^@]+@[^@]+\.[^@]+$",           _norm_email,    "a@b.com",                    True),
    "gmail":              _spec(r"^[^@]+@gmail\.com$",             _norm_gmail,    "a@gmail.com",                True),
    "domain":             _spec(r"^[a-z0-9.-]+\.[a-z]{2,}$",      _norm_domain,   "vidacomia.com",              False),
    "subdomain":          _spec(r"^[a-z0-9.-]+\.[a-z0-9.-]+\.[a-z]{2,}$", _norm_lower, "blog.vida.com",         False),
    "youtube_channel_id": _spec(r"^UC[a-zA-Z0-9_-]{22}$",         _norm_strip,    "UCxyz1234567890123456789",   False),
    "youtube_handle":     _spec(r"^@[a-zA-Z0-9._-]{3,30}$",       _norm_yt_handle,"@vidacomia",                 False),
    "tiktok_handle":      _spec(r"^@[a-zA-Z0-9._]{1,24}$",        _norm_at_handle,"@filipe",                    False),
    "twitter_handle":     _spec(r"^@[a-zA-Z0-9_]{1,15}$",         _norm_at_handle,"@filipe",                    False),
    "instagram_handle":   _spec(r"^[a-z0-9._]{1,30}$",            _norm_handle,   "filipelauar",                False),
    "linkedin_url":       _spec(r"^https?://[a-z.]*linkedin\.com/in/[^/]+/?$", _norm_linkedin, "https://linkedin.com/in/x", False),
    "github_handle":      _spec(r"^[a-z0-9-]{1,39}$",             _norm_lower,    "filipelauar",                False),
    "reddit_username":    _spec(r"^[a-zA-Z0-9_-]{3,20}$",         _norm_handle,   "filipelauar",                False),
    "twitch_handle":      _spec(r"^[a-z0-9_]{4,25}$",             _norm_lower,    "filipelauar",                False),
    "spotify_artist_id":  _spec(r"^spotify:artist:[a-zA-Z0-9]+$", _norm_spotify,  "spotify:artist:abc",         False),
    "podcast_url":        _spec(r"^https?://.+$",                  _norm_url,      "https://pod.example.com",   False),
    "podcast_itunes_id":  _spec(r"^\d{6,12}$",                    _norm_strip,    "1234567890",                 False),
    "substack_url":       _spec(r"^https://[a-z0-9-]+\.substack\.com$", _norm_substack, "https://foo.substack.com", False),
    "website_url":        _spec(r"^https?://.+$",                  _norm_url,      "https://vidacomia.com",     False),
    "wikidata_id":        _spec(r"^Q\d+$",                         _norm_upper,    "Q12345",                     False),
    "cnpj":               _spec(r"^\d{14}$",                       _norm_cnpj,     "12345678000190",             True),
    "phone":              _spec(r"^\+\d{10,15}$",                  _norm_phone,    "+5531999912345",             True),
}

ENTITY_TYPES: dict[str, EntityTypeSpec] = {
    k: EntityTypeSpec(name=k, **v) for k, v in _RAW.items()
}


# ── Entity dataclass ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Entity:
    type: str
    value: str
    source: str
    confidence: float
    depth: int
    discovered_at: str

    def __post_init__(self):
        if self.type not in ENTITY_TYPES:
            raise InvalidEntityTypeError(f"Unknown entity type: {self.type!r}")
        # Clamp confidence silently
        if not (0.0 <= self.confidence <= 1.0):
            object.__setattr__(self, "confidence", max(0.0, min(1.0, self.confidence)))
        if self.depth < 0:
            raise ValueError(f"depth must be >= 0, got {self.depth}")
        try:
            datetime.fromisoformat(self.discovered_at.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            raise ValueError(f"discovered_at must be UTC ISO 8601, got {self.discovered_at!r}")
        spec = ENTITY_TYPES[self.type]
        try:
            normalized = spec.normalizer(self.value)
        except Exception:
            normalized = None
        if normalized != self.value:
            raise ValueError(
                f"Entity value {self.value!r} is not normalized for type {self.type!r}. "
                f"Apply ENTITY_TYPES['{self.type}'].normalizer() first."
                + (f" Expected: {normalized!r}" if normalized is not None else "")
            )


def make_entity(
    entity_type: str,
    raw_value: str,
    *,
    source: str,
    confidence: float,
    depth: int,
    discovered_at: str | None = None,
) -> Entity:
    """Normalize raw_value and construct a validated Entity."""
    from datetime import timezone
    if entity_type not in ENTITY_TYPES:
        raise InvalidEntityTypeError(f"Unknown entity type: {entity_type!r}")
    if discovered_at is None:
        discovered_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    spec = ENTITY_TYPES[entity_type]
    normalized = spec.normalizer(raw_value)
    return Entity(
        type=entity_type, value=normalized, source=source,
        confidence=confidence, depth=depth, discovered_at=discovered_at,
    )
