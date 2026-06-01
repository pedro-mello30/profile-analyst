#!/usr/bin/env python3
"""HealSweep — outer diagnosis loop (spec 0013 §5).

Reads MLflow traces for the last N runs, groups retry failure patterns,
diffs eval scores against a pinned baseline, and writes a markdown report.
Never modifies prompts, schemas, or code.

Usage:
    python3 tools/heal_sweep.py [--window 30] [--out docs/heal-reports/] [--no-eval]
"""
from __future__ import annotations

import argparse
import json
import re
import traceback
from datetime import datetime, timezone
from pathlib import Path

_BASELINE_PATH = Path(__file__).parent.parent / "observability" / "eval" / "baseline.json"


# ── failure grouping ───────────────────────────────────────────────────────────

def _extract_path_key(error_detail: str, error_type: str) -> str:
    """Extract the last meaningful path segment from an error_detail string.

    For schema_violation errors the detail is typically:
        "features → 2 → confidence: '0.95' is not type number"
    We want the last non-numeric, non-empty, reasonably short segment before
    the colon that delimits the constraint message.
    """
    if error_type == "json_decode":
        return "json_decode"

    # Take everything before the first colon (the path portion).
    path_part = error_detail.split(":")[0].strip()

    # Split on common delimiters: →, /, ., space.
    segments = re.split(r"[→/.\s]+", path_part)

    # Walk from right to left, skipping numeric-only and very long segments.
    for seg in reversed(segments):
        seg = seg.strip()
        if not seg:
            continue
        if seg.isdigit():
            continue
        if len(seg) > 40:
            continue
        return seg

    # Fallback: use the whole path_part truncated.
    return path_part[:40] if path_part else "unknown"


def group_failures(attempts: list[dict]) -> dict[tuple[str, str], int]:
    """Group retry attempts by (error_type, path_key), returning counts.

    Args:
        attempts: List of attempt dicts produced by the inner retry loop.
                  Each dict is expected to have ``error_type`` and ``error_detail`` keys.

    Returns:
        Mapping of ``(error_type, path_key)`` → count, or ``{}`` on empty input.
    """
    if not attempts:
        return {}

    counts: dict[tuple[str, str], int] = {}
    for attempt in attempts:
        error_type = attempt.get("error_type", "unknown")
        error_detail = attempt.get("error_detail", "")
        path_key = _extract_path_key(error_detail, error_type)
        key = (error_type, path_key)
        counts[key] = counts.get(key, 0) + 1

    return counts


# ── baseline diff ──────────────────────────────────────────────────────────────

def diff_baseline(
    current: dict[str, float],
    baseline: dict[str, float],
    threshold: float = 0.05,
) -> dict[str, dict]:
    """Return metrics where current has regressed more than *threshold* below baseline.

    Args:
        current:   Mapping of metric_name → current score.
        baseline:  Mapping of metric_name → pinned baseline score.
        threshold: Minimum drop (exclusive) to flag as a regression.

    Returns:
        Dict of metric_name → ``{baseline, current, delta}`` for each regression.
        Empty dict if no regressions found.
    """
    regressions: dict[str, dict] = {}
    for metric, base_val in baseline.items():
        if metric not in current:
            continue
        cur_val = current[metric]
        delta = cur_val - base_val
        if delta < -threshold:
            regressions[metric] = {
                "baseline": base_val,
                "current": cur_val,
                "delta": round(delta, 6),
            }
    return regressions


# ── report rendering ───────────────────────────────────────────────────────────

def _hypothesis(error_type: str, path_key: str, count: int) -> str:
    if error_type == "json_decode":
        return (
            "Model output was truncated or contained markdown fences; "
            "check OLLAMA_TIMEOUT_S and prompt output instructions."
        )
    if path_key in ("confidence", "method", "art9_risk"):
        return (
            f"Model omits or misformats required field `{path_key}`; "
            "tighten grammar constraint in `_array_format()` or add an explicit example "
            "in the Stage 3 prompt."
        )
    if path_key == "value":
        return (
            "Model returns object-shaped value instead of string/array; "
            "check `_array_format()` value type constraint."
        )
    if count >= 5:
        return (
            f"High-frequency failure on `{path_key}`; likely a systematic prompt gap — "
            "add a concrete example."
        )
    return f"Occasional failure on `{path_key}`; monitor for recurrence."


def render_report(
    groups: dict[tuple[str, str], int],
    regressions: dict[str, dict],
    window: int,
) -> str:
    """Render a markdown diagnosis report.

    Args:
        groups:      Output of :func:`group_failures`.
        regressions: Output of :func:`diff_baseline`.
        window:      Number of MLflow runs that were examined.

    Returns:
        Markdown string ready to write to disk.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines: list[str] = [
        f"# HealSweep Diagnosis Report",
        f"",
        f"**Generated:** {now}  ",
        f"**Window:** last {window} runs",
        f"",
    ]

    # ── Failure table ─────────────────────────────────────────────────────────
    lines.append("## Retry Failure Patterns")
    lines.append("")

    if not groups:
        lines.append("No failures recorded in this window.")
    else:
        lines.append("| error_type | path / key | count | hypothesis |")
        lines.append("|---|---|---|---|")
        sorted_groups = sorted(groups.items(), key=lambda kv: kv[1], reverse=True)
        for (error_type, path_key), count in sorted_groups:
            hypo = _hypothesis(error_type, path_key, count)
            # Escape pipes in hypothesis for markdown table safety
            hypo_escaped = hypo.replace("|", "\\|")
            lines.append(f"| {error_type} | {path_key} | {count} | {hypo_escaped} |")

    lines.append("")

    # ── Regression section ────────────────────────────────────────────────────
    lines.append("## Eval Score Regressions")
    lines.append("")

    if not regressions:
        lines.append("No regressions detected.")
    else:
        lines.append("| metric | baseline | current | delta |")
        lines.append("|---|---|---|---|")
        for metric, entry in sorted(regressions.items()):
            lines.append(
                f"| {metric} | {entry['baseline']:.4f} | {entry['current']:.4f} | {entry['delta']:+.4f} |"
            )
        lines.append("")
        lines.append(
            "> **Action required:** Review the metrics above. "
            "A regression > 0.05 below baseline warrants investigation before the next release."
        )

    lines.append("")
    return "\n".join(lines) + "\n"


# ── MLflow data fetching ───────────────────────────────────────────────────────

def _fetch_mlflow_attempts(window: int) -> list[dict]:
    """Download retry_attempts.json artifacts from the last *window* MLflow runs.

    Returns an empty list silently if MLflow is unavailable, the experiment is
    not found, or no artifacts exist.
    """
    try:
        import mlflow
        from observability.config import settings

        client = mlflow.MlflowClient(tracking_uri=settings.tracking_uri)

        # Look up the experiment by name.
        experiment = client.get_experiment_by_name(settings.experiment)
        if experiment is None:
            return []

        # Fetch the last `window` runs sorted by start time descending.
        runs = client.search_runs(
            experiment_ids=[experiment.experiment_id],
            order_by=["start_time DESC"],
            max_results=window,
        )

        all_attempts: list[dict] = []
        for run in runs:
            try:
                artifacts = client.list_artifacts(run.info.run_id)
                artifact_names = [a.path for a in artifacts]
                if "retry_attempts.json" not in artifact_names:
                    continue
                local_path = client.download_artifacts(
                    run.info.run_id, "retry_attempts.json"
                )
                with open(local_path) as fh:
                    data = json.load(fh)
                if isinstance(data, list):
                    all_attempts.extend(data)
                elif isinstance(data, dict):
                    # Support a wrapped format {attempts: [...]}
                    inner = data.get("attempts", [])
                    if isinstance(inner, list):
                        all_attempts.extend(inner)
            except Exception:  # noqa: BLE001
                continue

        return all_attempts

    except Exception:  # noqa: BLE001
        return []


# ── main ───────────────────────────────────────────────────────────────────────

def _load_baseline() -> dict[str, float]:
    """Load the pinned baseline metrics from disk."""
    try:
        with open(_BASELINE_PATH) as fh:
            data = json.load(fh)
        return data.get("metrics", {})
    except Exception:  # noqa: BLE001
        return {}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="HealSweep — outer diagnosis loop (spec 0013 §5)."
    )
    parser.add_argument(
        "--window",
        type=int,
        default=30,
        help="Number of recent MLflow runs to examine (default: 30).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("docs/heal-reports"),
        help="Directory to write the markdown report (default: docs/heal-reports/).",
    )
    parser.add_argument(
        "--no-eval",
        action="store_true",
        help="Skip running observability.evaluation.run_evaluation().",
    )
    args = parser.parse_args()

    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── 1. Fetch retry attempts from MLflow ───────────────────────────────────
    print(f"[heal_sweep] Fetching retry attempts from last {args.window} MLflow runs…")
    attempts: list[dict] = []
    try:
        attempts = _fetch_mlflow_attempts(args.window)
        print(f"[heal_sweep] Found {len(attempts)} attempt record(s).")
    except Exception:  # noqa: BLE001
        print("[heal_sweep] Warning: could not fetch MLflow attempts (MLflow unavailable?).")
        traceback.print_exc()

    # ── 2. Group failures ─────────────────────────────────────────────────────
    groups: dict[tuple[str, str], int] = {}
    try:
        groups = group_failures(attempts)
    except Exception:  # noqa: BLE001
        print("[heal_sweep] Warning: failure grouping failed.")
        traceback.print_exc()

    # ── 3. Optionally run eval and diff against baseline ─────────────────────
    regressions: dict[str, dict] = {}
    if not args.no_eval:
        print("[heal_sweep] Running RAG evaluation…")
        try:
            from observability.evaluation import run_evaluation
            current_metrics = run_evaluation()
            baseline = _load_baseline()
            regressions = diff_baseline(current_metrics, baseline)
        except Exception:  # noqa: BLE001
            print("[heal_sweep] Warning: eval run failed.")
            traceback.print_exc()
    else:
        print("[heal_sweep] --no-eval: skipping evaluation run.")

    # ── 4. Render and write report ────────────────────────────────────────────
    report = render_report(groups, regressions, window=args.window)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_path = out_dir / f"{today}.md"
    try:
        out_path.write_text(report, encoding="utf-8")
        print(f"[heal_sweep] Report written to {out_path}")
    except Exception:  # noqa: BLE001
        print(f"[heal_sweep] Warning: could not write report to {out_path}.")
        traceback.print_exc()
        # Print to stdout as fallback.
        print("\n── Report ──\n")
        print(report)


if __name__ == "__main__":
    main()
