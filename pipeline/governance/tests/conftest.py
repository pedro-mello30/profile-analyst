"""Shared fixtures: fake adapters, enrichers, and a minimal EntityPool."""
from __future__ import annotations

from types import SimpleNamespace

import pytest


def make_valid_enrichment_adapter(**overrides) -> SimpleNamespace:
    attrs = {
        "adapter_id": "test_enrichment",
        "display_name": "Test Enrichment Adapter",
        "requires": ["handle"],
        "produces": ["email", "domain"],
        "data_category": "PUBLIC_API",
        "tos_compliant": True,
        "robots_txt_policy": "N/A",
        "gdpr_basis": "LEGITIMATE_INTERESTS",
        "osint_risk": False,
        "tier": "fast",
        "rate_limit_rpm": 60,
        "timeout_s": 30.0,
    }
    attrs.update(overrides)
    return SimpleNamespace(**attrs)


def make_valid_discovery_adapter(**overrides) -> SimpleNamespace:
    attrs = {
        "adapter_id": "test_discovery",
        "display_name": "Test Discovery Adapter",
        "requires": ["handle"],
        "produces": ["youtube_handle", "twitter_handle"],
        "data_category": "PUBLIC_API",
        "tos_compliant": True,
        "robots_txt_policy": "N/A",
    }
    attrs.update(overrides)
    return SimpleNamespace(**attrs)


def make_valid_enricher(**overrides) -> SimpleNamespace:
    attrs = {
        "enricher_id": "test_enricher",
        "adapter_id": "test_enrichment",
        "min_confidence": 0.5,
    }
    attrs.update(overrides)
    return SimpleNamespace(**attrs)


class FakeEntity:
    def __init__(self, entity_type: str, value: str = "x", attribution_chain=None):
        self.type = entity_type
        self.value = value
        self.attribution_chain = attribution_chain if attribution_chain is not None else []


class FakeEntityPool:
    def __init__(self, entities=None):
        self._entities = list(entities or [])

    def __iter__(self):
        return iter(self._entities)

    def add(self, entity):
        self._entities.append(entity)
