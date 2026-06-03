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
from pipeline.diagnostics import build_derived_insights, build_derived_diagnostics
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

_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "exec_summary": "Executive Summary",
        "key_findings": "Key Findings",
        "contributions": "Contributions",
        "key_risks": "Key risks",
        "key_opportunities": "Key opportunities",
        "eqs_er": "ER vs benchmark",
        "eqs_comments": "Comment volume",
        "eqs_consistency": "Posting frequency",
        "eqs_ratio": "Follower/following ratio",
        "eqs_pod": "Pod engagement penalty",
        "auth_completeness": "Profile completeness",
        "auth_ratio": "Follower/following ratio",
        "auth_anomaly": "Engagement spike penalty",
        "auth_pod": "Pod engagement penalty",
        "spon_base": "FTC disclosure status",
        "spon_ratio": "Commercial disclosure ratio",
        "safety_sentiment": "Caption sentiment",
    },
    "pt": {
        "exec_summary": "Resumo Executivo",
        "key_findings": "Principais Achados",
        "contributions": "Contribuições",
        "key_risks": "Principais riscos",
        "key_opportunities": "Principais oportunidades",
        "eqs_er": "ER vs referência",
        "eqs_comments": "Volume de comentários",
        "eqs_consistency": "Frequência de postagem",
        "eqs_ratio": "Ratio seguidores/seguindo",
        "eqs_pod": "Penalidade de pod",
        "auth_completeness": "Completude do perfil",
        "auth_ratio": "Ratio seguidores/seguindo",
        "auth_anomaly": "Penalidade de spike",
        "auth_pod": "Penalidade de pod",
        "spon_base": "Status FTC",
        "spon_ratio": "Posts comerciais divulgados",
        "safety_sentiment": "Sentimento das legendas",
    },
}


def _detect_language(governance: dict) -> str:
    """Return 'pt' for Brazilian profiles, 'en' otherwise."""
    return "pt" if governance.get("subject_jurisdiction") == "BR" else "en"


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
    contributions: list[list] = []

    if er is not None:
        er_component = er_vs_benchmark(er, tier)
        contributions.append(["eqs_er", round((er_component - 50.0) * EQS_WEIGHTS["er"], 1)])
        signals.append(f"er_by_followers={er}% vs {tier} benchmark {TIER_BENCHMARK_ER.get(tier)}%")
    else:
        er_component = 50.0
        signals.append("er_by_followers unavailable — using neutral 50")

    if comments_avg is not None:
        comments_component = clamp((comments_avg / 30.0) * 100)
        contributions.append(["eqs_comments", round((comments_component - 50.0) * EQS_WEIGHTS["comments"], 1)])
        signals.append(f"comments_per_post_avg={comments_avg}")
    else:
        comments_component = 50.0
        signals.append("comments_per_post_avg unavailable — using neutral 50")

    if consistency is not None:
        consistency_component = consistency * 100.0
        contributions.append(["eqs_consistency", round((consistency_component - 50.0) * EQS_WEIGHTS["consistency"], 1)])
        signals.append(f"posting_consistency_score={consistency}")
    else:
        consistency_component = 50.0
        signals.append("posting_consistency_score unavailable — using neutral 50")

    if ratio is not None:
        ratio_component = _ratio_reasonableness(ratio)
        contributions.append(["eqs_ratio", round((ratio_component - 50.0) * EQS_WEIGHTS["ratio"], 1)])
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
        contributions.append(["eqs_pod", -20.0])
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
        contributions=contributions,
        confidence=conf,
    )


def score_authenticity(feats: dict[str, dict]) -> DossierScore:
    """Authenticity Score per spec §8."""
    completeness = _fval(feats, "account_completeness_score")
    ratio = _fval(feats, "follower_following_ratio")
    anomaly = _fval(feats, "engagement_anomaly", "none")
    pod = _fval(feats, "comment_pod_signal", "unknown")

    signals: list[str] = []
    contributions: list[list] = []

    if completeness is not None:
        completeness_component = completeness * 100.0
        contributions.append(["auth_completeness", round((completeness_component - 50.0) * AUTH_WEIGHTS["completeness"], 1)])
        signals.append(f"account_completeness_score={completeness}")
    else:
        completeness_component = 50.0
        signals.append("account_completeness_score unavailable — neutral 50")

    if ratio is not None:
        ratio_component = _ratio_reasonableness(ratio)
        contributions.append(["auth_ratio", round((ratio_component - 50.0) * AUTH_WEIGHTS["ratio"], 1)])
        signals.append(f"follower_following_ratio={ratio}")
    else:
        ratio_component = 50.0
        signals.append("follower_following_ratio unavailable — neutral 50")

    raw = (
        AUTH_WEIGHTS["completeness"] * completeness_component
        + AUTH_WEIGHTS["ratio"] * ratio_component
        + 0.50 * 50.0  # 50-point neutral baseline
    )

    if anomaly == "spike":
        raw -= 20.0
        contributions.append(["auth_anomaly", -20.0])
        signals.append("engagement_anomaly=spike: −20 penalty")
    if pod == "detected":
        raw -= 30.0
        contributions.append(["auth_pod", -30.0])
        signals.append("comment_pod_signal=detected: −30 penalty")

    confidences = [
        _fconf(feats, "account_completeness_score"),
        _fconf(feats, "follower_following_ratio"),
    ]
    conf = round(sum(confidences) / len(confidences), 4)

    return DossierScore(
        value=int(round(clamp(raw))),
        signals=signals,
        contributions=contributions,
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
    contributions: list[list] = [["spon_base", float(base - 50)]]

    total_commercial = (len(sponsored) if isinstance(sponsored, list) else 0) + (
        len(undisclosed) if isinstance(undisclosed, list) else 0
    )
    disclosed = len(sponsored) if isinstance(sponsored, list) else 0

    if total_commercial > 0:
        ratio = disclosed / total_commercial
        raw = base * ratio + base * (1 - ratio) * 0.2
        delta = round(raw - base, 1)
        if delta != 0:
            contributions.append(["spon_ratio", delta])
        signals.append(f"disclosed={disclosed}/{total_commercial} commercial posts")
    else:
        raw = float(base)
        signals.append("no commercial posts detected")

    conf = _fconf(feats, "ftc_disclosure_status", 0.7)

    return DossierScore(
        value=int(round(clamp(raw))),
        signals=signals,
        contributions=contributions,
        confidence=conf,
    )


def score_brand_safety(feats: dict[str, dict]) -> DossierScore:
    """Brand Safety Score per spec §8 (sentiment + absence of flagged topics)."""
    sentiment = _fval(feats, "caption_sentiment", "neutral")

    sentiment_score = {"positive": 90.0, "neutral": 70.0, "negative": 30.0}.get(
        sentiment if isinstance(sentiment, str) else "neutral", 70.0
    )

    signals = [f"caption_sentiment={sentiment}"]
    contributions: list[list] = [["safety_sentiment", round(sentiment_score - 50.0, 1)]]
    conf = _fconf(feats, "caption_sentiment", 0.7)

    return DossierScore(
        value=int(round(clamp(sentiment_score))),
        signals=signals,
        contributions=contributions,
        confidence=conf,
    )


def build_scores(feats: dict[str, dict]) -> dict[str, DossierScore]:
    return {
        "engagement_quality": score_engagement_quality(feats),
        "authenticity": score_authenticity(feats),
        "sponsorship_transparency": score_sponsorship_transparency(feats),
        "brand_safety": score_brand_safety(feats),
    }


# ── Report helpers ────────────────────────────────────────────────────────────

def _contributions_md(score: "DossierScore", lang: str) -> str:
    """Format per-component contributions as an indented markdown list."""
    if not score.contributions:
        return ""
    L = _LABELS[lang]
    header = L.get("contributions", "Contributions")
    lines = []
    for key, delta in score.contributions:
        label = L.get(key, key)
        lines.append(f"  - {label}: ({delta:+.0f})")
    return f"  _{header}:_\n" + "\n".join(lines)


def _render_executive_summary(
    handle: str,
    tier: str,
    niche: str,
    niche_conf: float,
    followers: int,
    freq: float | None,
    er: float | None,
    scores: dict[str, "DossierScore"],
    ftc: str,
    lang: str,
) -> str:
    L = _LABELS[lang]
    eqs = scores.get("engagement_quality")
    benchmark = TIER_BENCHMARK_ER.get(tier)

    if lang == "pt":
        intro = f"Perfil de criador {tier} focado em **{niche}** com {followers:,} seguidores."
    else:
        intro = f"{tier} creator profile focused on **{niche}** with {followers:,} followers."

    paragraphs = [intro]

    if freq is not None:
        if lang == "pt":
            paragraphs.append(f"O criador apresenta {freq:.1f} posts/semana.")
        else:
            paragraphs.append(f"The creator posts {freq:.1f} times/week.")

    if er is not None and benchmark is not None:
        if lang == "pt":
            direction = "acima" if er > benchmark else "abaixo"
            paragraphs.append(
                f"O engajamento está {direction} do benchmark para criadores {tier} ({er:.1f}% vs {benchmark:.1f}%)."
            )
        else:
            direction = "above" if er > benchmark else "below"
            paragraphs.append(
                f"Engagement is {direction} the {tier} creator benchmark ({er:.1f}% vs {benchmark:.1f}%)."
            )
    elif eqs is not None:
        if lang == "pt":
            level = "abaixo da referência" if eqs.value < 40 else "acima da referência" if eqs.value > 60 else "próximo da referência"
            paragraphs.append(f"Qualidade de engajamento {level} (EQS: {eqs.value}/100).")
        else:
            level = "below benchmark" if eqs.value < 40 else "above benchmark" if eqs.value > 60 else "near benchmark"
            paragraphs.append(f"Engagement quality {level} (EQS: {eqs.value}/100).")

    conf_level = ("high" if niche_conf > 0.8 else "moderate" if niche_conf > 0.5 else "low")
    conf_level_pt = ("alta" if niche_conf > 0.8 else "moderada" if niche_conf > 0.5 else "baixa")
    if lang == "pt":
        paragraphs.append(f"A classificação de nicho possui confiança {conf_level_pt}.")
    else:
        paragraphs.append(f"The niche classification has {conf_level} confidence.")

    # Risks
    risks: list[str] = []
    auth = scores.get("authenticity")
    if eqs and eqs.value < 40:
        risks.append("Engajamento abaixo da média" if lang == "pt" else "Below-average engagement")
    if auth and any("pod" in s for s in auth.signals if "detected" in s):
        risks.append("Sinal de pod de engajamento detectado" if lang == "pt" else "Engagement pod signal detected")
    if ftc in ("unknown", "at_risk"):
        risks.append("Histórico comercial desconhecido ou em risco FTC" if lang == "pt" else "Unknown commercial history or FTC risk")
    if auth and auth.value < 40:
        risks.append("Completude de perfil abaixo do mínimo" if lang == "pt" else "Profile completeness below minimum")

    # Opportunities
    opps: list[str] = []
    if niche_conf > 0.8 and niche not in ("Other", "Unknown"):
        opps.append(f"Audiência especializada em {niche}" if lang == "pt" else f"Specialized audience in {niche}")
    if niche not in ("Other", "Unknown"):
        opps.append("Posicionamento claro de nicho" if lang == "pt" else "Clear niche positioning")
    if freq is not None and freq >= 2:
        opps.append(f"Frequência saudável de publicação ({freq:.1f}/semana)" if lang == "pt" else f"Healthy posting frequency ({freq:.1f}/week)")
    brand = scores.get("brand_safety")
    if brand and brand.value >= 70:
        opps.append("Perfil de segurança de marca positivo" if lang == "pt" else "Positive brand safety profile")

    risks_header = f"**{L['key_risks']}:**"
    opps_header = f"**{L['key_opportunities']}:**"
    risks_md = "\n".join(f"- {r}" for r in risks) if risks else ("- " + ("Nenhum risco crítico identificado" if lang == "pt" else "No critical risks identified"))
    opps_md = "\n".join(f"- {o}" for o in opps) if opps else ("- " + ("Dados insuficientes" if lang == "pt" else "Insufficient data"))

    body = "\n\n".join(paragraphs)
    return f"## {L['exec_summary']}\n\n{body}\n\n{risks_header}\n{risks_md}\n\n{opps_header}\n{opps_md}\n"


def _render_key_findings(
    niche: str,
    niche_conf: float,
    tier: str,
    er: float | None,
    freq: float | None,
    scores: dict[str, "DossierScore"],
    ftc: str,
    lang: str,
) -> str:
    L = _LABELS[lang]
    findings: list[str] = []

    # 1. Niche clarity
    conf_label = "high" if niche_conf > 0.8 else "moderate" if niche_conf > 0.5 else "low"
    conf_label_pt = "alta" if niche_conf > 0.8 else "moderada" if niche_conf > 0.5 else "baixa"
    if lang == "pt":
        findings.append(f"Nicho {'claramente definido' if niche_conf > 0.8 else 'identificado'} em **{niche}** (confiança {conf_label_pt}).")
    else:
        findings.append(f"Niche {'clearly defined' if niche_conf > 0.8 else 'identified'} as **{niche}** ({conf_label} confidence).")

    # 2. Engagement vs benchmark
    eqs = scores.get("engagement_quality")
    benchmark = TIER_BENCHMARK_ER.get(tier)
    if er is not None and benchmark is not None:
        if lang == "pt":
            direction = "acima" if er > benchmark else "abaixo"
            findings.append(f"Engajamento {direction} da média para criadores {tier} ({er:.1f}% vs {benchmark:.1f}% de referência).")
        else:
            direction = "above" if er > benchmark else "below"
            findings.append(f"Engagement {direction} average for {tier} creators ({er:.1f}% vs {benchmark:.1f}% benchmark).")
    elif eqs:
        if lang == "pt":
            findings.append(f"Qualidade de engajamento: {eqs.value}/100 (ER indisponível).")
        else:
            findings.append(f"Engagement quality: {eqs.value}/100 (ER data unavailable).")

    # 3. Posting activity
    if freq is not None:
        if lang == "pt":
            level = "consistente" if freq >= 3 else "moderada" if freq >= 1 else "baixa"
            findings.append(f"Atividade de publicação {level} ({freq:.1f} posts/semana).")
        else:
            level = "consistent" if freq >= 3 else "moderate" if freq >= 1 else "low"
            findings.append(f"{level.capitalize()} posting activity ({freq:.1f} posts/week).")
    else:
        findings.append("Frequência de publicação indisponível." if lang == "pt" else "Posting frequency data unavailable.")

    # 4. Fraud signals
    auth = scores.get("authenticity")
    if auth:
        has_fraud_signal = any(
            ("pod" in s and "detected" in s) or "spike" in s
            for s in auth.signals
        )
        if has_fraud_signal:
            findings.append("Sinais de engajamento artificial detectados — revisão recomendada." if lang == "pt" else "Artificial engagement signals detected — review recommended.")
        else:
            findings.append("Nenhum sinal forte de fraude encontrado." if lang == "pt" else "No strong fraud signals found.")

    # 5. Commercial history
    if ftc == "compliant":
        findings.append("Histórico de divulgação de parceria em conformidade com FTC." if lang == "pt" else "FTC-compliant partnership disclosure history.")
    elif ftc == "at_risk":
        findings.append("Risco FTC identificado — posts patrocinados sem divulgação adequada." if lang == "pt" else "FTC risk identified — sponsored posts without proper disclosure.")
    else:
        findings.append("Ausência de evidências de experiência comercial identificada." if lang == "pt" else "No evidence of commercial campaign history found.")

    numbered = "\n".join(f"{i + 1}. {f}" for i, f in enumerate(findings))
    return f"## {L['key_findings']}\n\n{numbered}\n"


# ── Report renderer (spec §8) ─────────────────────────────────────────────────

_ARCHETYPE_DISPLAY: dict[str, tuple[str, str]] = {
    "specialist_educator": (
        "Specialist Educator",
        "A focused expert in a professional niche who publishes consistently high-quality, on-topic content.",
    ),
    "thought_leader": (
        "Thought Leader",
        "An influential voice who publishes infrequently but drives above-average engagement in a professional domain.",
    ),
    "brand_builder": (
        "Brand Builder",
        "A creator whose content mix includes significant commercial or partnership material.",
    ),
    "entertainer": (
        "Entertainer",
        "A high-frequency creator in an entertainment niche whose content is optimised for reach and virality.",
    ),
    "lifestyle_blogger": (
        "Lifestyle Blogger",
        "A broad-interest creator publishing personal or aspirational content across lifestyle topics.",
    ),
    "content_creator": (
        "Content Creator",
        "A general creator whose content does not fit a more specific archetype.",
    ),
}

_LIFECYCLE_DISPLAY: dict[str, tuple[str, str]] = {
    "nascent": (
        "Nascent",
        "Early-stage account still building an audience and establishing a content identity.",
    ),
    "nascent_stalled": (
        "Nascent (Stalled)",
        "Early-stage account with low posting consistency, suggesting limited active growth.",
    ),
    "early_growth": (
        "Early Growth",
        "Account gaining traction with a growing and engaged audience.",
    ),
    "scaling": (
        "Scaling",
        "Mid-tier account actively expanding reach with sustained engagement.",
    ),
    "established": (
        "Established",
        "Mature account with a stable, sizable audience and predictable performance.",
    ),
    "mature": (
        "Mature",
        "Large-scale account with a broad audience and established brand recognition.",
    ),
    "plateaued": (
        "Plateaued",
        "Account showing engagement below tier benchmark, suggesting slowed momentum.",
    ),
}

_READINESS_DISPLAY: dict[str, tuple[str, str]] = {
    "high": (
        "High",
        "Strong compliance record, authentic engagement, and brand-safe content make this profile ready for partnerships.",
    ),
    "medium": (
        "Medium",
        "Adequate compliance and engagement signals; review FTC status before campaign activation.",
    ),
    "low": (
        "Low",
        "One or more risk factors — FTC compliance, authenticity, or brand safety — require resolution before partnerships.",
    ),
}

_SEVERITY_DISPLAY: dict[str, str] = {
    "high": "High",
    "medium": "Medium",
    "low": "Low",
}


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


def _render_diagnostics_section(derived_insights, derived_diagnostics) -> str:
    """Render the Creator Diagnostics section (§9) for report.md.

    Returns an empty string when *derived_diagnostics* is None (backward-compatible).
    """
    if derived_diagnostics is None:
        return ""

    # ── Archetype ──────────────────────────────────────────────────────────────
    archetype = derived_diagnostics.creator_archetype
    arch_title, arch_desc = _ARCHETYPE_DISPLAY.get(
        archetype.value, (archetype.value, "")
    )
    evidence_str = ", ".join(archetype.evidence) if archetype.evidence else "—"
    matched_rule = archetype.matched_rule if archetype.matched_rule else "—"

    # ── Lifecycle ──────────────────────────────────────────────────────────────
    lifecycle = derived_diagnostics.lifecycle_stage
    lc_title, lc_desc = _LIFECYCLE_DISPLAY.get(
        lifecycle.value, (lifecycle.value, "")
    )
    creator_size = derived_diagnostics.creator_size
    creator_size_str = creator_size.value.title() if creator_size else "—"

    # ── Sponsorship readiness ──────────────────────────────────────────────────
    readiness = derived_diagnostics.sponsorship_readiness
    rd_title, rd_desc = _READINESS_DISPLAY.get(
        readiness.value, (readiness.value, "")
    )

    # ── Brand fit ─────────────────────────────────────────────────────────────
    brand_fit_entries = derived_diagnostics.brand_fit
    high_fit_categories = [e.category.replace("_", " ").title() for e in brand_fit_entries if e.fit == "high"]
    medium_fit_categories = [e.category.replace("_", " ").title() for e in brand_fit_entries if e.fit == "medium"]
    high_fit_str = ", ".join(high_fit_categories) if high_fit_categories else "None identified"
    medium_fit_str = ", ".join(medium_fit_categories) if medium_fit_categories else "None identified"

    # ── Risk flags ────────────────────────────────────────────────────────────
    risk_flags = derived_diagnostics.risk_flags
    if risk_flags:
        risk_rows = "\n".join(
            f"| {flag.flag.replace('_', ' ').title()} | {_SEVERITY_DISPLAY.get(flag.severity, flag.severity)} |"
            for flag in risk_flags
        )
    else:
        risk_rows = "| No risk flags identified | — |"

    return f"""---

## 9. Creator Diagnostics

### Creator Archetype

**{arch_title}** — {arch_desc}

*Evidence:* {evidence_str} · Rule: `{matched_rule}` · Confidence: {archetype.confidence:.0%}

### Lifecycle Stage

**{lc_title}** — {lc_desc}

*Creator size:* {creator_size_str} · Confidence: {lifecycle.confidence:.0%}

### Sponsorship Readiness

**{rd_title}** — {rd_desc}

### Brand Fit

**High fit:** {high_fit_str}

**Medium fit:** {medium_fit_str}

### Risk Assessment

| Risk | Severity |
|---|---|
{risk_rows}

> All diagnostics are derived labels, not facts. Recomputed each pipeline run.
"""


def render_report(
    dossier: Dossier,
    *,
    expose_art9: bool = False,
    platform_block: "PlatformPresenceBlock | None" = None,
    derived_insights=None,
    derived_diagnostics=None,
) -> str:
    p = dossier.profile
    scores = dossier.scores
    feats = dossier.features
    cf = dossier.compliance_flags

    lang = _detect_language(p.get("governance", {}))

    def _score_section(name: str, label: str) -> str:
        s = scores.get(name)
        if s is None:
            return f"- {label}: N/A"
        sigs = "; ".join(s.signals[:3])
        header = f"- {label}: **{s.value}/100** (confidence {s.confidence:.0%}) — {sigs}"
        breakdown = _contributions_md(s, lang)
        return f"{header}\n{breakdown}" if breakdown else header

    art9_section = gate_art9_report_exposure(cf.art9_features, expose_art9=expose_art9)

    handle = p.get("handle", "unknown")
    tier = feats.get("follower_tier", {}).get("value", "N/A")
    niche = feats.get("primary_niche", {}).get("value", "N/A")
    niche_conf = feats.get("primary_niche", {}).get("confidence", 0.0)
    followers = p.get("followers", 0)
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

    exec_summary = _render_executive_summary(
        handle=handle,
        tier=tier,
        niche=niche,
        niche_conf=niche_conf,
        followers=followers,
        freq=freq,
        er=er_val,
        scores=scores,
        ftc=ftc,
        lang=lang,
    )

    key_findings = _render_key_findings(
        niche=niche,
        niche_conf=niche_conf,
        tier=tier,
        er=er_val,
        freq=freq,
        scores=scores,
        ftc=ftc,
        lang=lang,
    )

    platform_section = _render_platform_section(platform_block) if platform_block and platform_block.rows else ""
    diagnostics_section = _render_diagnostics_section(derived_insights, derived_diagnostics)

    report = f"""# Creator Dossier — @{handle}

*Generated: {dossier.generated_at} | Pipeline v{dossier.provenance.pipeline_version}*

---

{exec_summary}

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

{_score_section("engagement_quality", "Engagement Quality Score (EQS)")}

- ER by followers: {er_str}
- Posting cadence: {freq_str}

---

## 3. Content Profile

- Primary niche: **{niche}**
- Secondary niches: {secondary_str}
- FTC disclosure status: **{ftc}**

---

## 4. Authenticity Signals

{_score_section("authenticity", "Authenticity Score")}

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

{key_findings}

---

## 7. Provenance & Confidence Notes

- Source: `{dossier.provenance.source_id}`
- Stages run: {", ".join(dossier.provenance.stages_run)}
- Dossier ID: `{dossier.dossier_id}`

{_score_section("sponsorship_transparency", "Sponsorship Transparency")}
{_score_section("brand_safety", "Brand Safety")}

> Scores are advisory only. All campaign selection decisions require human review (GDPR Art. 22).
{platform_section}{diagnostics_section}"""
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

    # Diagnostics — Layer 3 (spec 0016 Track D)
    media_items = normalized.get("media", [])
    tier_val = _fval(feats, "follower_tier", "Mid")
    niche_val = _fval(feats, "primary_niche", "Unknown")
    niche_conf_val = _fconf(feats, "primary_niche", 0.5)
    secondary_val = _fval(feats, "secondary_niches", []) or []
    freq_val = _fval(feats, "posting_frequency_per_week", 0.0) or 0.0
    consistency_val = _fval(feats, "posting_consistency_score", 0.5) or 0.5
    pod_val = _fval(feats, "comment_pod_signal", "unknown")
    anomaly_val = _fval(feats, "engagement_anomaly", "none")
    followers_val = normalized.get("followers", 0)

    derived_insights = build_derived_insights(media_items, feats)
    derived_diagnostics = build_derived_diagnostics(
        feats=feats,
        scores=scores,
        insights=derived_insights,
        tier=tier_val,
        niche=niche_val,
        niche_conf=niche_conf_val,
        secondary_niches=secondary_val,
        freq=freq_val,
        consistency=consistency_val,
        ftc_status=ftc_status,
        pod_signal=pod_val,
        engagement_anomaly=anomaly_val,
        followers=followers_val,
    )

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

    dossier_dict["derived_insights"] = derived_insights.model_dump()
    dossier_dict["derived_diagnostics"] = derived_diagnostics.model_dump()

    schema = _load_schema()
    jsonschema.validate(dossier_dict, schema)

    # Render report
    report_md = render_report(
        dossier,
        expose_art9=expose_art9,
        platform_block=platform_block,
        derived_insights=derived_insights,
        derived_diagnostics=derived_diagnostics,
    )

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
