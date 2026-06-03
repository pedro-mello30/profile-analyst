"""Stage 1 + Enrichment integration tests.

Verifies that --stage 1 automatically chains into Stage 1B enrichment,
while --stage 1b remains available as a standalone re-run path.
"""
from unittest.mock import patch, MagicMock

import profile_analyst as pa


class TestParseStagesAll:
    def test_all_excludes_1b_because_1_includes_it(self):
        """--stage all must not list '1b' separately; it is now bundled inside stage 1."""
        stages = pa._parse_stages("all")
        assert "1b" not in stages

    def test_all_includes_stage_1(self):
        """--stage all still runs stage 1 (which now bundles enrichment)."""
        stages = pa._parse_stages("all")
        assert "1" in stages


class TestStage1bStandalone:
    def test_1b_still_available_standalone(self):
        """--stage 1b must remain runnable for re-processing without re-fetching."""
        stages = pa._parse_stages("1b")
        assert "1b" in stages

    def test_stage_map_has_1b(self):
        """'1b' must remain a key in STAGE_MAP."""
        assert "1b" in pa.STAGE_MAP

    def test_stage_map_1b_is_callable(self):
        assert callable(pa.STAGE_MAP["1b"])


class TestStage1AutoChain:
    def test_stage1_triggers_enrichment(self, tmp_path, monkeypatch):
        """Running _run_stage1 must automatically invoke Stage 1B enrichment."""
        monkeypatch.setattr(pa, "PROJECTS_ROOT", tmp_path)

        with patch("pipeline.stage1_ingest.run") as mock_ingest, \
             patch("pipeline.stage1b_enrichment.run") as mock_enrich:
            raw_path = tmp_path / "sample_creator" / "01-raw.json"
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.touch()
            mock_ingest.return_value = raw_path
            mock_enrich.return_value = tmp_path / "sample_creator" / "enrichment_map.json"

            pa._run_stage1("sample_creator")

        mock_enrich.assert_called_once()

    def test_stage1_enrichment_uses_same_handle_and_project_dir(self, tmp_path, monkeypatch):
        """Stage 1B must be called with the same handle and project_dir that was ingested."""
        monkeypatch.setattr(pa, "PROJECTS_ROOT", tmp_path)

        with patch("pipeline.stage1_ingest.run") as mock_ingest, \
             patch("pipeline.stage1b_enrichment.run") as mock_enrich:
            raw_path = tmp_path / "test_handle" / "01-raw.json"
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.touch()
            mock_ingest.return_value = raw_path
            mock_enrich.return_value = tmp_path / "test_handle" / "enrichment_map.json"

            pa._run_stage1("test_handle")

        call_args = mock_enrich.call_args
        assert call_args[0][0] == "test_handle"
        assert call_args[0][1] == tmp_path / "test_handle"
