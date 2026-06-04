"""Session-scoped setup: seed projects/sample_creator/02-normalized.json from the
committed test fixture so Stage 4 e2e tests work in a clean worktree.
"""
import shutil
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent.parent / "fixtures" / "02-normalized.json"
PROJECTS_ROOT = Path(__file__).parent.parent.parent / "projects"


@pytest.fixture(autouse=True, scope="session")
def stage4_normalized_artifact():
    dst = PROJECTS_ROOT / "sample_creator" / "02-normalized.json"
    if not dst.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(FIXTURE, dst)
