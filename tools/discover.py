#!/usr/bin/env python3
"""Account Discovery CLI — spec-0018 tools/discover.py

Usage:
  python3 tools/discover.py --handle <handle> [--bio-text TEXT] [--bio-urls URL ...] \
      [--depth N] [--timeout S] [--max-accounts N] [--output-dir DIR] [--allow-noncompliant]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.account_discovery.orchestrator import discover
from pipeline.account_discovery.adapters.bio_parser import BioParsing
from pipeline.account_discovery.adapters.link_expander import LinkExpander
from pipeline.account_discovery.adapters.pattern_matcher import PatternMatcher
from pipeline.account_discovery.adapters.url_resolver import UrlResolver
from pipeline.account_discovery.scheduler import DiscoveryConfig


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Account Discovery Engine (spec-0018)")
    p.add_argument("--handle", required=True, help="Instagram handle (seed)")
    p.add_argument("--bio-text", default="", help="Bio text to parse")
    p.add_argument("--bio-urls", nargs="*", default=[], help="Bio URLs to expand")
    p.add_argument("--depth", type=int, default=2)
    p.add_argument("--timeout", type=float, default=30.0)
    p.add_argument("--max-accounts", type=int, default=50)
    p.add_argument("--output-dir", default=None,
                   help="Output dir for 00-discovery.json (default: projects/<handle>)")
    p.add_argument("--allow-noncompliant", action="store_true")
    return p


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)

    output_dir = (
        Path(args.output_dir) if args.output_dir
        else Path("projects") / args.handle
    )

    config = DiscoveryConfig(
        max_depth=args.depth,
        max_timeout_s=args.timeout,
        max_accounts=args.max_accounts,
        allow_noncompliant=args.allow_noncompliant,
    )
    adapters = [BioParsing(), PatternMatcher(), LinkExpander(), UrlResolver()]

    manifest = discover(
        args.handle, adapters,
        bio_text=args.bio_text,
        bio_urls=args.bio_urls,
        output_dir=output_dir,
        config=config,
    )

    print(f"Discovered {manifest.stats.accounts_found} accounts in {manifest.stats.elapsed_s:.2f}s")
    for acc in manifest.discovered_accounts:
        print(f"  {acc.platform:12} @{acc.handle} (confidence={acc.confidence:.2f})")
    if manifest.limit_reached:
        print("  [limit reached]")

    return 0


if __name__ == "__main__":
    sys.exit(main())
