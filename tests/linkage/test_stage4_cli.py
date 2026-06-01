"""Unit tests for Stage 4 CLI wiring (spec 0011 T19)."""
import pytest

import profile_analyst as pa


def test_parse_stages_all_excludes_stage4():
    stages = pa._parse_stages("all")
    assert "4" not in stages


def test_parse_stages_explicit_4_includes_stage4():
    stages = pa._parse_stages("4")
    assert "4" in stages


def test_stage_map_has_stage4():
    assert "4" in pa.STAGE_MAP


def test_stage_map_stage4_is_callable():
    assert callable(pa.STAGE_MAP["4"])


