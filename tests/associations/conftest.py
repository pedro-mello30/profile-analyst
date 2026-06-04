"""Session-scoped setup: seed ≥ 2 normalized profiles so Stage 5 cohort tests work
in a clean worktree. Copies the committed tests/fixtures/02-normalized.json for the
ego handle, and synthesises a second profile entry for the cohort minimum.
"""
import json
import shutil
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent.parent / "fixtures" / "02-normalized.json"
PROJECTS_ROOT = Path(__file__).parent.parent.parent / "projects"


@pytest.fixture(autouse=True, scope="session")
def stage5_cohort_artifacts():
    # Primary ego: sample_creator
    primary_dst = PROJECTS_ROOT / "sample_creator" / "02-normalized.json"
    if not primary_dst.exists():
        primary_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(FIXTURE, primary_dst)

    # Second profile: pedromellob (required for cohort ≥ 2)
    second_dst = PROJECTS_ROOT / "pedromellob" / "02-normalized.json"
    if not second_dst.exists():
        second_dst.parent.mkdir(parents=True, exist_ok=True)
        data = json.loads(FIXTURE.read_text())
        data["handle"] = "pedromellob"
        data["profile_id"] = "9999999999"
        second_dst.write_text(json.dumps(data))
