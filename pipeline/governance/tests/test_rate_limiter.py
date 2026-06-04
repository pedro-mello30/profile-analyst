"""RateLimiter tests — AC3 (spec-0020 §5.2). time.monotonic + time.sleep monkeypatched."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from pipeline.governance import RateLimiter, build_report
from pipeline.governance.policies import RateLimitExceeded


def _adapter(rpm: int = 60, timeout_s: float = 30.0, adapter_id: str = "test") -> SimpleNamespace:
    return SimpleNamespace(adapter_id=adapter_id, rate_limit_rpm=rpm, timeout_s=timeout_s)


class TestNoRateLimit:
    def test_zero_rpm_returns_immediately(self):
        rl = RateLimiter()
        adapter = _adapter(rpm=0)
        token = rl.acquire(adapter)
        assert token.wait_s == 0.0
        assert token.adapter_id == "test"


class TestTokenBucket:
    def test_first_call_does_not_wait(self):
        rl = RateLimiter()
        adapter = _adapter(rpm=60)
        with patch("pipeline.governance.policies.time.sleep") as mock_sleep, \
             patch("pipeline.governance.policies.time.monotonic", return_value=0.0):
            token = rl.acquire(adapter)
        mock_sleep.assert_not_called()
        assert token.wait_s == 0.0

    def test_token_bucket_blocks(self):  # AC3
        """After bucket is drained, the next call must sleep until a token is available."""
        rl = RateLimiter()
        adapter = _adapter(rpm=60)  # capacity = max(1, 60//10) = 6
        slept = []

        with patch("pipeline.governance.policies.time.monotonic", return_value=0.0), \
             patch("pipeline.governance.policies.time.sleep", side_effect=lambda s: slept.append(s)):
            for _ in range(6):  # drain all 6 burst tokens
                rl.acquire(adapter)
            t7 = rl.acquire(adapter)

        assert len(slept) == 1, f"Expected exactly 1 sleep, got {slept}"
        assert slept[0] > 0
        assert t7.wait_s > 0

    def test_burst_capacity(self):
        """Burst capacity = max(1, rpm // 10). 60 rpm → 6 tokens burst."""
        rl = RateLimiter()
        adapter = _adapter(rpm=60)
        slept = []

        with patch("pipeline.governance.policies.time.monotonic", return_value=0.0), \
             patch("pipeline.governance.policies.time.sleep", side_effect=lambda s: slept.append(s)):
            # 6 calls should all get tokens without waiting
            for _ in range(6):
                rl.acquire(adapter)

        assert slept == [], f"Expected no sleeps for burst of 6, got {slept}"

    def test_rate_limit_exceeded_raises(self):
        """If wait > timeout_s, raise RateLimitExceeded."""
        rl = RateLimiter()
        adapter = _adapter(rpm=1, timeout_s=0.5)  # 60s/token but timeout=0.5s

        with patch("pipeline.governance.policies.time.monotonic", return_value=0.0), \
             patch("pipeline.governance.policies.time.sleep"):
            # capacity=max(1, 1//10)=1; first call uses the 1 token
            rl.acquire(adapter)
            with pytest.raises(RateLimitExceeded, match="timeout_s"):
                rl.acquire(adapter)

    def test_wait_recorded_in_report(self):
        rl = RateLimiter()
        adapter = _adapter(rpm=60)
        report = build_report("run1", "test")
        slept = []

        with patch("pipeline.governance.policies.time.monotonic", return_value=0.0), \
             patch("pipeline.governance.policies.time.sleep", side_effect=lambda s: slept.append(s)):
            for _ in range(6):
                rl.acquire(adapter, report=report)
            rl.acquire(adapter, report=report)

        assert report.total_rate_limit_waits == 1
        assert report.total_wait_s > 0

    def test_different_adapters_have_separate_buckets(self):
        rl = RateLimiter()
        a1 = _adapter(rpm=60, adapter_id="a1")
        a2 = _adapter(rpm=60, adapter_id="a2")
        slept = []

        with patch("pipeline.governance.policies.time.monotonic", return_value=0.0), \
             patch("pipeline.governance.policies.time.sleep", side_effect=lambda s: slept.append(s)):
            for _ in range(6):
                rl.acquire(a1)
            # a2 should still have its own full bucket
            for _ in range(6):
                rl.acquire(a2)

        assert slept == [], "Separate adapters should not share buckets"
