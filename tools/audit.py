#!/usr/bin/env python3
"""tools/audit.py — run the Stage 7 audit/read queries against Neo4j (spec 0002 §8).

Usage:
  python3 tools/audit.py --user-id <id> --query explain_score --score-type brand_safety --run-id <rid>
  python3 tools/audit.py --user-id <id> --query art9_signals --run-id <rid>
  python3 tools/audit.py --user-id <id> --query undisclosed_sponsored
  python3 tools/audit.py --user-id <id> --query audience_overlap
"""
from __future__ import annotations

import argparse
import json

from pipeline.graph import GraphSession
from pipeline.graph import queries


def main() -> None:
    p = argparse.ArgumentParser(prog="audit", description="Stage 7 graph audit queries.")
    p.add_argument("--user-id", required=True)
    p.add_argument(
        "--query",
        required=True,
        choices=["explain_score", "audience_overlap", "art9_signals", "undisclosed_sponsored"],
    )
    p.add_argument("--score-type", help="required for explain_score")
    p.add_argument("--run-id", help="required for explain_score / art9_signals")
    args = p.parse_args()

    with GraphSession() as session:
        if args.query == "explain_score":
            result = queries.explain_score(session, args.user_id, args.score_type, args.run_id)
        elif args.query == "art9_signals":
            result = queries.art9_signals(session, args.user_id, args.run_id)
        elif args.query == "undisclosed_sponsored":
            result = queries.undisclosed_sponsored(session, args.user_id)
        else:
            result = queries.audience_overlap(session, args.user_id)

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
