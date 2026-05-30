"""Erasure + retention: idempotency, path-traversal guard, retention checks (spec §9.1)."""
import json
import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pipeline.compliance import (
    erase_profile,
    is_expired,
    assert_within_retention,
    gc_sweep,
    ComplianceError,
)


@pytest.fixture
def tmp_project(tmp_path):
    """Create a fake projects/test_user directory with a sentinel file."""
    handle = "test_user"
    pdir = tmp_path / handle
    pdir.mkdir()
    (pdir / "02-normalized.json").write_text("{}")
    (pdir / "01-raw.json").write_text("{}")
    return tmp_path, handle


class TestEraseProfile:
    def test_erase_deletes_directory(self, tmp_project):
        root, handle = tmp_project
        receipt = erase_profile(handle, projects_root=root)
        assert receipt.existed is True
        assert not (root / handle).exists()
        assert receipt.bytes_freed > 0

    def test_erase_idempotent(self, tmp_project):
        root, handle = tmp_project
        r1 = erase_profile(handle, projects_root=root)
        r2 = erase_profile(handle, projects_root=root)
        assert r1.existed is True
        assert r2.existed is False
        assert r2.bytes_freed == 0

    def test_dry_run_does_not_delete(self, tmp_project):
        root, handle = tmp_project
        receipt = erase_profile(handle, dry_run=True, projects_root=root)
        assert receipt.existed is True
        assert (root / handle).exists()  # still there

    def test_path_traversal_guard_slash(self):
        with pytest.raises(ComplianceError) as exc_info:
            erase_profile("foo/bar")
        assert "Unsafe handle" in str(exc_info.value)

    def test_path_traversal_guard_dotdot(self):
        with pytest.raises(ComplianceError):
            erase_profile("../etc")

    def test_path_traversal_guard_absolute(self):
        with pytest.raises(ComplianceError):
            erase_profile("/etc/passwd")


class TestRetention:
    def test_is_expired_past(self):
        past = "2020-01-01T00:00:00Z"
        assert is_expired(past) is True

    def test_is_expired_future(self):
        future = "2099-01-01T00:00:00Z"
        assert is_expired(future) is False

    def test_assert_within_retention_passes(self):
        gov = {"retention_expires_at": "2099-01-01T00:00:00Z"}
        assert_within_retention(gov, handle="test")  # should not raise

    def test_assert_within_retention_raises_expired(self):
        gov = {"retention_expires_at": "2020-01-01T00:00:00Z"}
        with pytest.raises(ComplianceError) as exc_info:
            assert_within_retention(gov, handle="test")
        assert "retention expired" in str(exc_info.value)


class TestGcSweep:
    def test_sweeps_expired_profiles(self, tmp_path):
        handle = "expired_user"
        pdir = tmp_path / handle
        pdir.mkdir()
        gov = {"retention_expires_at": "2020-01-01T00:00:00Z"}
        normalized = {"handle": handle, "governance": gov}
        (pdir / "02-normalized.json").write_text(json.dumps(normalized))

        receipts = gc_sweep(tmp_path)
        assert any(r.handle == handle for r in receipts)
        assert not (tmp_path / handle).exists()

    def test_does_not_sweep_valid_profiles(self, tmp_path):
        handle = "valid_user"
        pdir = tmp_path / handle
        pdir.mkdir()
        gov = {"retention_expires_at": "2099-01-01T00:00:00Z"}
        normalized = {"handle": handle, "governance": gov}
        (pdir / "02-normalized.json").write_text(json.dumps(normalized))

        receipts = gc_sweep(tmp_path)
        assert not any(r.handle == handle for r in receipts)
        assert (tmp_path / handle).exists()
