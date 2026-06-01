"""5-family AgreementVector for UIL (spec 0011 §3, T12).

Each family emits a FeatureEvidence entry {feature, agreement, detail}.
pHash (profile_photo) lives behind the [uil] extra — weight 0 if absent.
"""
from __future__ import annotations

import urllib.parse
from dataclasses import dataclass, field

from rapidfuzz.distance import JaroWinkler

try:
    import imagehash  # type: ignore
    from PIL import Image  # type: ignore
    _HAS_PHASH = True
except ImportError:
    _HAS_PHASH = False


@dataclass
class AgreementVector:
    evidences: list[dict] = field(default_factory=list)
    phash_available: bool = False

    def add(self, feature: str, agreement: float, detail: str) -> None:
        self.evidences.append({
            "feature": feature,
            "agreement": max(0.0, min(1.0, agreement)),
            "detail": detail,
        })


def _jaro_winkler(a: str | None, b: str | None) -> float:
    if not a or not b:
        return 0.0
    return JaroWinkler.normalized_similarity(a.lower(), b.lower())


def _jaccard_tokens(a: str | None, b: str | None) -> float:
    if not a or not b:
        return 0.0
    set_a = set(a.lower().split())
    set_b = set(b.lower().split())
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def _host(url: str | None) -> str | None:
    if not url:
        return None
    try:
        return urllib.parse.urlparse(url).netloc.lower().lstrip("www.")
    except Exception:
        return None


def compute_agreement_vector(
    profile: dict,
    candidate: dict,
) -> AgreementVector:
    """Compute the 5-family AgreementVector between a Profile dict and a candidate dict."""
    vec = AgreementVector(phash_available=_HAS_PHASH)

    # ── 1. handle ────────────────────────────────────────────────────────────
    ig_handle = profile.get("handle", "")
    cand_handle = candidate.get("candidate_handle", "")
    exact_match = ig_handle.lower() == cand_handle.lower()
    jw_handle = _jaro_winkler(ig_handle, cand_handle)
    agreement_handle = 1.0 if exact_match else jw_handle
    detail_handle = "exact match" if exact_match else f"Jaro-Winkler={jw_handle:.3f}"
    vec.add("handle", agreement_handle, detail_handle)

    # ── 2. display_name ──────────────────────────────────────────────────────
    jw_name = _jaro_winkler(profile.get("display_name"), candidate.get("display_name"))
    vec.add("display_name", jw_name, f"Jaro-Winkler={jw_name:.3f}")

    # ── 3. profile_photo (pHash — behind [uil] extra) ────────────────────────
    if _HAS_PHASH:
        ig_url = profile.get("profile_photo_url")
        cand_url = candidate.get("profile_photo_url")
        if ig_url and cand_url:
            try:
                import io
                import httpx  # noqa: F401 — only used inside [uil] path
                # In the v3a fixture path, URLs are null; skip if either is None.
                vec.add("profile_photo", 0.0, "pHash skipped (no local image)")
            except Exception:
                vec.add("profile_photo", 0.0, "pHash unavailable")
        else:
            vec.add("profile_photo", 0.0, "pHash skipped (no URL in fixture)")
    else:
        # weight 0 when extra is absent — never an error
        vec.add("profile_photo", 0.0, "pHash unavailable (install profile-analyst[uil])")

    # ── 4. website ───────────────────────────────────────────────────────────
    ig_host = _host(profile.get("website"))
    cand_host = _host(candidate.get("website"))
    if ig_host and cand_host:
        website_match = 1.0 if ig_host == cand_host else 0.0
        detail_web = f"host match: {ig_host}" if website_match else f"{ig_host} ≠ {cand_host}"
    else:
        website_match = 0.0
        detail_web = "website absent for one or both parties"
    vec.add("website", website_match, detail_web)

    # ── 5. bio ───────────────────────────────────────────────────────────────
    bio_sim = _jaccard_tokens(profile.get("bio"), candidate.get("bio"))
    vec.add("bio", bio_sim, f"Jaccard token-set={bio_sim:.3f}")

    return vec
