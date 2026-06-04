"""RobotsPolicy tests — AC4, AC5 (spec-0020 §5.1)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from pipeline.governance import GovernanceReport, RobotsPolicy, build_report
from pipeline.governance.tests.conftest import make_valid_discovery_adapter


def _api_adapter():
    return SimpleNamespace(adapter_id="api_adapter", robots_txt_policy="N/A")


def _scrape_adapter():
    return SimpleNamespace(adapter_id="scrape_adapter", robots_txt_policy="RESPECT")


class TestNAPolicy:
    def test_na_policy_skips_check(self):  # AC5
        policy = RobotsPolicy()
        adapter = _api_adapter()
        decision = policy.check("https://example.com/profile/foo", adapter)
        assert decision.allowed is True
        assert decision.reason == "robots_txt_policy=N/A"
        assert decision.policy_type == "N/A"

    def test_na_policy_logged_to_report(self):
        policy = RobotsPolicy()
        report = build_report("run1", "test")
        adapter = _api_adapter()
        policy.check("https://example.com/x", adapter, report=report)
        assert len(report.policy_decisions) == 1
        assert report.policy_decisions[0].allowed is True


class TestRespectPolicy:
    def _make_rp(self, allowed: bool):
        rp = MagicMock()
        rp.can_fetch.return_value = allowed
        return rp

    def test_disallowed_path(self):  # AC4
        policy = RobotsPolicy()
        adapter = _scrape_adapter()
        mock_rp = self._make_rp(allowed=False)
        with patch("urllib.robotparser.RobotFileParser") as MockRFP:
            MockRFP.return_value = mock_rp
            mock_rp.read.return_value = None
            decision = policy.check("https://example.com/disallowed", adapter)
        assert decision.allowed is False
        assert decision.reason == "robots.txt disallows path"

    def test_allowed_path(self):
        policy = RobotsPolicy()
        adapter = _scrape_adapter()
        mock_rp = self._make_rp(allowed=True)
        with patch("urllib.robotparser.RobotFileParser") as MockRFP:
            MockRFP.return_value = mock_rp
            mock_rp.read.return_value = None
            decision = policy.check("https://example.com/allowed", adapter)
        assert decision.allowed is True
        assert decision.reason == "robots.txt permits"

    def test_fetch_failure_returns_permissive(self):
        policy = RobotsPolicy()
        adapter = _scrape_adapter()
        mock_rp = MagicMock()
        mock_rp.read.side_effect = OSError("connection refused")
        with patch("urllib.robotparser.RobotFileParser") as MockRFP:
            MockRFP.return_value = mock_rp
            decision = policy.check("https://down.example.com/x", adapter)
        assert decision.allowed is True
        assert "permissive fallback" in decision.reason

    def test_never_raises(self):
        policy = RobotsPolicy()
        adapter = _scrape_adapter()
        with patch("urllib.robotparser.RobotFileParser") as MockRFP:
            MockRFP.side_effect = RuntimeError("unexpected")
            decision = policy.check("https://example.com/x", adapter)
        assert decision.allowed is True

    def test_result_logged_to_report(self):
        policy = RobotsPolicy()
        adapter = _scrape_adapter()
        report = build_report("run2", "test")
        mock_rp = self._make_rp(allowed=True)
        with patch("urllib.robotparser.RobotFileParser") as MockRFP:
            MockRFP.return_value = mock_rp
            mock_rp.read.return_value = None
            policy.check("https://example.com/x", adapter, report=report)
        assert len(report.policy_decisions) == 1

    def test_cache_reuse(self):
        policy = RobotsPolicy()
        adapter = _scrape_adapter()
        mock_rp = self._make_rp(allowed=True)
        call_count = 0

        original_rfp = __import__("urllib.robotparser", fromlist=["RobotFileParser"]).RobotFileParser

        def counting_rfp():
            nonlocal call_count
            call_count += 1
            return mock_rp

        with patch("urllib.robotparser.RobotFileParser", side_effect=counting_rfp):
            mock_rp.read.return_value = None
            policy.check("https://example.com/a", adapter)
            policy.check("https://example.com/b", adapter)

        assert call_count == 1, "robots.txt should be fetched once and cached"

    def test_decision_has_url(self):
        policy = RobotsPolicy()
        adapter = _api_adapter()
        url = "https://example.com/profile/xyz"
        decision = policy.check(url, adapter)
        assert decision.checked_url == url
