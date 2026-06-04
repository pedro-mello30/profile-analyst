"""Stage 1B ENRICHMENT — dependency-driven multi-source enrichment (spec 0014)."""
from __future__ import annotations

import importlib
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml

from pipeline.compliance import assert_within_retention
from pipeline.enrichment.engine import EngineConfig, run_engine

logger = logging.getLogger(__name__)

_ADAPTER_MODULES = {
    "instagram_bio":   "pipeline.enrichment.adapters.instagram_bio.InstagramBioAdapter",
    "linktree":        "pipeline.enrichment.adapters.linktree.LinktreeAdapter",
    "whois":           "pipeline.enrichment.adapters.whois.WhoisAdapter",
    "crt":             "pipeline.enrichment.adapters.crt.CrtAdapter",
    "knowledge_graph": "pipeline.enrichment.adapters.knowledge_graph.KnowledgeGraphAdapter",
    "wikidata":        "pipeline.enrichment.adapters.wikidata.WikidataAdapter",
    "youtube":         "pipeline.enrichment.adapters.youtube.YouTubeAdapter",
    "itunes":          "pipeline.enrichment.adapters.itunes.ITunesAdapter",
    "spotify":         "pipeline.enrichment.adapters.spotify.SpotifyAdapter",
    "github":          "pipeline.enrichment.adapters.github.GitHubAdapter",
    "reddit":          "pipeline.enrichment.adapters.reddit.RedditAdapter",
    "twitch":          "pipeline.enrichment.adapters.twitch.TwitchAdapter",
    "cnpj":            "pipeline.enrichment.adapters.cnpj.CNPJAdapter",
    "holehe":          "pipeline.enrichment.adapters.holehe.HoleheAdapter",
    "ghunt":           "pipeline.enrichment.adapters.ghunt.GhuntAdapter",
    "hibp":            "pipeline.enrichment.adapters.hibp.HibpAdapter",
    "gdelt":           "pipeline.enrichment.adapters.gdelt.GdeltAdapter",
    "google_news":     "pipeline.enrichment.adapters.google_news.GoogleNewsAdapter",
    "substack":        "pipeline.enrichment.adapters.substack.SubstackAdapter",
    "maigret":         "pipeline.enrichment.adapters.maigret.MaigretAdapter",
}

_CONFIG_DIR = Path(__file__).parent / "enrichment" / "config"

_ART9_SIGNAL_KEYS = frozenset({
    "holehe_services", "reddit_top_subreddits", "github_topics",
    "hibp_breach_names", "cnpj_partners",
})


def _load_adapters(adapter_ids: list[str] | None = None):
    """Instantiate all enabled adapters, or a named subset."""
    adapters = []
    for adapter_id, class_path in _ADAPTER_MODULES.items():
        if adapter_ids and adapter_id not in adapter_ids:
            continue
        yaml_path = _CONFIG_DIR / f"{adapter_id}.yaml"
        if yaml_path.exists():
            cfg = yaml.safe_load(yaml_path.read_text())
            if not cfg.get("enabled", True):
                continue
        module_path, class_name = class_path.rsplit(".", 1)
        try:
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
            adapters.append(cls())
        except Exception as exc:
            logger.warning("Could not load adapter %s: %s", adapter_id, exc)
    return adapters


def list_adapters() -> list[dict]:
    """Return metadata for all configured adapters (for --list-adapters CLI)."""
    rows = []
    for adapter_id in _ADAPTER_MODULES:
        yaml_path = _CONFIG_DIR / f"{adapter_id}.yaml"
        if yaml_path.exists():
            cfg = yaml.safe_load(yaml_path.read_text())
            rows.append({
                "adapter_id": adapter_id,
                "tier": cfg.get("tier", "?"),
                "enabled": cfg.get("enabled", True),
                "osint_risk": cfg.get("osint_risk", False),
                "ttl_hours": cfg.get("ttl_hours", 0),
            })
    return rows


def run(
    handle: str,
    project_dir: Path,
    *,
    fast_only: bool = False,
    adapter_ids: list[str] | None = None,
    bust_cache: list[str] | None = None,
    engine_config: EngineConfig | None = None,
) -> Path:
    """Run Stage 1B for *handle*. Reads 01-raw.json, writes enrichment_map.json.

    Runs between Stage 1 and Stage 2. Stage 2 will merge enrichment_map.json
    into the normalized profile after this stage completes.
    Enrichment is additive — if this fails, Stages 2+ continue with what they have.
    """
    raw_path = project_dir / "01-raw.json"
    if not raw_path.exists():
        raise FileNotFoundError(
            f"Stage 1 artifact not found: {raw_path}. Run Stage 1 first (--stage 1)."
        )

    with open(raw_path) as fh:
        raw = json.load(fh)

    gov = raw.get("_governance", {})
    assert_within_retention(gov, handle=handle)

    cache_dir = project_dir / ".enrichment_cache"
    config = engine_config or EngineConfig()

    if fast_only:
        config = EngineConfig(
            max_depth=config.max_depth,
            max_adapter_runs=config.max_adapter_runs,
            max_cost_usd=config.max_cost_usd,
            min_confidence_global=config.min_confidence_global,
            slow_tier_timeout_s=0,   # skip slow tier
            parallel_workers=config.parallel_workers,
        )

    adapters = _load_adapters(adapter_ids)
    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    pool, state, results = run_engine(
        seed_data=raw.get("raw_profile", {}),
        adapters=adapters,
        config=config,
        cache_dir=cache_dir,
        run_id=run_id,
        raw_media=raw.get("raw_media", []),
    )

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Collect flat signal list (convert Signal objects and raw dicts)
    all_signals = []
    for r in results:
        for s in r.signals:
            if hasattr(s, "__dict__"):
                all_signals.append(vars(s))
            elif isinstance(s, dict):
                all_signals.append(s)

    osint_signal_keys = [s["key"] for s in all_signals if s.get("osint_risk")]
    art9_signal_keys = [s["key"] for s in all_signals if s["key"] in _ART9_SIGNAL_KEYS]

    doc = {
        "handle": handle,
        "enriched_at": generated_at,
        "engine_version": "0014.1",
        "schema_version": "enrichment_map/v1",
        "status": "complete",
        "dossier_version": "v1" if fast_only else "v3",
        "gdpr_art9_consent_obtained": False,
        "limits": {
            "max_depth": config.max_depth,
            "max_adapter_runs": config.max_adapter_runs,
            "max_cost_usd": config.max_cost_usd,
            "actual_runs": state.total_runs,
            "actual_cost_usd": round(state.total_cost, 6),
            "limit_reached": (
                state.total_runs >= config.max_adapter_runs
                or state.total_cost >= config.max_cost_usd
            ),
        },
        "entity_pool": pool.snapshot(),
        "adapter_runs": [
            {
                "adapter_id": r.adapter_id,
                "status": "timeout" if r.error == "timeout"
                          else ("error" if r.error else "success"),
                "cached": r.cached,
                "ran_at": r.ran_at,
                "duration_s": round(getattr(r, "duration_s", 0.0), 3),
                "cost_usd": r.cost_usd,
                "entities_produced": len(r.entities),
                "signals_produced": len(r.signals),
                "error": r.error,
            }
            for r in results
        ],
        "signals": all_signals,
        "compliance": {
            "osint_signals_present": bool(osint_signal_keys),
            "osint_signal_keys": osint_signal_keys,
            "art9_risk_signals": art9_signal_keys,
            "gdpr_basis": gov.get("gdpr_basis", "LEGITIMATE_INTERESTS"),
            "requires_human_review": bool(osint_signal_keys),
            "opt_out_path": f"DELETE /profiles/{handle}",
        },
        "governance": (
            state.governance_report.to_dict()
            if state.governance_report is not None
            else None
        ),
    }

    if state.adapter_errors:
        doc["adapter_errors"] = state.adapter_errors
    if state.conflicts:
        doc["conflicts"] = state.conflicts

    # Atomic write
    out_path = project_dir / "enrichment_map.json"
    tmp_path = out_path.with_suffix(".tmp")
    with open(tmp_path, "w") as fh:
        json.dump(doc, fh, indent=2, default=str)
    os.replace(tmp_path, out_path)

    # enrichment_status.json
    status = {
        "handle": handle,
        "dossier_version": doc["dossier_version"],
        "started_at": started_at,
        "v1_ready_at": generated_at,
        "v2_ready_at": generated_at if not fast_only else None,
        "v3_ready_at": generated_at if not fast_only else None,
        "slow_tier_running": False,
        "limit_reached": doc["limits"]["limit_reached"],
        "adapter_errors": state.adapter_errors,
        "conflicts": state.conflicts,
    }
    status_path = project_dir / "enrichment_status.json"
    tmp_status = status_path.with_suffix(".tmp")
    with open(tmp_status, "w") as fh:
        json.dump(status, fh, indent=2)
    os.replace(tmp_status, status_path)

    return out_path
