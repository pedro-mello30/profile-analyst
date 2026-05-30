"""Shared Pydantic v2 models for the profile-analyst pipeline (spec §4, §8)."""
from __future__ import annotations

from typing import Any

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
