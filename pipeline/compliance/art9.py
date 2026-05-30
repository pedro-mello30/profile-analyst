"""Art.9 scanner — defense-in-depth re-assertion of special-category data flags (spec §9.1)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class Art9Category(Enum):
    HEALTH = "HEALTH"
    SEXUALITY = "SEXUALITY"
    RELIGION = "RELIGION"
    POLITICAL = "POLITICAL"


# feature_ids that are categorically Art.9-adjacent regardless of value
ART9_SENSITIVE_FEATURE_IDS: set[str] = {
    "caption_sentiment",
}

# niche values that imply Art.9 risk by category (case-insensitive)
ART9_NICHE_VALUES: dict[Art9Category, set[str]] = {
    Art9Category.HEALTH: {
        "fitness/health", "fitness", "health", "wellness", "mental health",
        "chronic illness", "disability", "nutrition", "diet",
    },
    Art9Category.SEXUALITY: {
        "lgbtq", "lgbtq+", "queer", "pride", "sexuality",
    },
    Art9Category.RELIGION: {
        "religion", "faith", "christianity", "islam", "judaism", "hinduism",
        "buddhism", "spirituality",
    },
    Art9Category.POLITICAL: {
        "politics", "political", "activism", "social justice", "feminism",
        "climate", "environment",
    },
}

# compiled regex patterns to scan value / notes strings
ART9_TEXT_PATTERNS: dict[Art9Category, re.Pattern] = {
    Art9Category.HEALTH: re.compile(
        r"\b(health|fitness|wellness|chronic|illness|disability|diagnos|medical|mental[\s-]health|diet|nutrition)\b",
        re.IGNORECASE,
    ),
    Art9Category.SEXUALITY: re.compile(
        r"\b(lgbtq\+?|queer|pride|gay|lesbian|bisexual|transgender|sexuality|sexual[\s-]orientation)\b",
        re.IGNORECASE,
    ),
    Art9Category.RELIGION: re.compile(
        r"\b(religion|religious|faith|christian|muslim|jewish|hindu|buddhist|spiritual|pray|worship)\b",
        re.IGNORECASE,
    ),
    Art9Category.POLITICAL: re.compile(
        r"\b(politic|activist|activism|feminist|feminism|climate[\s-]change|environment|social[\s-]justice)\b",
        re.IGNORECASE,
    ),
}


@dataclass
class Art9Finding:
    feature_id: str
    categories: list[Art9Category]
    reason: str


class Art9Scanner:
    def scan_feature(self, feature: dict) -> Art9Finding | None:
        """Return an Art9Finding if the feature triggers any Art.9 category, else None."""
        fid = feature.get("feature_id", "")
        categories: list[Art9Category] = []
        reasons: list[str] = []

        # 1. Categorical match on feature_id
        if fid in ART9_SENSITIVE_FEATURE_IDS:
            # caption_sentiment may reveal political/religious/health views
            categories.append(Art9Category.HEALTH)
            categories.append(Art9Category.POLITICAL)
            categories.append(Art9Category.RELIGION)
            reasons.append(f"feature_id '{fid}' is categorically Art.9-adjacent")

        # 2. Value-level niche match
        val = feature.get("value", "")
        if isinstance(val, str):
            val_lower = val.lower()
            for cat, niche_set in ART9_NICHE_VALUES.items():
                if val_lower in niche_set:
                    if cat not in categories:
                        categories.append(cat)
                    reasons.append(f"value '{val}' matches {cat.value} niche lexicon")
            # 3. Text-pattern scan on value
            for cat, pattern in ART9_TEXT_PATTERNS.items():
                if pattern.search(val):
                    if cat not in categories:
                        categories.append(cat)
                    reasons.append(f"value text matches {cat.value} pattern")

        # 4. Text-pattern scan on notes
        notes = feature.get("notes") or ""
        if isinstance(notes, str) and notes:
            for cat, pattern in ART9_TEXT_PATTERNS.items():
                if pattern.search(notes):
                    if cat not in categories:
                        categories.append(cat)
                    reasons.append(f"notes text matches {cat.value} pattern")

        # 5. Check list values (e.g. secondary_niches)
        if isinstance(val, list):
            for item in val:
                if isinstance(item, str):
                    item_lower = item.lower()
                    for cat, niche_set in ART9_NICHE_VALUES.items():
                        if item_lower in niche_set:
                            if cat not in categories:
                                categories.append(cat)
                            reasons.append(f"list value '{item}' matches {cat.value} niche lexicon")
                    for cat, pattern in ART9_TEXT_PATTERNS.items():
                        if pattern.search(item):
                            if cat not in categories:
                                categories.append(cat)
                            reasons.append(f"list value text matches {cat.value} pattern")

        if not categories:
            return None
        return Art9Finding(
            feature_id=fid,
            categories=categories,
            reason="; ".join(reasons),
        )

    def sweep(self, features: list[dict]) -> list[Art9Finding]:
        """Return Art9Findings for all features that trigger Art.9."""
        return [f for feat in features if (f := self.scan_feature(feat)) is not None]

    def enforce(self, features: list[dict]) -> list[str]:
        """Force art9_risk=True on any Art.9-triggering feature. Returns affected feature_ids."""
        affected: list[str] = []
        for feat in features:
            finding = self.scan_feature(feat)
            if finding:
                feat["art9_risk"] = True
                affected.append(feat.get("feature_id", ""))
        return affected
