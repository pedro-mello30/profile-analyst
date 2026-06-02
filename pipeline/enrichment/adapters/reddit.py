"""Reddit public profile adapter via PRAW (fast tier, priority 35)."""
from __future__ import annotations

import time
from datetime import datetime, timezone

from pipeline.enrichment.adapter import (
    AdapterConfig,
    AdapterResult,
    EnrichmentAdapter,
    Signal,
)
from pipeline.enrichment.entity import Entity


class RedditAdapter(EnrichmentAdapter):
    adapter_id       = "reddit"
    display_name     = "Reddit Public Profile"
    requires         = ["reddit_username", "handle"]
    produces         = []
    tier             = "fast"
    priority         = 35
    cost_usd         = 0.0
    timeout_s        = 15
    retry_max        = 1
    rate_limit_rpm   = 60
    ttl_hours        = 24
    min_confidence   = 0.5
    max_instances    = 1
    osint_risk       = False
    secrets_required = ["REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET"]
    gdpr_basis       = "LEGITIMATE_INTERESTS"
    data_category    = "PUBLIC_API"
    tos_compliant    = True

    def run(self, seed_entities: list[Entity], config: AdapterConfig) -> AdapterResult:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        t0  = time.monotonic()

        if config.dry_run or not seed_entities:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error=None, cached=False, ran_at=now, cost_usd=0.0,
                duration_s=time.monotonic() - t0,
            )

        client_id     = config.secrets.get("REDDIT_CLIENT_ID", "")
        client_secret = config.secrets.get("REDDIT_CLIENT_SECRET", "")

        if not client_id or not client_secret:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error="REDDIT credentials not configured",
                cached=False, ran_at=now, cost_usd=0.0,
                duration_s=time.monotonic() - t0,
            )

        # Prefer reddit_username entity; fall back to generic handle
        username_entity = next(
            (e for e in seed_entities if e.type == "reddit_username"), seed_entities[0]
        )
        username = username_entity.value

        try:
            import praw
            from prawcore.exceptions import PrawcoreException

            reddit = praw.Reddit(
                client_id=client_id,
                client_secret=client_secret,
                user_agent="profile-analyst/0.1",
            )

            redditor = reddit.redditor(username)

            # Force attribute fetch (PRAW is lazy)
            comment_karma = redditor.comment_karma
            link_karma    = redditor.link_karma
            created_utc   = redditor.created_utc

            # Collect top subreddits from recent submissions
            subreddits: list[str] = []
            seen_subs: set[str] = set()
            post_count = 0
            for submission in redditor.submissions.new(limit=25):
                post_count += 1
                sub_name = submission.subreddit.display_name
                if sub_name not in seen_subs:
                    seen_subs.add(sub_name)
                    subreddits.append(sub_name)

            account_age_days = 0
            if created_utc:
                age_s = time.time() - float(created_utc)
                account_age_days = int(age_s // 86400)

            signals: list[Signal] = [
                Signal(
                    key="reddit_karma_total",
                    value=int(comment_karma) + int(link_karma),
                    unit="count",
                    confidence=1.0,
                    method="api",
                    source=self.adapter_id,
                    osint_risk=False,
                ),
                Signal(
                    key="reddit_account_age_days",
                    value=account_age_days,
                    unit="days",
                    confidence=1.0,
                    method="api",
                    source=self.adapter_id,
                    osint_risk=False,
                ),
                Signal(
                    key="reddit_top_subreddits",
                    value=subreddits,
                    unit=None,
                    confidence=1.0,
                    method="api",
                    source=self.adapter_id,
                    osint_risk=True,
                ),
                Signal(
                    key="reddit_post_count",
                    value=post_count,
                    unit="count",
                    confidence=1.0,
                    method="api",
                    source=self.adapter_id,
                    osint_risk=False,
                ),
            ]

        except Exception as exc:
            return AdapterResult(
                adapter_id=self.adapter_id, entities=[], signals=[],
                error=str(exc), cached=False, ran_at=now, cost_usd=0.0,
                duration_s=time.monotonic() - t0,
            )

        return AdapterResult(
            adapter_id=self.adapter_id,
            entities=[],
            signals=signals,
            error=None,
            cached=False,
            ran_at=now,
            cost_usd=0.0,
            duration_s=time.monotonic() - t0,
        )
