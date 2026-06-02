"""Stage 6 DOSSIER — scoring, compliance assembly, and report rendering (spec §8)."""
from __future__ import annotations

import dataclasses
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import jsonschema

from pipeline.enrichment.platform_presence import PlatformPresenceExtractor, PlatformPresenceBlock
from pipeline.compliance import (
    assert_within_retention,
    assert_scores_explainable,
    build_compliance_flags,
    gate_art9_report_exposure,
    Art9Scanner,
)
from pipeline.models import DossierScore, ComplianceFlags, Provenance, Dossier
from pipeline.scoring_utils import (
    clamp,
    er_vs_benchmark,
    _ratio_reasonableness,
    TIER_BENCHMARK_ER,
    EQS_WEIGHTS,
    AUTH_WEIGHTS,
)

_SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "06-dossier.schema.json"


def _load_schema() -> dict:
    with open(_SCHEMA_PATH) as fh:
        return json.load(fh)


# ── Feature indexing ──────────────────────────────────────────────────────────

def index_features(features_doc: dict) -> dict[str, dict]:
    """Return a dict keyed by feature_id for fast lookup."""
    return {f["feature_id"]: f for f in features_doc.get("features", [])}


def _fval(feats: dict[str, dict], fid: str, default=None):
    f = feats.get(fid)
    return f["value"] if f is not None else default


def _fconf(feats: dict[str, dict], fid: str, default: float = 0.0) -> float:
    f = feats.get(fid)
    return float(f["confidence"]) if f is not None else default


# ── Composite scorers (spec §8) ───────────────────────────────────────────────

def score_engagement_quality(feats: dict[str, dict]) -> DossierScore:
    """Engagement Quality Score (EQS) per spec §8."""
    tier = _fval(feats, "follower_tier", "Mid")
    er = _fval(feats, "er_by_followers")
    comments_avg = _fval(feats, "comments_per_post_avg")
    consistency = _fval(feats, "posting_consistency_score")
    ratio = _fval(feats, "follower_following_ratio")
    pod = _fval(feats, "comment_pod_signal", "unknown")

    signals: list[str] = []

    if er is not None:
        er_component = er_vs_benchmark(er, tier)
        signals.append(f"er_by_followers={er}% vs {tier} benchmark {TIER_BENCHMARK_ER.get(tier)}%")
    else:
        er_component = 50.0
        signals.append("er_by_followers unavailable — using neutral 50")

    if comments_avg is not None:
        comments_component = clamp((comments_avg / 30.0) * 100)
        signals.append(f"comments_per_post_avg={comments_avg}")
    else:
        comments_component = 50.0
        signals.append("comments_per_post_avg unavailable — using neutral 50")

    if consistency is not None:
        consistency_component = consistency * 100.0
        signals.append(f"posting_consistency_score={consistency}")
    else:
        consistency_component = 50.0
        signals.append("posting_consistency_score unavailable — using neutral 50")

    if ratio is not None:
        ratio_component = _ratio_reasonableness(ratio)
        signals.append(f"follower_following_ratio={ratio}")
    else:
        ratio_component = 50.0
        signals.append("follower_following_ratio unavailable — using neutral 50")

    raw = (
        EQS_WEIGHTS["er"] * er_component
        + EQS_WEIGHTS["comments"] * comments_component
        + EQS_WEIGHTS["consistency"] * consistency_component
        + EQS_WEIGHTS["ratio"] * ratio_component
    )

    if pod == "detected":
        raw -= 20.0
        signals.append("comment_pod_signal=detected: −20 penalty")

    confidences = [
        _fconf(feats, "er_by_followers"),
        _fconf(feats, "comments_per_post_avg"),
        _fconf(feats, "posting_consistency_score"),
        _fconf(feats, "follower_following_ratio"),
    ]
    conf = round(sum(confidences) / len(confidences), 4)

    return DossierScore(
        value=int(round(clamp(raw))),
        signals=signals,
        confidence=conf,
    )


def score_authenticity(feats: dict[str, dict]) -> DossierScore:
    """Authenticity Score per spec §8."""
    completeness = _fval(feats, "account_completeness_score")
    ratio = _fval(feats, "follower_following_ratio")
    anomaly = _fval(feats, "engagement_anomaly", "none")
    pod = _fval(feats, "comment_pod_signal", "unknown")

    signals: list[str] = []

    completeness_component = (completeness * 100.0) if completeness is not None else 50.0
    signals.append(
        f"account_completeness_score={completeness}" if completeness is not None
        else "account_completeness_score unavailable — neutral 50"
    )

    ratio_component = _ratio_reasonableness(ratio) if ratio is not None else 50.0
    signals.append(
        f"follower_following_ratio={ratio}" if ratio is not None
        else "follower_following_ratio unavailable — neutral 50"
    )

    raw = (
        AUTH_WEIGHTS["completeness"] * completeness_component
        + AUTH_WEIGHTS["ratio"] * ratio_component
        + 0.50 * 50.0  # 50-point neutral baseline
    )

    if anomaly == "spike":
        raw -= 20.0
        signals.append("engagement_anomaly=spike: −20 penalty")
    if pod == "detected":
        raw -= 30.0
        signals.append("comment_pod_signal=detected: −30 penalty")

    confidences = [
        _fconf(feats, "account_completeness_score"),
        _fconf(feats, "follower_following_ratio"),
    ]
    conf = round(sum(confidences) / len(confidences), 4)

    return DossierScore(
        value=int(round(clamp(raw))),
        signals=signals,
        confidence=conf,
    )


def score_sponsorship_transparency(feats: dict[str, dict]) -> DossierScore:
    """Sponsorship Transparency Score per spec §8."""
    ftc_status = _fval(feats, "ftc_disclosure_status", "unknown")
    sponsored = _fval(feats, "sponsored_posts", [])
    undisclosed = _fval(feats, "likely_sponsored_undisclosed", [])

    base = {"compliant": 100, "partial": 60, "at_risk": 20, "unknown": 50}.get(
        ftc_status if isinstance(ftc_status, str) else "unknown", 50
    )

    signals = [f"ftc_disclosure_status={ftc_status}"]

    total_commercial = (len(sponsored) if isinstance(sponsored, list) else 0) + (
        len(undisclosed) if isinstance(undisclosed, list) else 0
    )
    disclosed = len(sponsored) if isinstance(sponsored, list) else 0

    if total_commercial > 0:
        ratio = disclosed / total_commercial
        raw = base * ratio + base * (1 - ratio) * 0.2
        signals.append(f"disclosed={disclosed}/{total_commercial} commercial posts")
    else:
        raw = float(base)
        signals.append("no commercial posts detected")

    conf = _fconf(feats, "ftc_disclosure_status", 0.7)

    return DossierScore(
        value=int(round(clamp(raw))),
        signals=signals,
        confidence=conf,
    )


def score_brand_safety(feats: dict[str, dict]) -> DossierScore:
    """Brand Safety Score per spec §8 (sentiment + absence of flagged topics)."""
    sentiment = _fval(feats, "caption_sentiment", "neutral")

    sentiment_score = {"positive": 90.0, "neutral": 70.0, "negative": 30.0}.get(
        sentiment if isinstance(sentiment, str) else "neutral", 70.0
    )

    signals = [f"caption_sentiment={sentiment}"]
    conf = _fconf(feats, "caption_sentiment", 0.7)

    return DossierScore(
        value=int(round(clamp(sentiment_score))),
        signals=signals,
        confidence=conf,
    )


def build_scores(feats: dict[str, dict]) -> dict[str, DossierScore]:
    return {
        "engagement_quality": score_engagement_quality(feats),
        "authenticity": score_authenticity(feats),
        "sponsorship_transparency": score_sponsorship_transparency(feats),
        "brand_safety": score_brand_safety(feats),
    }


# ── Report renderer (spec §8) ─────────────────────────────────────────────────

def _render_platform_section(block: "PlatformPresenceBlock") -> str:
    platform_slugs = ", ".join(block.platforms_found)
    n = len(block.rows)
    rows_md = "\n".join(
        f"| {row.platform.title()} | {row.handle_or_id} | {row.key_metric} |"
        for row in block.rows
    )
    return f"""---

## 8. Platform Presence

> Enrichment Uplift: {n} additional platform(s) detected via Stage 1B ({platform_slugs}).
> EQS, Brand Safety, and Sponsorship Transparency scores are based on Instagram data only.

| Platform | Handle / ID | Key Metric |
|---|---|---|
{rows_md}

{block.narrative}
"""


def render_report(
    dossier: Dossier,
    *,
    expose_art9: bool = False,
    platform_block: "PlatformPresenceBlock | None" = None,
) -> str:
    p = dossier.profile
    scores = dossier.scores
    feats = dossier.features
    cf = dossier.compliance_flags

    def _score_line(name: str, label: str) -> str:
        s = scores.get(name)
        if s is None:
            return f"- {label}: N/A"
        sigs = "; ".join(s.signals[:3])
        return f"- {label}: **{s.value}/100** (confidence {s.confidence:.0%}) — {sigs}"

    art9_section = gate_art9_report_exposure(cf.art9_features, expose_art9=expose_art9)

    handle = p.get("handle", "unknown")
    tier = feats.get("follower_tier", {}).get("value", "N/A")
    niche = feats.get("primary_niche", {}).get("value", "N/A")
    followers = p.get("followers", "N/A")
    bio = p.get("bio") or "—"
    snapshot = p.get("snapshot_at", "N/A")

    er_feat = feats.get("er_by_followers", {})
    er_val = er_feat.get("value")
    er_str = f"{er_val:.2f}%" if er_val is not None else "N/A"
    freq = feats.get("posting_frequency_per_week", {}).get("value")
    freq_str = f"{freq:.1f} posts/week" if freq is not None else "N/A"

    secondary = feats.get("secondary_niches", {}).get("value") or []
    secondary_str = ", ".join(secondary) if secondary else "None"
    ftc = cf.ftc_disclosure_status

    platform_section = _render_platform_section(platform_block) if platform_block and platform_block.rows else ""

    report = f"""# Creator Dossier — @{handle}

*Generated: {dossier.generated_at} | Pipeline v{dossier.provenance.pipeline_version}*

---

## 1. Creator Identity

| Field | Value |
|---|---|
| Handle | @{handle} |
| Tier | {tier} |
| Primary Niche | {niche} |
| Followers | {followers:,} |
| Snapshot | {snapshot} |

**Bio:** {bio}

---

## 2. Engagement Quality

{_score_line("engagement_quality", "Engagement Quality Score (EQS)")}

- ER by followers: {er_str}
- Posting cadence: {freq_str}

---

## 3. Content Profile

- Primary niche: **{niche}**
- Secondary niches: {secondary_str}
- FTC disclosure status: **{ftc}**

---

## 4. Authenticity Signals

{_score_line("authenticity", "Authenticity Score")}

> Note: Deep fake-follower analysis (Botometer-style follower-list traversal) is deferred to v2.
> Current scores are based on single-profile heuristics only.

---

## 5. Compliance Summary

- GDPR basis: **{cf.gdpr_basis}**
- Art. 22 applies: **{cf.art22_applies}** — human review required before any campaign selection decision
- Art. 9 features: {", ".join(art9_section) if art9_section else "none"}
- FTC status: **{ftc}**
- Opt-out path: `{cf.opt_out_path}`

---

## 6. Deferred Analyses

| Analysis | Status | When available |
|---|---|---|
| Cross-platform identity linkage | deferred | v3 |
| Audience overlap graph | deferred | v2 |
| Deep fake-follower detection | deferred | v2 |
| Audience demographics | deferred | v2 (requires creator consent) |

---

## 7. Provenance & Confidence Notes

- Source: `{dossier.provenance.source_id}`
- Stages run: {", ".join(dossier.provenance.stages_run)}
- Dossier ID: `{dossier.dossier_id}`

{_score_line("sponsorship_transparency", "Sponsorship Transparency")}
{_score_line("brand_safety", "Brand Safety")}

> Scores are advisory only. All campaign selection decisions require human review (GDPR Art. 22).
{platform_section}"""
    return report


# ── Stage 4 linkage surfacing (spec 0011 Track E) ────────────────────────────

def _load_linkage_block(project_dir: Path) -> dict:
    """Return the linkage block: surfaceable candidates from 04-linkage.json, or deferred."""
    linkage_path = project_dir / "04-linkage.json"
    if not linkage_path.exists():
        return {"status": "deferred", "candidates": []}
    try:
        with open(linkage_path) as f:
            doc = json.load(f)
    except Exception:
        return {"status": "deferred", "candidates": []}

    from pipeline.linkage.gate import apply_gate
    candidates = doc.get("candidates", [])
    # Defense-in-depth: re-apply the gate before surfacing
    gated = apply_gate(candidates)
    surfaceable = [c for c in gated if c.get("surfaceable")]
    if not surfaceable:
        return {"status": "deferred", "candidates": []}
    return {"status": "complete", "candidates": surfaceable}


# ── Stage 5 associations surfacing (spec 0012 Track F) ───────────────────────

def _load_associations_block(project_dir: Path) -> dict:
    """Return the associations block: ego view from 05-graph.json, or deferred."""
    graph_path = project_dir / "05-graph.json"
    if not graph_path.exists():
        return {"status": "deferred", "graph_summary": None}
    try:
        with open(graph_path) as f:
            doc = json.load(f)
    except Exception:
        return {"status": "deferred", "graph_summary": None}

    # Defense-in-depth: re-apply Art.9 gate on communities_summary
    communities = doc.get("communities_summary", [])
    redacted_communities = []
    for comm in communities:
        art9_risk = comm.get("art9_risk", False)
        entry = dict(comm)
        if art9_risk:
            entry["members"] = []  # redact member list without consent
        redacted_communities.append(entry)

    ego_view = {
        "ego": doc.get("ego"),
        "neighbors": doc.get("neighbors", []),
        "communities_summary": redacted_communities,
        "community_method": doc.get("community_method"),
        "cohort_size": doc.get("cohort_size"),
    }
    return {"status": "complete", "graph_summary": ego_view}


# ── Stage 1B enrichment map loader (spec 0015) ───────────────────────────────

def _load_enrichment_map(project_dir: Path) -> dict | None:
    path = project_dir / "enrichment_map.json"
    if not path.exists():
        return None
    try:
        with open(path) as fh:
            return json.load(fh)
    except json.JSONDecodeError:
        logging.getLogger(__name__).warning(
            "enrichment_map.json at %s is malformed JSON; skipping platform presence", path
        )
        return None


# ── Orchestrator ──────────────────────────────────────────────────────────────

def run(
    handle: str,
    project_dir: Path,
    *,
    pipeline_version: str = "0.1.0",
    expose_art9: bool = False,
    expose_osint: bool = False,
) -> Path:
    """Run Stage 6 for *handle*, reading 03-features.json and writing 06-dossier.json + report.md."""
    feat_path = project_dir / "03-features.json"
    norm_path = project_dir / "02-normalized.json"

    if not feat_path.exists():
        raise FileNotFoundError(f"Stage 3 artifact not found: {feat_path}")
    if not norm_path.exists():
        raise FileNotFoundError(f"Stage 2 artifact not found: {norm_path}")

    with open(feat_path) as fh:
        features_doc = json.load(fh)
    with open(norm_path) as fh:
        normalized = json.load(fh)

    gov = normalized.get("governance", {})
    assert_within_retention(gov, handle=handle)

    feats = index_features(features_doc)

    # Build scores
    scores = build_scores(feats)

    # Art.22 explainability check
    scores_dict = {k: v.model_dump() for k, v in scores.items()}
    assert_scores_explainable(scores_dict)

    # Art.9 IDs
    scanner = Art9Scanner()
    art9_ids = [
        f["feature_id"]
        for f in features_doc.get("features", [])
        if f.get("art9_risk")
    ]

    ftc_status = features_doc.get("ftc_disclosure_status", "unknown")

    # Compliance flags
    cf_dict = build_compliance_flags(
        governance=gov,
        scores=scores_dict,
        art9_feature_ids=art9_ids,
        ftc_disclosure_status=ftc_status,
        handle=handle,
    )

    # Assemble Dossier model
    dossier_id = str(uuid.uuid4())
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Stage 1B enrichment — platform presence (spec 0015)
    enrichment_map = _load_enrichment_map(project_dir)
    platform_block = PlatformPresenceExtractor.extract(
        enrichment_map,
        expose_osint=expose_osint,
        handle=handle,
    )

    dossier = Dossier(
        dossier_id=dossier_id,
        generated_at=generated_at,
        profile=normalized,
        features={f["feature_id"]: f for f in features_doc.get("features", [])},
        scores=scores,
        linkage=_load_linkage_block(project_dir),
        associations=_load_associations_block(project_dir),
        compliance_flags=ComplianceFlags(**cf_dict),
        provenance=Provenance(
            source_id=gov.get("source_id", "unknown"),
            pipeline_version=pipeline_version,
            stages_run=["ingest", "normalize", "features", "dossier"],
            stage_artifacts={
                "01": str(project_dir / "01-raw.json"),
                "02": str(project_dir / "02-normalized.json"),
                "03": str(project_dir / "03-features.json"),
                "06": str(project_dir / "06-dossier.json"),
            },
        ),
    )

    # Validate against schema
    dossier_dict = dossier.model_dump()
    # Convert DossierScore objects nested in scores to plain dicts
    dossier_dict["scores"] = {k: v.model_dump() for k, v in scores.items()}
    dossier_dict["compliance_flags"] = cf_dict
    dossier_dict["provenance"] = dossier.provenance.model_dump()
    pp = dataclasses.asdict(platform_block)
    pp.pop("narrative", None)   # narrative is for report.md only, not dossier JSON
    dossier_dict["platform_presence"] = pp

    schema = _load_schema()
    jsonschema.validate(dossier_dict, schema)

    # Render report
    report_md = render_report(dossier, expose_art9=expose_art9, platform_block=platform_block)

    # Atomic writes
    project_dir.mkdir(parents=True, exist_ok=True)
    out_path = project_dir / "06-dossier.json"
    tmp_path = out_path.with_suffix(".tmp")
    with open(tmp_path, "w") as fh:
        json.dump(dossier_dict, fh, indent=2)
    os.replace(tmp_path, out_path)

    report_path = project_dir / "report.md"
    tmp_report = report_path.with_suffix(".tmp")
    with open(tmp_report, "w") as fh:
        fh.write(report_md)
    os.replace(tmp_report, report_path)

    return out_path
