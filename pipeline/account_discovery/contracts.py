"""Adapter contract for the account discovery engine (spec-0018 §5).

IMPORTANT: This module must remain stdlib-only. It must NOT import from
pipeline.enrichment, pipeline.compliance, pipeline.graph, or any stage module.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


# ---------------------------------------------------------------------------
# Closed vocabulary of valid entity type strings
# ---------------------------------------------------------------------------

ENTITY_TYPES: frozenset[str] = frozenset({
    "instagram_handle",
    "bio_text",
    "url",
    "platform_handle",
    "youtube_handle",
    "github_handle",
    "tiktok_handle",
    "twitter_handle",
    "twitch_handle",
    "spotify_handle",
    "reddit_handle",
    "substack_url",
    "linkedin_url",
    "facebook_url",
    "domain",
    "email",
})

# ---------------------------------------------------------------------------
# Closed vocabularies for constrained fields
# ---------------------------------------------------------------------------

_VALID_DATA_CATEGORIES: frozenset[str] = frozenset({
    "PUBLIC_API",
    "PUBLIC_SCRAPE",
    "OSINT",
    "OPEN_DATA",
})

_VALID_ROBOTS_POLICIES: frozenset[str] = frozenset({"RESPECT", "N/A"})

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class AdapterContractError(RuntimeError):
    """Raised at class-definition time when a DiscoveryAdapter violates its contract."""


class DiscoveryContractError(RuntimeError):
    """Raised at runtime when a discovery operation violates a contract invariant."""


# ---------------------------------------------------------------------------
# Abstract base class with import-time contract validation
# ---------------------------------------------------------------------------

_REQUIRED_ATTRS = (
    "adapter_id",
    "display_name",
    "requires",
    "produces",
    "priority",
    "timeout_s",
    "retry_max",
    "data_category",
    "tos_compliant",
    "robots_txt_policy",
)


class DiscoveryAdapter(ABC):
    """Base class for all account-discovery adapters.

    Contract is validated at class-definition (import) time via
    ``__init_subclass__``. Concrete subclasses that omit required class
    attributes, or supply out-of-vocabulary values, raise
    ``AdapterContractError`` immediately on import — not at runtime.
    """

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)

        # Skip validation for intermediate abstract classes.
        # NOTE: __abstractmethods__ is set by ABCMeta *after* __init_subclass__
        # returns, so we must compute it manually: collect all abstractmethods
        # declared in ancestor classes, subtract those overridden by cls, then
        # add any new abstractmethods declared by cls itself.
        parent_abstracts: set[str] = set()
        for parent in cls.__mro__[1:]:
            for name, val in parent.__dict__.items():
                if getattr(val, "__isabstractmethod__", False):
                    parent_abstracts.add(name)
        own_overrides = {
            name for name in parent_abstracts
            if name in cls.__dict__
            and not getattr(cls.__dict__[name], "__isabstractmethod__", False)
        }
        own_new_abstracts = {
            name for name, val in cls.__dict__.items()
            if getattr(val, "__isabstractmethod__", False)
        }
        remaining_abstracts = (parent_abstracts - own_overrides) | own_new_abstracts
        if remaining_abstracts:
            return

        errors: list[str] = []

        # 1. Required attribute presence
        for attr in _REQUIRED_ATTRS:
            if not hasattr(cls, attr):
                errors.append(f"missing required class attribute: {attr!r}")

        # 2. data_category vocabulary
        if hasattr(cls, "data_category") and cls.data_category not in _VALID_DATA_CATEGORIES:
            errors.append(
                f"data_category={cls.data_category!r} not in {sorted(_VALID_DATA_CATEGORIES)}"
            )

        # 3. robots_txt_policy vocabulary
        if hasattr(cls, "robots_txt_policy") and cls.robots_txt_policy not in _VALID_ROBOTS_POLICIES:
            errors.append(
                f"robots_txt_policy={cls.robots_txt_policy!r} not in {sorted(_VALID_ROBOTS_POLICIES)}"
            )

        # 4. requires entity types
        if hasattr(cls, "requires"):
            bad = [t for t in cls.requires if t not in ENTITY_TYPES]
            if bad:
                errors.append(f"requires contains unknown entity types: {bad}")

        # 5. produces entity types
        if hasattr(cls, "produces"):
            bad = [t for t in cls.produces if t not in ENTITY_TYPES]
            if bad:
                errors.append(f"produces contains unknown entity types: {bad}")

        if errors:
            raise AdapterContractError(
                f"Adapter {cls.__name__!r} has {len(errors)} contract violation(s):\n"
                + "\n".join(f"  • {e}" for e in errors)
            )

    @abstractmethod
    def run(self, seed_entities: list, config: object) -> list:
        """Execute the adapter and return a list of discovered accounts/relationships."""
        ...
