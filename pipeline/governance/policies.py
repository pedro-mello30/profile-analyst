"""RobotsPolicy and RateLimiter (spec-0020 §5)."""
from __future__ import annotations

import threading
import time
import urllib.robotparser
from datetime import datetime, timezone
from urllib.parse import urlparse

from pipeline.governance.models import GovernanceReport, PolicyDecision, RateLimitToken


class RateLimitExceeded(RuntimeError):
    pass


class RobotsPolicy:
    """Checks robots.txt for adapters with robots_txt_policy=RESPECT.

    Never raises — returns a PolicyDecision even on fetch failure.
    Cache is in-process and per-session (TTL = 3600s).
    """

    _UA = "profile-analyst/1.0"
    _TTL_S = 3600

    def __init__(self):
        self._cache: dict[str, tuple] = {}  # domain -> (RobotFileParser, expires_monotonic)

    def check(
        self,
        url: str,
        adapter,
        report: GovernanceReport | None = None,
    ) -> PolicyDecision:
        policy = getattr(adapter, "robots_txt_policy", "N/A")

        if policy == "N/A":
            decision = PolicyDecision(
                allowed=True,
                reason="robots_txt_policy=N/A",
                checked_url=url,
                policy_type="N/A",
                decided_at=datetime.now(timezone.utc),
            )
        else:
            domain = urlparse(url).netloc
            rp = self._get_parser(url, domain)
            if rp is None:
                decision = PolicyDecision(
                    allowed=True,
                    reason="robots.txt unreachable — permissive fallback",
                    checked_url=url,
                    policy_type="RESPECT",
                    decided_at=datetime.now(timezone.utc),
                )
            else:
                allowed = rp.can_fetch(self._UA, url)
                decision = PolicyDecision(
                    allowed=allowed,
                    reason="robots.txt permits" if allowed else "robots.txt disallows path",
                    checked_url=url,
                    policy_type="RESPECT",
                    decided_at=datetime.now(timezone.utc),
                )

        if report is not None:
            report.policy_decisions.append(decision)
        return decision

    def _get_parser(self, url: str, domain: str):
        now = time.monotonic()
        cached = self._cache.get(domain)
        if cached is not None:
            rp, expires_at = cached
            if now < expires_at:
                return rp

        scheme = urlparse(url).scheme
        robots_url = f"{scheme}://{domain}/robots.txt"
        try:
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(robots_url)
            rp.read()
            self._cache[domain] = (rp, now + self._TTL_S)
            return rp
        except Exception:
            return None


class RateLimiter:
    """Token-bucket rate limiter, one bucket per adapter_id (spec-0020 §5.2).

    Thread-safe via per-instance threading.Lock.
    rate_limit_rpm=0 means no rate limit.
    Raises RateLimitExceeded if the wait would exceed adapter.timeout_s.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._buckets: dict[str, dict] = {}

    def acquire(
        self,
        adapter,
        report: GovernanceReport | None = None,
    ) -> RateLimitToken:
        adapter_id = str(getattr(adapter, "adapter_id", repr(adapter)))
        rate_limit_rpm = getattr(adapter, "rate_limit_rpm", 0)
        timeout_s = getattr(adapter, "timeout_s", float("inf"))

        if rate_limit_rpm == 0:
            return RateLimitToken(
                adapter_id=adapter_id,
                acquired_at=datetime.now(timezone.utc),
                wait_s=0.0,
            )

        interval = 60.0 / rate_limit_rpm
        capacity = max(1, rate_limit_rpm // 10)
        wait_s = 0.0

        with self._lock:
            now = time.monotonic()
            if adapter_id not in self._buckets:
                self._buckets[adapter_id] = {
                    "tokens": float(capacity),
                    "last_refill": now,
                }

            bucket = self._buckets[adapter_id]
            elapsed = now - bucket["last_refill"]
            bucket["tokens"] = min(capacity, bucket["tokens"] + elapsed / interval)
            bucket["last_refill"] = now

            if bucket["tokens"] >= 1.0:
                bucket["tokens"] -= 1.0
            else:
                tokens_needed = 1.0 - bucket["tokens"]
                wait_s = tokens_needed * interval
                if wait_s > timeout_s:
                    raise RateLimitExceeded(
                        f"Rate limit wait ({wait_s:.2f}s) exceeds timeout_s ({timeout_s}s) "
                        f"for adapter {adapter_id!r}"
                    )
                bucket["tokens"] = 0.0

        # Sleep OUTSIDE the lock: holding the lock while sleeping would block all other
        # adapter threads from acquiring tokens. The token was already consumed atomically
        # inside the lock above — the sleep is only the inter-request pacing delay.
        # Future: replace with asyncio.sleep in an async upgrade (spec-0020 §5.2).
        if wait_s > 0:
            time.sleep(wait_s)

        token = RateLimitToken(
            adapter_id=adapter_id,
            acquired_at=datetime.now(timezone.utc),
            wait_s=wait_s,
        )
        if report is not None and wait_s > 0:
            report.total_rate_limit_waits += 1
            report.total_wait_s += wait_s
        return token
