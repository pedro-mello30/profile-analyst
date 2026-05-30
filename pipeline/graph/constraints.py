"""Schema constraints & indexes for the creator graph (spec 0002 §5.3).

All statements are ``IF NOT EXISTS`` so ``ensure_constraints`` is idempotent and
safe to run at the start of every Stage 7 load.
"""
from __future__ import annotations

CONSTRAINTS: list[str] = [
    "CREATE CONSTRAINT creator_user_id IF NOT EXISTS "
    "FOR (c:Creator) REQUIRE c.user_id IS UNIQUE",
    "CREATE CONSTRAINT media_media_id IF NOT EXISTS "
    "FOR (m:Media) REQUIRE m.media_id IS UNIQUE",
    "CREATE CONSTRAINT user_username IF NOT EXISTS "
    "FOR (u:User) REQUIRE u.username IS UNIQUE",
    "CREATE CONSTRAINT comment_id IF NOT EXISTS "
    "FOR (cm:Comment) REQUIRE cm.comment_id IS UNIQUE",
    "CREATE INDEX score_lookup IF NOT EXISTS "
    "FOR (s:Score) ON (s.type, s.created_at)",
]


def ensure_constraints(session) -> None:
    """Create the uniqueness constraints + score index. Idempotent."""
    for stmt in CONSTRAINTS:
        session.run(stmt)
