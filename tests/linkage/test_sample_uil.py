"""Unit tests for SampleUILAdapter (spec 0011 T10)."""
import socket
from pathlib import Path

import pytest

from adapters.cross_platform.sample_uil import SampleUILAdapter

PROJECTS_ROOT = Path(__file__).parent.parent.parent / "projects"


def test_sample_uil_loads_fixture():
    adapter = SampleUILAdapter(projects_root=PROJECTS_ROOT)
    candidates = adapter.fetch_candidates("sample_creator")
    assert len(candidates) >= 1
    for c in candidates:
        assert "platform" in c
        assert "candidate_handle" in c


def test_sample_uil_governance_posture():
    adapter = SampleUILAdapter()
    assert adapter.tos_compliant is True
    assert adapter.data_category == "public_profile"
    assert adapter.requires_creator_consent is True
    assert adapter.gdpr_basis == "LEGITIMATE_INTERESTS"


def test_sample_uil_missing_fixture_returns_empty():
    adapter = SampleUILAdapter(projects_root=PROJECTS_ROOT)
    candidates = adapter.fetch_candidates("__no_such_handle__")
    assert candidates == []


def test_sample_uil_opens_no_socket(monkeypatch):
    """Confirm the adapter never touches the network."""
    def _no_connect(*a, **kw):
        raise AssertionError("SampleUILAdapter must not open a network socket")

    monkeypatch.setattr(socket, "getaddrinfo", _no_connect)
    adapter = SampleUILAdapter(projects_root=PROJECTS_ROOT)
    adapter.fetch_candidates("sample_creator")  # must not raise
