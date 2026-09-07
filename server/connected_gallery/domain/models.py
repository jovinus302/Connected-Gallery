from __future__ import annotations
from datetime import datetime
from typing import Literal
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator, model_serializer
from connected_gallery.domain.empty_evidence import EMPTY_EVIDENCE_SPEC, EMPTY_EVIDENCE_POLICY, MAX_EMPTY_CANDIDATES


def new_id() -> str:
    return str(uuid4())


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Box(Model):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def inside(self):
        if self.x + self.width > 1.00001 or self.y + self.height > 1.00001:
            raise ValueError("Region extends outside oriented image")
        return self


class PhotoAsset(Model):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,128}$")
    device_id: str
    local_uri: str = ""
    version: str
    captured_at: datetime | None = None
    time_source: Literal["exif", "media_store", "modified", "unknown", "demo_fixture"] = "unknown"
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    rotation: int = 0
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def fixture_time(self):
        if self.time_source == "demo_fixture" and (
            self.device_id != "synthetic-demo" or self.captured_at is None
            or self.captured_at.tzinfo is None
        ):
            raise ValueError("Demo fixture time requires a synthetic-demo asset and an aware timestamp")
        return self

    @property
    def year(self):
        return (
            self.captured_at.year
            if self.captured_at and self.time_source in ("exif", "media_store")
            else None
        )


class Region(Model):
    id: str = Field(default_factory=new_id)
    photo_id: str
    box: Box
    kind: Literal["person", "object", "text", "place"]
    label: str
    evidence: str


class PhotoAnalysis(Model):
    photo_id: str
    description: str
    ocr: str = ""
    uncertainty: str = ""
    coverage: list[str] = Field(default_factory=list)
    regions: list[Region] = Field(default_factory=list)


class PhotoAnalysisSubmission(PhotoAnalysis):
    """New analyst submissions are bounded; historical analyses stay readable."""

    regions: list[Region] = Field(default_factory=list, max_length=3)


class SemanticAnchor(Model):
    photo_id: str
    region_id: str | None = None
    box: Box | None = None
    label: str = "선택한 부분"
    kind: Literal["person", "object", "text", "place"] = "object"


class ExploreInput(Model):
    anchor: SemanticAnchor
    direction: Literal["related", "same_moment"] = "related"
    year: int | None = Field(default=None, ge=1800, le=2200)
    request_revision: int = Field(default=0, ge=0)


class ResultItem(Model):
    photo_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,128}$")
    reason: str


class ResultGroup(Model):
    id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=120)
    reason: str = Field(min_length=1, max_length=600)
    photo_ids: list[str] = Field(min_length=1, max_length=1000)

    @field_validator("id", "title", "reason")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("Group fields must not be blank")
        return value

    @field_validator("photo_ids")
    @classmethod
    def valid_ids(cls, values):
        if any(not value.strip() for value in values):
            raise ValueError("Group photo IDs must not be blank")
        return values


class EmptyCandidateEvidence(Model):
    photo_id: str
    verdict: Literal["unrelated"]
    reason: str = Field(min_length=1, max_length=500)


class EmptyEvidence(Model):
    spec: Literal[EMPTY_EVIDENCE_SPEC]
    policy: Literal[EMPTY_EVIDENCE_POLICY]
    reviewed: Literal[True]
    anchor_supported: Literal[True]
    scope_sufficient: Literal[True]
    selected_meaning: str = Field(min_length=1, max_length=500)
    scope_reason: str = Field(min_length=1, max_length=500)
    anchor: SemanticAnchor
    direction: Literal["related", "same_moment"]
    year: int | None
    gallery_revision: int = Field(ge=0)
    cache_model: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    inspection_mode: Literal["source_crop_and_full_candidates"]
    eligible_photo_ids: list[str] = Field(max_length=MAX_EMPTY_CANDIDATES)
    inspected_photo_ids: list[str] = Field(min_length=1, max_length=MAX_EMPTY_CANDIDATES + 1)
    photo_versions: dict[str, str]
    decisions: list[EmptyCandidateEvidence] = Field(max_length=MAX_EMPTY_CANDIDATES)

    @model_validator(mode="after")
    def full_negative_coverage(self):
        ids = self.eligible_photo_ids
        inspected = self.inspected_photo_ids
        reviewed = [decision.photo_id for decision in self.decisions]
        if (len(ids) != len(set(ids)) or len(inspected) != len(set(inspected)) or self.anchor.photo_id in ids
                or set(inspected) != set(ids) | {self.anchor.photo_id}
                or set(self.photo_versions) != set(inspected) or len(reviewed) != len(ids) or set(reviewed) != set(ids)):
            raise ValueError("Empty evidence must inspect and independently reject every eligible photo exactly once")
        if not self.selected_meaning.strip() or not self.scope_reason.strip() or any(not d.reason.strip() for d in self.decisions):
            raise ValueError("Empty evidence requires meaningful review reasons")
        return self


class ExplorationResult(Model):
    label: str
    items: list[ResultItem]
    complete: bool = True
    groups: list[ResultGroup] = Field(default_factory=list, max_length=8)
    grouping_status: Literal["legacy", "ready", "failed"] = "legacy"
    empty_evidence: EmptyEvidence | None = None

    @model_serializer(mode="wrap")
    def omit_absent_empty_evidence(self, handler):
        result = handler(self)
        if self.empty_evidence is None:
            result.pop("empty_evidence", None)
        return result

    @model_validator(mode="after")
    def valid_groups(self):
        if self.empty_evidence is not None and (self.items or not self.complete):
            raise ValueError("Negative evidence belongs only to a completed empty result")
        if self.grouping_status != "ready":
            if self.groups:
                raise ValueError("Only independently verified ready results may contain groups")
            return self
        if not self.items and self.empty_evidence is None:
            raise ValueError("A ready empty result requires independent negative evidence")
        ids = [item.photo_id for item in self.items]
        members = [pid for group in self.groups for pid in group.photo_ids]
        group_ids = [group.id for group in self.groups]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate result IDs")
        if len(group_ids) != len(set(group_ids)):
            raise ValueError("Duplicate group IDs")
        if len(members) != len(set(members)) or set(members) != set(ids):
            raise ValueError("Groups must partition every accepted result exactly once")
        return self


class Space(Model):
    id: str = Field(default_factory=new_id)
    name: str
    meaning: str
    items: list[ResultItem]


class SpaceProposal(Model):
    spaces: list[Space]


class RunRequest(Model):
    role: Literal["analyst", "explorer", "organizer", "context"]
    photo_ids: list[str] = Field(default_factory=list, max_length=1000)
    explore: ExploreInput | None = None
    idempotency_key: str = Field(default_factory=new_id, max_length=160)

    @model_validator(mode="after")
    def required(self):
        if self.role == "explorer" and self.explore is None:
            raise ValueError("explore is required")
        if self.role in ("analyst", "context") and len(self.photo_ids) != 1:
            raise ValueError("One durable analysis run per photo")
        if self.role == "context" and self.explore is not None:
            raise ValueError("Photo context is independent of a selected Connect region")
        return self


class SyncRequest(Model):
    assets: list[PhotoAsset] = Field(default_factory=list, max_length=1000)
    deleted_ids: list[str] = Field(default_factory=list, max_length=1000)


class Feedback(Model):
    event_id: str = Field(default_factory=new_id)
    kind: Literal["space_include", "space_exclude", "person_name", "metric"]
    space_id: str | None = None
    photo_id: str | None = None
    region_id: str | None = None
    value: str = ""
    session_id: str = ""
