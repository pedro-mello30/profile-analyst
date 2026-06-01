"""Unit tests for uil_lia_gate (spec 0011 T16)."""
import os
import pytest

from pipeline.compliance.tos import UilLiaError, uil_lia_gate


def test_lia_gate_raises_without_env(monkeypatch):
    monkeypatch.delenv("LIA_FILE_PATH", raising=False)
    with pytest.raises(UilLiaError) as exc_info:
        uil_lia_gate("sample_creator")
    assert "sample_creator" in str(exc_info.value)


def test_lia_gate_raises_with_empty_env(monkeypatch):
    monkeypatch.setenv("LIA_FILE_PATH", "")
    with pytest.raises(UilLiaError):
        uil_lia_gate("sample_creator")


def test_lia_gate_passes_with_lia_path(monkeypatch):
    monkeypatch.setenv("LIA_FILE_PATH", "/docs/lia.pdf")
    uil_lia_gate("sample_creator")  # must not raise


def test_lia_error_is_subclass_of_compliance_error():
    from pipeline.compliance.tos import ComplianceError
    assert issubclass(UilLiaError, ComplianceError)
