"""Unit tests for Stage 5 CLI wiring (spec 0012 T25)."""
import profile_analyst as pa


def test_parse_stages_all_excludes_stage5():
    stages = pa._parse_stages("all")
    assert "5" not in stages


def test_parse_stages_explicit_5_includes_stage5():
    stages = pa._parse_stages("5")
    assert "5" in stages


def test_stage_map_has_stage5():
    assert "5" in pa.STAGE_MAP


def test_stage_map_stage5_is_callable():
    assert callable(pa.STAGE_MAP["5"])
