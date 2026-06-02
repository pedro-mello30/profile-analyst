"""Stage 6 — Platform Presence integration tests (spec 0015 Track D).

Tests T14–T18 covering: section rendering, absent enrichment_map, malformed
enrichment_map, osint-flag gating, and schema validity.
"""
from __future__ import annotations

import json
import logging
import shutil
import pytest
from pathlib import Path

FIXTURE_ROOT = Path(__file__).parent / "fixtures"

HANDLE = "sample"


# ── Fixture helpers ───────────────────────────────────────────────────────────

def _make_enrichment_map() -> dict:
    """Return a minimal valid enrichment_map with YouTube + Podcast signals."""
    return {
        "handle": "testcreator",
        "signals": [
            {
                "key": "youtube_subscriber_count",
                "value": 4200,
                "confidence": 1.0,
                "method": "api",
                "source": "youtube",
                "osint_risk": False,
            },
            {
                "key": "youtube_video_count",
                "value": 61,
                "confidence": 1.0,
                "method": "api",
                "source": "youtube",
                "osint_risk": False,
            },
            {
                "key": "podcast_episode_count",
                "value": 38,
                "confidence": 1.0,
                "method": "api",
                "source": "itunes",
                "osint_risk": False,
            },
        ],
        "compliance": {"osint_signals_present": False},
    }


@pytest.fixture
def project_with_stages(tmp_path):
    shutil.copy(FIXTURE_ROOT / "02-normalized.json", tmp_path / "02-normalized.json")
    shutil.copy(FIXTURE_ROOT / "03-features.json", tmp_path / "03-features.json")
    return tmp_path


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestPlatformPresenceSection:
    """T14 — valid enrichment_map → section 8 rendered in report + dossier."""

    def test_platform_presence_section_rendered(self, project_with_stages):
        from pipeline.stage6_dossier import run

        em = _make_enrichment_map()
        (project_with_stages / "enrichment_map.json").write_text(json.dumps(em))

        out = run(HANDLE, project_with_stages)

        report = (project_with_stages / "report.md").read_text()
        assert "## 8. Platform Presence" in report, "Section 8 heading missing from report"
        assert "YouTube" in report, "YouTube row missing from report"
        assert "Podcast" in report, "Podcast row missing from report"
        # Key metric strings
        assert "subscribers" in report, "'subscribers' not found in report"
        assert "38 episodes" in report, "'38 episodes' not found in report"

        dossier = json.loads(out.read_text())
        pp = dossier["platform_presence"]
        assert "youtube" in pp["platforms_found"], "youtube missing from platforms_found"
        assert "podcast" in pp["platforms_found"], "podcast missing from platforms_found"
        assert pp["uplift_advisory"] is True, "uplift_advisory should be True"
        assert len(pp["rows"]) == 2, f"Expected 2 rows, got {len(pp['rows'])}"


class TestAbsentEnrichmentMap:
    """T15 — absent enrichment_map → Stage 6 runs without section 8 (A4)."""

    def test_absent_enrichment_map_no_section(self, project_with_stages):
        from pipeline.stage6_dossier import run

        # Explicitly ensure there is no enrichment_map.json
        em_path = project_with_stages / "enrichment_map.json"
        assert not em_path.exists(), "enrichment_map.json should not exist for this test"

        out = run(HANDLE, project_with_stages)

        report = (project_with_stages / "report.md").read_text()
        assert "## 8. Platform Presence" not in report, (
            "Section 8 should be absent when enrichment_map.json is missing"
        )

        dossier = json.loads(out.read_text())
        pp = dossier["platform_presence"]
        assert pp["rows"] == [], f"Expected rows==[], got {pp['rows']}"
        assert pp["uplift_advisory"] is False, "uplift_advisory should be False"


class TestMalformedEnrichmentMap:
    """T16 — malformed enrichment_map → warning logged, rows=[] (A11)."""

    def test_malformed_enrichment_map_graceful(self, project_with_stages, caplog):
        from pipeline.stage6_dossier import run

        (project_with_stages / "enrichment_map.json").write_text("{ this is not valid json }")

        with caplog.at_level(logging.WARNING):
            out = run(HANDLE, project_with_stages)   # must not raise

        # Some WARNING mentioning the issue
        warning_texts = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        assert any(
            "malformed" in m.lower() or "enrichment_map" in m.lower()
            for m in warning_texts
        ), f"Expected warning about malformed enrichment_map; got: {warning_texts}"

        dossier = json.loads(out.read_text())
        assert dossier["platform_presence"]["rows"] == [], (
            "rows should be [] when enrichment_map is malformed"
        )


class TestOsintSignalGating:
    """T17 — osint_risk signal excluded by default; included with expose_osint=True (A6)."""

    def test_osint_signal_excluded_by_default(self, project_with_stages):
        from pipeline.stage6_dossier import run

        em = {
            "handle": "testcreator",
            "signals": [
                {
                    "key": "youtube_subscriber_count",
                    "value": 9999,
                    "confidence": 1.0,
                    "method": "osint",
                    "source": "osint_scraper",
                    "osint_risk": True,   # <-- OSINT-flagged signal
                },
            ],
            "compliance": {"osint_signals_present": True},
        }
        (project_with_stages / "enrichment_map.json").write_text(json.dumps(em))

        # Default: expose_osint=False → signal excluded → no section 8
        out_default = run(HANDLE, project_with_stages, expose_osint=False)
        report_default = (project_with_stages / "report.md").read_text()
        assert "## 8. Platform Presence" not in report_default, (
            "Section 8 should be absent when only signal has osint_risk=True and expose_osint=False"
        )

        # Explicit: expose_osint=True → signal included → section 8 present
        out_exposed = run(HANDLE, project_with_stages, expose_osint=True)
        report_exposed = (project_with_stages / "report.md").read_text()
        assert "## 8. Platform Presence" in report_exposed, (
            "Section 8 should appear when expose_osint=True"
        )


class TestSchemaValidation:
    """T18 — produced dossier validates against 06-dossier.schema.json."""

    def test_dossier_validates_against_schema(self, project_with_stages):
        import jsonschema
        from pipeline.stage6_dossier import run

        em = _make_enrichment_map()
        (project_with_stages / "enrichment_map.json").write_text(json.dumps(em))

        out = run(HANDLE, project_with_stages)
        dossier = json.loads(out.read_text())

        schema_path = Path(__file__).parent.parent / "schemas" / "06-dossier.schema.json"
        schema = json.loads(schema_path.read_text())

        jsonschema.validate(dossier, schema)   # raises on failure
