"""Acceptance tests spec-0018 AC1–AC7."""
import ast
from pathlib import Path
import pytest
from pipeline.account_discovery.orchestrator import discover
from pipeline.account_discovery.adapters.bio_parser import BioParsing
from pipeline.account_discovery.adapters.pattern_matcher import PatternMatcher


def test_ac1_bio_yields_non_instagram_account():
    """AC1: bio with YouTube URL → ≥1 DiscoveredAccount with platform ≠ instagram."""
    manifest = discover(
        "creator123", [BioParsing(), PatternMatcher()],
        bio_text="My YouTube: youtube.com/@Creator123Official",
    )
    non_ig = [a for a in manifest.discovered_accounts if a.platform != "instagram"]
    assert len(non_ig) >= 1, f"Expected non-instagram account, got: {manifest.discovered_accounts}"


def test_ac2_all_accounts_have_attribution_chain():
    """AC2: every DiscoveredAccount has a non-empty attribution_chain."""
    manifest = discover(
        "creator", [BioParsing(), PatternMatcher()],
        bio_text="github.com/creator123 tiktok.com/@creator",
    )
    for acc in manifest.discovered_accounts:
        assert len(acc.attribution_chain) > 0, f"{acc.account_id} has empty attribution_chain"


def test_ac3_new_adapter_pluggable():
    """AC3: adding a DiscoveryAdapter subclass is the only change needed for a new platform."""
    from pipeline.account_discovery.contracts import DiscoveryAdapter

    class MyNewAdapter(DiscoveryAdapter):
        adapter_id = "my_new"; display_name = "New"
        requires = ["instagram_handle"]; produces = ["platform_handle"]
        priority = 99; timeout_s = 1.0; retry_max = 0
        data_category = "OPEN_DATA"; tos_compliant = True; robots_txt_policy = "N/A"
        def run(self, s, c): return []

    manifest = discover("test", [MyNewAdapter()])
    assert manifest is not None  # no engine change needed


def test_ac4_runs_without_stage_artifacts(tmp_path):
    """AC4: discover() works with no 01-raw.json present."""
    assert not (tmp_path / "01-raw.json").exists()
    manifest = discover("test", [BioParsing()], bio_text="github.com/test", output_dir=tmp_path)
    assert (tmp_path / "00-discovery.json").exists()


def test_ac5_no_forbidden_imports():
    """AC5: pipeline/account_discovery/ has zero imports from pipeline.enrichment, etc."""
    forbidden = ("pipeline.enrichment", "pipeline.graph", "pipeline.stage", "pipeline.compliance")
    base = Path("pipeline/account_discovery")
    violations = []
    for py_file in base.rglob("*.py"):
        if "__pycache__" in str(py_file) or "test_" in py_file.name:
            continue
        try:
            tree = ast.parse(py_file.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for f in forbidden:
                    if node.module.startswith(f):
                        violations.append(f"{py_file}: from {node.module}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    for f in forbidden:
                        if alias.name.startswith(f):
                            violations.append(f"{py_file}: import {alias.name}")
    assert not violations, "Forbidden imports:\n" + "\n".join(violations)


def test_ac6_depth_limit_sets_limit_reached(tmp_path):
    """AC6: max_adapters=0 → manifest written with limit_reached=True, no exception."""
    from pipeline.account_discovery.scheduler import DiscoveryConfig
    cfg = DiscoveryConfig(max_adapters=0)
    manifest = discover("test", [BioParsing()], bio_text="github.com/t",
                        output_dir=tmp_path, config=cfg)
    assert manifest.limit_reached is True
    assert (tmp_path / "00-discovery.json").exists()


def test_ac7_dedup_merges_attribution():
    """AC7: same (platform, handle) from two adapters → one account, merged attribution_chain."""
    from pipeline.account_discovery.pool import AccountPool
    from pipeline.account_discovery.models import AttributionStep, DiscoveredAccount
    from datetime import datetime, timezone

    pool = AccountPool()
    now = datetime.now(timezone.utc)

    acc1 = DiscoveredAccount(
        account_id="yt-a", platform="youtube", handle="creator",
        profile_url="https://yt.com/c", confidence=0.8, method="bio",
        source_adapter_id="bio_parser",
        attribution_chain=[AttributionStep("bio_parser", "bio_text", "bio", "mention")],
        discovered_at=now,
    )
    acc2 = DiscoveredAccount(
        account_id="yt-a", platform="youtube", handle="creator",
        profile_url="https://yt.com/c", confidence=0.9, method="link",
        source_adapter_id="link_expander",
        attribution_chain=[AttributionStep("link_expander", "url", "linktr.ee/c", "link")],
        discovered_at=now,
    )
    pool.add(acc1)
    pool.add(acc2)
    assert len(pool) == 1, "Should have exactly one account after dedup"
    merged = pool.get("youtube", "creator")
    adapter_ids = {s.adapter_id for s in merged.attribution_chain}
    assert "bio_parser" in adapter_ids and "link_expander" in adapter_ids
