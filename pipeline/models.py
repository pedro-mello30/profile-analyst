"""Shared Pydantic v2 models for the profile-analyst pipeline (spec §4, §8)."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class GovernanceBlock(BaseModel):
    source_id: str
    data_category: str
    tos_compliant_at_ingest: bool
    ingested_at: str
    gdpr_basis: str
    subject_jurisdiction: str
    retention_expires_at: str
    consent_record_id: str | None = None


class MediaItem(BaseModel):
    media_id: str
    media_type: str
    posted_at: str
    likes: int | None = None
    comments: int | None = None
    saves: int | None = None
    shares: int | None = None
    views: int | None = None
    caption: str | None = None
    hashtags: list[str] = Field(default_factory=list)
    mentions: list[str] = Field(default_factory=list)
    is_paid_partnership: bool = False
    paid_partner_handle: str | None = None


class AudienceSummary(BaseModel):
    gender_split: dict[str, float] | None = None
    age_distribution: dict[str, float] | None = None
    top_locations: list[str] | None = None


class Profile(BaseModel):
    handle: str
    platform: str = "instagram"
    profile_id: str | None = None
    display_name: str | None = None
    bio: str | None = None
    website: str | None = None
    is_verified: bool = False
    is_business: bool = False
    account_type: str | None = None
    followers: int
    following: int
    post_count: int
    snapshot_at: str
    media: list[MediaItem] = Field(default_factory=list)
    audience: AudienceSummary | None = None
    governance: GovernanceBlock

    @field_validator("followers", "following", "post_count")
    @classmethod
    def non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("Must be non-negative")
        return v


# ── Dossier models ────────────────────────────────────────────────────────────

class DossierScore(BaseModel):
    value: int = Field(ge=0, le=100)
    signals: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    contributions: list[list] = Field(default_factory=list)  # [[key, delta], ...]


class ComplianceFlags(BaseModel):
    gdpr_basis: str
    art22_applies: bool
    art22_human_review_required: bool
    art9_features: list[str] = Field(default_factory=list)
    ftc_disclosure_status: str
    tos_compliant_source: bool
    opt_out_path: str


class Provenance(BaseModel):
    source_id: str
    pipeline_version: str
    stages_run: list[str]
    stage_artifacts: dict[str, str]


class Dossier(BaseModel):
    dossier_id: str
    generated_at: str
    profile: dict[str, Any]
    features: dict[str, Any]
    scores: dict[str, DossierScore]
    linkage: dict[str, Any]
    associations: dict[str, Any]
    compliance_flags: ComplianceFlags
    provenance: Provenance
    derived_insights: dict[str, Any] | None = None
    derived_diagnostics: dict[str, Any] | None = None


# ── Layer 3 diagnostics models (spec 0016) ───────────────────────────────────

class TopicEntry(BaseModel):
    topic: str
    share: float = Field(ge=0, le=1)
    evidence_media_ids: list[str]


class ThemeMix(BaseModel):
    values: dict[str, float]
    unmapped_ratio: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    method: Literal["heuristic"] = "heuristic"
    version: str = "v1"


class ContentFormatMix(BaseModel):
    values: dict[str, float]
    method: Literal["computed"] = "computed"


class EditorialConsistencyScore(BaseModel):
    value: int = Field(ge=0, le=100)
    method: Literal["heuristic"] = "heuristic"
    # confidence intentionally omitted — it lives on the parent ThemeMix (spec §6.1)


class ContentAnalysis(BaseModel):
    theme_mix: ThemeMix | None = None
    top_topics: list[TopicEntry] = Field(default_factory=list)
    editorial_consistency_score: EditorialConsistencyScore | None = None
    content_format_mix: ContentFormatMix | None = None


class DerivedInsights(BaseModel):
    computed_at: str
    content_analysis: ContentAnalysis


class LabeledInterpretation(BaseModel):
    value: str
    confidence: float = Field(ge=0.0, le=1.0)
    method: Literal["rule_based", "score_derived", "heuristic", "llm", "inferred", "computed"]
    version: str = "v1"
    evidence: list[str] = Field(default_factory=list)
    matched_rule: str | None = None


class BrandFitEntry(BaseModel):
    category: str
    fit: Literal["high", "medium", "low"]
    confidence: float = Field(ge=0.0, le=1.0)
    method: Literal["rule_based"] = "rule_based"


class RiskFlag(BaseModel):
    flag: str
    severity: Literal["high", "medium", "low"]
    method: Literal["rule_based", "score_derived"] = "rule_based"
    evidence: list[str] = Field(default_factory=list)


class CreatorSizeField(BaseModel):
    value: Literal["nano", "micro", "mid", "macro", "mega", "unknown"]
    method: Literal["computed"] = "computed"


class DerivedDiagnostics(BaseModel):
    computed_at: str
    creator_archetype: LabeledInterpretation
    creator_size: CreatorSizeField
    lifecycle_stage: LabeledInterpretation
    sponsorship_readiness: LabeledInterpretation
    brand_fit: list[BrandFitEntry] = Field(default_factory=list)
    risk_flags: list[RiskFlag] = Field(default_factory=list)


# ── Linkage models (spec 0011, Stage 4 v3a) ──────────────────────────────────

class FeatureEvidence(BaseModel):
    feature: str = Field(min_length=1)
    agreement: float = Field(ge=0.0, le=1.0)
    detail: str

    model_config = {"extra": "forbid"}


class LinkageCandidate(BaseModel):
    platform: str = Field(min_length=1)
    candidate_handle: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    likelihood_ratio: float
    feature_evidence: list[FeatureEvidence] = Field(min_length=1)
    classification: str  # link | possible_link | non_link
    multi_match_flag: bool
    manual_review_required: bool
    human_review_status: str  # pending | approved | rejected
    consent_record_id: str | None
    surfaceable: bool

    model_config = {"extra": "forbid"}

    @field_validator("classification")
    @classmethod
    def valid_classification(cls, v: str) -> str:
        if v not in {"link", "possible_link", "non_link"}:
            raise ValueError(f"Invalid classification: {v}")
        return v

    @field_validator("human_review_status")
    @classmethod
    def valid_review_status(cls, v: str) -> str:
        if v not in {"pending", "approved", "rejected"}:
            raise ValueError(f"Invalid human_review_status: {v}")
        return v


class LinkageDocument(BaseModel):
    handle: str = Field(min_length=1)
    method_version: str = "v3a"
    computed_at: str | None = None
    governance: dict[str, Any]
    candidates: list[LinkageCandidate]

    model_config = {"extra": "forbid"}

    @field_validator("method_version")
    @classmethod
    def valid_version(cls, v: str) -> str:
        if v != "v3a":
            raise ValueError(f"method_version must be v3a, got {v!r}")
        return v


# ── Association graph models (spec 0012, Stage 5 v2a) ────────────────────────

class EgoCentrality(BaseModel):
    degree: float = Field(ge=0.0, le=1.0)
    pagerank: float = Field(ge=0.0)
    betweenness: float = Field(ge=0.0, le=1.0)

    model_config = {"extra": "forbid"}


class EgoView(BaseModel):
    community_id: int
    community_size: int = Field(ge=1)
    centrality: EgoCentrality

    model_config = {"extra": "forbid"}


class AssociationNeighbor(BaseModel):
    handle: str = Field(min_length=1)
    edge_type: str  # content_similar | collaborated
    weight: float = Field(ge=0.0, le=1.0)
    method: str
    signals: list[str] = Field(min_length=1)

    model_config = {"extra": "forbid"}

    @field_validator("edge_type")
    @classmethod
    def valid_edge_type(cls, v: str) -> str:
        if v not in {"content_similar", "collaborated"}:
            raise ValueError(f"Invalid edge_type: {v}")
        return v


class CommunitySummary(BaseModel):
    community_id: int
    size: int = Field(ge=1)
    members: list[str]
    art9_risk: bool

    model_config = {"extra": "forbid"}


class AssociationGraph(BaseModel):
    handle: str = Field(min_length=1)
    method_version: str = "v2a"
    computed_at: str | None = None
    governance: dict[str, Any]
    cohort_size: int = Field(ge=2)
    community_method: str  # leiden | louvain
    ego: EgoView
    neighbors: list[AssociationNeighbor]
    communities_summary: list[CommunitySummary]
    warnings: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}

    @field_validator("method_version")
    @classmethod
    def valid_version(cls, v: str) -> str:
        if v != "v2a":
            raise ValueError(f"method_version must be v2a, got {v!r}")
        return v

    @field_validator("community_method")
    @classmethod
    def valid_community_method(cls, v: str) -> str:
        if v not in {"leiden", "louvain"}:
            raise ValueError(f"community_method must be leiden or louvain")
        return v
