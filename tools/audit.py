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
    p = argparse.ArgumentParser(prog="audit", description="Graph audit queries (spec 0002 §8, 0004 §8).")
    p.add_argument("--user-id", help="Creator user_id (required for 0002 queries)")
    p.add_argument(
        "--query",
        required=True,
        choices=[
            "explain_score", "audience_overlap", "art9_signals", "undisclosed_sponsored",
            "fraud_risk_chain", "engagement_pods", "audience_overlap_gds",
        ],
    )
    p.add_argument("--score-type", help="required for explain_score")
    p.add_argument("--run-id", help="required for explain_score / art9_signals / GDS queries")
    p.add_argument("--limit", type=int, default=20, help="row limit for fraud_risk_chain")
    p.add_argument("--pod-max", type=int, default=8, help="max pod size for engagement_pods")
    args = p.parse_args()

    with GraphSession() as session:
        if args.query == "explain_score":
            result = queries.explain_score(session, args.user_id, args.score_type, args.run_id)
        elif args.query == "art9_signals":
            result = queries.art9_signals(session, args.user_id, args.run_id)
        elif args.query == "undisclosed_sponsored":
            result = queries.undisclosed_sponsored(session, args.user_id)
        elif args.query == "fraud_risk_chain":
            result = queries.fraud_risk_chain(session, args.run_id, limit=args.limit)
        elif args.query == "engagement_pods":
            result = queries.engagement_pods(session, args.run_id, pod_max=args.pod_max)
        elif args.query == "audience_overlap_gds":
            result = queries.audience_overlap_gds(session, args.run_id)
        else:
            result = queries.audience_overlap(session, args.user_id)

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
