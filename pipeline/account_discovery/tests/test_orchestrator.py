"""Tests for the discovery orchestrator (spec-0018 §3 AC4)."""
import json
from pathlib import Path
from pipeline.account_discovery.orchestrator import discover
from pipeline.account_discovery.contracts import DiscoveryAdapter
from pipeline.account_discovery.models import AttributionStep, DiscoveredAccount
from datetime import datetime, timezone

NOW = datetime.now(timezone.utc)


class FakeBioParser(DiscoveryAdapter):
    adapter_id = "bio_parser_orch"; display_name = "Bio"
    requires = ["bio_text"]; produces = ["platform_handle"]
    priority = 1; timeout_s = 1.0; retry_max = 0
    data_category = "PUBLIC_API"; tos_compliant = True; robots_txt_policy = "N/A"

    def run(self, seed_entities, config):
        for e in seed_entities:
            if getattr(e, "type", "") == "bio_text":
                return [DiscoveredAccount(
                    account_id="yt-creator", platform="youtube", handle="creator",
                    profile_url="https://youtube.com/creator",
                    confidence=0.9, method="test", source_adapter_id="bio_parser_orch",
                    attribution_chain=[AttributionStep("bio_parser_orch","bio_text","bio","mention")],
                    discovered_at=NOW,
                )]
        return []


def test_discover_writes_artifact(tmp_path):  # AC4 — no stage artifacts needed
    manifest = discover("creator123", [FakeBioParser()],
                        bio_text="youtube.com/creator", output_dir=tmp_path)
    assert (tmp_path / "00-discovery.json").exists()
    doc = json.loads((tmp_path / "00-discovery.json").read_text())
    assert doc["seed_handle"] == "creator123"
    assert len(doc["discovered_accounts"]) >= 1


def test_governance_block_in_artifact(tmp_path):
    discover("creator123", [FakeBioParser()],
             bio_text="youtube.com/creator", output_dir=tmp_path)
    doc = json.loads((tmp_path / "00-discovery.json").read_text())
    assert "governance" in doc


def test_runs_without_output_dir():  # AC4
    manifest = discover("creator", [FakeBioParser()], bio_text="youtube.com/test")
    assert manifest.seed_handle == "creator"
    assert manifest.governance is not None  # governance always populated


def test_stats_populated():
    manifest = discover("creator", [FakeBioParser()], bio_text="github.com/test")
    assert manifest.stats.elapsed_s >= 0
    assert isinstance(manifest.stats.accounts_found, int)
