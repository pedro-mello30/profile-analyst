"""Stage 7 LOAD tests — spec-0002 full acceptance-criteria coverage.

DB-free tests (compliance gate, missing files, env-var bypass, A8 validate) run always.
DB-backed tests (A1-A7) use FakeGraphSession when no live Neo4j is reachable.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from pipeline.compliance import ComplianceError
from pipeline.stage7_load import run
from pipeline.graph import queries
from tests.graph.conftest import FIXTURE_ROOT, write_normalized


# ── §4.1: required artifacts (DB-free) ───────────────────────────────────────────

class TestMissingArtifacts:
    def test_missing_normalized_raises(self, tmp_path):
        """02-normalized.json absent → FileNotFoundError before any DB connection."""
        shutil.copy(FIXTURE_ROOT / "03-features.json", tmp_path / "03-features.json")
        shutil.copy(FIXTURE_ROOT / "06-dossier.json", tmp_path / "06-dossier.json")
        with pytest.raises(FileNotFoundError, match="02-normalized"):
            run("sample_creator", tmp_path)

    def test_missing_features_raises(self, tmp_path):
        """03-features.json absent → FileNotFoundError before any DB connection."""
        shutil.copy(FIXTURE_ROOT / "02-normalized.json", tmp_path / "02-normalized.json")
        shutil.copy(FIXTURE_ROOT / "06-dossier.json", tmp_path / "06-dossier.json")
        with pytest.raises(FileNotFoundError, match="03-features"):
            run("sample_creator", tmp_path)

    def test_missing_dossier_raises(self, tmp_path):
        """06-dossier.json absent → FileNotFoundError before any DB connection."""
        shutil.copy(FIXTURE_ROOT / "02-normalized.json", tmp_path / "02-normalized.json")
        shutil.copy(FIXTURE_ROOT / "03-features.json", tmp_path / "03-features.json")
        with pytest.raises(FileNotFoundError, match="06-dossier"):
            run("sample_creator", tmp_path)


# ── A5: compliance gate (no DB required — gate runs before any connection) ──────

class TestComplianceGate:
    def test_missing_governance_blocks(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ALLOW_NONCOMPLIANT", raising=False)
        write_normalized(tmp_path, drop_governance=True)
        shutil.copy(FIXTURE_ROOT / "03-features.json", tmp_path / "03-features.json")
        shutil.copy(FIXTURE_ROOT / "06-dossier.json", tmp_path / "06-dossier.json")
        with pytest.raises(ComplianceError):
            run("sample_creator", tmp_path)

    def test_allow_noncompliant_env_var_bypasses_gate(self, tmp_path, monkeypatch):
        """ALLOW_NONCOMPLIANT=true env var (not just the flag) bypasses the gate (C1)."""
        monkeypatch.setenv("ALLOW_NONCOMPLIANT", "true")
        write_normalized(tmp_path, drop_governance=True)
        shutil.copy(FIXTURE_ROOT / "03-features.json", tmp_path / "03-features.json")
        shutil.copy(FIXTURE_ROOT / "06-dossier.json", tmp_path / "06-dossier.json")
        # Should not raise — env var bypass takes effect without any DB connection needed
        from tests.graph.fake_session import FakeGraphSession
        out = run("sample_creator", tmp_path, session=FakeGraphSession())
        assert out.exists()


# ── A8: make validate passes (DB-free) ───────────────────────────────────────────

class TestValidateScript:
    def test_a8_validate_exits_zero(self):
        """tools/validate.py exits 0 — schemas including 07-graph-load.schema.json are valid."""
        result = subprocess.run(
            [sys.executable, "tools/validate.py"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr


# ── Integration: real graph (skips without Neo4j) ──────────────────────────────

def _creator_user_id() -> str:
    doc = json.loads((FIXTURE_ROOT / "02-normalized.json").read_text())
    return doc["profile_id"]


class TestLoadIntegration:
    def test_a1_creates_nodes_and_valid_manifest(self, project_dir, graph_session):
        out = run("sample_creator", project_dir, session=graph_session)
        manifest = json.loads(out.read_text())
        assert manifest["counts"]["nodes"]["Creator"] == 1
        assert manifest["counts"]["nodes"]["Media"] == 12
        assert manifest["counts"]["nodes"]["Signal"] >= 1
        # nodes actually exist
        rows = graph_session.read("MATCH (c:Creator) RETURN count(c) AS n")
        assert rows[0]["n"] == 1

    def test_a6_deferred_associations(self, project_dir, graph_session):
        out = run("sample_creator", project_dir, session=graph_session)
        manifest = json.loads(out.read_text())
        assert manifest["associations"] == "deferred"
        rows = graph_session.read("MATCH ()-[r:SHARES_AUDIENCE]->() RETURN count(r) AS n")
        assert rows[0]["n"] == 0

    def test_a2_idempotent_counts(self, project_dir, graph_session):
        run("sample_creator", project_dir, session=graph_session, run_id="run-1")

        def counts():
            n = graph_session.read("MATCH (n) RETURN count(n) AS c")[0]["c"]
            r = graph_session.read("MATCH ()-[x]->() RETURN count(x) AS c")[0]["c"]
            return n, r

        before = counts()
        run("sample_creator", project_dir, session=graph_session, run_id="run-1")
        after = counts()
        assert before == after

    def test_a7_versioning_supersedes(self, project_dir, graph_session):
        uid = _creator_user_id()
        # First run
        run("sample_creator", project_dir, session=graph_session, run_id="run-A")
        # Mutate a signal value, second run with a new run_id
        feats = json.loads((project_dir / "03-features.json").read_text())
        for f in feats["features"]:
            if f["feature_id"] == "er_by_followers":
                f["value"] = 99.9
        (project_dir / "03-features.json").write_text(json.dumps(feats))
        out = run("sample_creator", project_dir, session=graph_session, run_id="run-B")
        manifest = json.loads(out.read_text())
        assert manifest["superseded"]["signals"] >= 1

        # Only run-B signals remain
        rows = graph_session.read(
            "MATCH (s:Signal) RETURN DISTINCT s.run_id AS rid"
        )
        assert {r["rid"] for r in rows} == {"run-B"}
        # AQ1 reflects new run
        expl = queries.explain_score(graph_session, uid, "engagement_quality", "run-B")
        names = {s["signal"]: s["value"] for s in expl["signals"]}
        assert names["er_by_followers"] == 99.9

    def test_a5_gate_with_flag_loads(self, tmp_path, graph_session, monkeypatch):
        monkeypatch.delenv("ALLOW_NONCOMPLIANT", raising=False)
        write_normalized(tmp_path, drop_governance=True)
        shutil.copy(FIXTURE_ROOT / "03-features.json", tmp_path / "03-features.json")
        shutil.copy(FIXTURE_ROOT / "06-dossier.json", tmp_path / "06-dossier.json")
        out = run("sample_creator", tmp_path, session=graph_session, allow_noncompliant_flag=True)
        assert out.exists()

    def test_a6_associations_loaded_when_05_graph_present(self, tmp_path, graph_session):
        """A6 complementary: when 05-graph.json IS present manifest records associations: loaded."""
        for name in ("02-normalized.json", "03-features.json", "06-dossier.json"):
            shutil.copy(FIXTURE_ROOT / name, tmp_path / name)
        uid = _creator_user_id()
        graph_doc = {"audience_overlap": [
            {"source_user_id": uid, "target_user_id": "other", "overlap_pct": 0.5},
        ]}
        (tmp_path / "05-graph.json").write_text(json.dumps(graph_doc))
        out = run("sample_creator", tmp_path, session=graph_session)
        manifest = json.loads(out.read_text())
        assert manifest["associations"] == "loaded"
        assert manifest["counts"]["relationships"]["SHARES_AUDIENCE"] == 1
