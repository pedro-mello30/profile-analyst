#!/usr/bin/env python3
"""profile_analyst.py — CLI entry point for the social-media associations profile pipeline."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECTS_ROOT = Path("projects")

# Initialise MLflow observability once at process start (no-op when disabled).
try:
    from observability import init_tracing as _init_tracing
    _init_tracing()
except Exception:
    pass


def _project_dir(handle: str) -> Path:
    return PROJECTS_ROOT / handle


def _run_stage1(handle: str) -> None:
    from adapters.sample import SampleAdapter
    from pipeline.stage1_ingest import run

    adapter = SampleAdapter()
    out = run(handle, adapter, _project_dir(handle))
    print(f"Stage 1 complete: {out}")


def _run_stage2(handle: str) -> None:
    from pipeline.stage2_normalize import run

    out = run(handle, _project_dir(handle))
    print(f"Stage 2 complete: {out}")


def _run_stage3(handle: str) -> None:
    import anthropic
    from pipeline.stage3_features import run

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    out = run(handle, _project_dir(handle), anthropic_client=client)
    print(f"Stage 3 complete: {out}")


def _run_stage4(handle: str) -> None:
    from pipeline.stage4_linkage import run
    from pipeline.compliance.tos import UilLiaError

    try:
        out = run(handle, _project_dir(handle))
        print(f"Stage 4 complete: {out}")
    except UilLiaError as exc:
        print(f"Stage 4 error — {exc}", file=sys.stderr)
        sys.exit(2)


def _run_stage6(handle: str, *, expose_art9: bool = False) -> None:
    from pipeline.stage6_dossier import run

    out = run(
        handle,
        _project_dir(handle),
        pipeline_version="0.1.0",
        expose_art9=expose_art9,
    )
    print(f"Stage 6 complete: {out}")


def _run_stage7(handle: str) -> None:
    from pipeline.stage7_load import run

    out = run(handle, _project_dir(handle))
    print(f"Stage 7 complete: {out}")


def _run_stage8(handle: str) -> None:
    from pipeline.stage8_embed import run
    from pipeline.llm.ollama_client import OllamaError
    from pipeline.rag.indexes import Neo4jVersionError, DimensionMismatchError

    try:
        out = run(handle, _project_dir(handle))
        print(f"Stage 8 complete: {out}")
    except OllamaError as exc:
        print(f"Stage 8 error — Ollama unreachable at {os.environ.get('OLLAMA_HOST','http://localhost:11434')}: {exc}", file=sys.stderr)
        sys.exit(2)
    except Neo4jVersionError as exc:
        print(f"Stage 8 error — {exc}", file=sys.stderr)
        sys.exit(2)
    except DimensionMismatchError as exc:
        print(f"Stage 8 error — {exc}", file=sys.stderr)
        sys.exit(2)


def _run_stage9(handle: str) -> None:
    from pipeline.stage9_gds import run
    from pipeline.graph.gds import GdsUnavailableError

    try:
        out = run(handle, _project_dir(handle))
        print(f"Stage 9 complete: {out}")
    except GdsUnavailableError as exc:
        print(f"Stage 9 error: {exc}", file=sys.stderr)
        sys.exit(2)


STAGE_MAP = {
    "1": _run_stage1,
    "2": _run_stage2,
    "3": _run_stage3,
    "4": _run_stage4,
    "6": _run_stage6,
    "7": _run_stage7,
    "8": _run_stage8,
    "9": _run_stage9,
}


def _parse_stages(stage_str: str) -> list[str]:
    if stage_str == "all":
        return ["1", "2", "3", "6", "7", "8", "9"]
    return [s.strip() for s in stage_str.split(",")]


def cmd_ask(handle: str, question: str) -> None:
    """NL→Cypher graph query (spec 0003). Exits non-zero on rejection / unreachable Ollama."""
    from pipeline.llm.ollama_client import OllamaError
    from tools.ask import ask

    try:
        result = ask(handle, question)
    except OllamaError as exc:
        print(f"Ollama unreachable: {exc}", file=sys.stderr)
        sys.exit(2)

    print(result.manifest["answer"])
    print(f"\n(manifest: {result.manifest_path})", file=sys.stderr)
    if result.exit_code != 0:
        sys.exit(result.exit_code)


def cmd_rag(args: argparse.Namespace) -> None:
    """Hybrid RAG query (spec 0005). Exits non-zero on all-retriever failure."""
    from pipeline.llm.ollama_client import OllamaError
    from pipeline.rag.indexes import Neo4jVersionError
    from tools.rag import run as rag_run, RAGError

    modes = [m.strip() for m in args.modes.split(",")] if getattr(args, "modes", None) else None
    project_dir = _project_dir(args.handle) if getattr(args, "handle", None) else None

    try:
        manifest = rag_run(
            question=args.rag,
            handle=getattr(args, "handle", None),
            modes=modes,
            project_dir=project_dir,
        )
    except OllamaError as exc:
        print(f"Ollama unreachable at {os.environ.get('OLLAMA_HOST','http://localhost:11434')}: {exc}", file=sys.stderr)
        sys.exit(2)
    except Neo4jVersionError as exc:
        print(f"Neo4j version error: {exc}", file=sys.stderr)
        sys.exit(2)
    except RAGError as exc:
        print(f"RAG error: {exc}\nTip: run --stage 8 first to ensure embeddings exist.", file=sys.stderr)
        sys.exit(2)

    print(manifest["answer"])
    if manifest.get("citations"):
        cited = ", ".join(
            f"@{c.get('handle', c.get('user_id', '?'))}"
            for c in manifest["citations"]
            if c.get("type") == "creator"
        )
        if cited:
            print(f"\nCited: {cited}", file=sys.stderr)


def cmd_run(args: argparse.Namespace) -> None:
    if getattr(args, "rag", None):
        cmd_rag(args)
        return

    if getattr(args, "ask", None):
        cmd_ask(args.handle, args.ask)
        return

    if args.allow_noncompliant:
        os.environ["ALLOW_NONCOMPLIANT"] = "true"

    stages = _parse_stages(args.stage)
    unknown = [s for s in stages if s not in STAGE_MAP]
    if unknown:
        print(f"Unknown stage(s): {unknown}. Valid: {list(STAGE_MAP.keys())} or 'all'", file=sys.stderr)
        sys.exit(1)

    for s in stages:
        if s == "6":
            _run_stage6(args.handle, expose_art9=args.expose_art9)
        else:
            STAGE_MAP[s](args.handle)


def cmd_erase(args: argparse.Namespace) -> None:
    from pipeline.compliance import erase_profile

    receipt = erase_profile(args.handle, dry_run=args.dry_run, projects_root=PROJECTS_ROOT)
    action = "Would erase" if args.dry_run else "Erased"
    status = "existed" if receipt.existed else "did not exist"
    print(f"{action} profile '{args.handle}' ({status}). "
          f"Artifacts: {len(receipt.artifacts_deleted)}, bytes: {receipt.bytes_freed}")


def cmd_gc(args: argparse.Namespace) -> None:
    from pipeline.compliance import gc_sweep

    receipts = gc_sweep(PROJECTS_ROOT)
    if receipts:
        for r in receipts:
            print(f"GC erased '{r.handle}': {len(r.artifacts_deleted)} artifacts, {r.bytes_freed} bytes")
    else:
        print("GC: no expired profiles found.")


def cmd_load(args: argparse.Namespace) -> None:
    from pipeline.stage7_load import run

    out = run(
        args.handle,
        _project_dir(args.handle),
        allow_noncompliant_flag=args.allow_noncompliant,
    )
    print(f"Stage 7 complete: {out}")


def cmd_gds(args: argparse.Namespace) -> None:
    from pipeline.stage9_gds import run
    from pipeline.graph.gds import GdsUnavailableError

    try:
        out = run(
            args.handle,
            _project_dir(args.handle),
            allow_noncompliant_flag=args.allow_noncompliant,
        )
        print(f"Stage 9 complete: {out}")
    except GdsUnavailableError as exc:
        print(f"Stage 9 error: {exc}", file=sys.stderr)
        sys.exit(2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="profile_analyst",
        description="Social-media associations profile pipeline.",
    )
    sub = parser.add_subparsers(dest="command")

    # ── run (default command via --handle / --stage) ─────────────────────────
    run_p = argparse.ArgumentParser(add_help=False)
    run_p.add_argument("--handle", required=True, help="Instagram handle to process")
    run_p.add_argument("--stage", default="all", help="Stage(s) to run: all | 1,2,3,6")
    run_p.add_argument("--allow-noncompliant", action="store_true")
    run_p.add_argument("--expose-art9", action="store_true")

    # Support both `profile_analyst.py --handle X` and `profile_analyst.py run --handle X`
    parser.add_argument("--handle", help="Instagram handle to process")
    parser.add_argument("--stage", default="all", help="Stage(s) to run: all | 1,2,3,6")
    parser.add_argument("--allow-noncompliant", action="store_true")
    parser.add_argument("--expose-art9", action="store_true")
    parser.add_argument("--ask", help="Natural-language question to run against the 0002 graph (spec 0003)")
    parser.add_argument("--rag", help="Natural-language question for Hybrid RAG retrieval (spec 0005)")
    parser.add_argument("--modes", help="Comma-separated retrieval modes: vector,graph,keyword (spec 0005)")
    parser.add_argument("--rerank", action="store_true", default=False, help="Enable cross-encoder reranking (spec 0005)")

    # ── erase ─────────────────────────────────────────────────────────────────
    erase_p = sub.add_parser("erase", help="GDPR Art.17 erasure for a handle")
    erase_p.add_argument("--handle", required=True)
    erase_p.add_argument("--dry-run", action="store_true")

    # ── gc ────────────────────────────────────────────────────────────────────
    sub.add_parser("gc", help="Sweep and erase expired profiles")

    # ── load (Stage 7: Neo4j graph persistence) ────────────────────────────────
    load_p = sub.add_parser("load", help="Stage 7 LOAD: upsert the dossier into Neo4j")
    load_p.add_argument("--handle", required=True)
    load_p.add_argument("--allow-noncompliant", action="store_true")

    # ── gds (Stage 9: graph data-science) ──────────────────────────────────────
    gds_p = sub.add_parser("gds", help="Stage 9 GDS: run graph algorithms + write-back (spec 0004)")
    gds_p.add_argument("--handle", required=True)
    gds_p.add_argument("--allow-noncompliant", action="store_true")

    args = parser.parse_args(argv)

    if args.command == "erase":
        cmd_erase(args)
    elif args.command == "gc":
        cmd_gc(args)
    elif args.command == "load":
        cmd_load(args)
    elif args.command == "gds":
        cmd_gds(args)
    else:
        if getattr(args, "rag", None):
            cmd_rag(args)
            return
        if not args.handle:
            parser.print_help()
            sys.exit(1)
        cmd_run(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
