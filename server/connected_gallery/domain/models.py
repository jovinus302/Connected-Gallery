from __future__ import annotations
from datetime import datetime
from typing import Literal
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    time_source: Literal["exif", "media_store", "modified", "unknown"] = "unknown"
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    rotation: int = 0
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

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
    photo_id: str
    reason: str


class ExplorationResult(Model):
    label: str
    items: list[ResultItem]
    complete: bool = True


class Space(Model):
    id: str = Field(default_factory=new_id)
    name: str
    meaning: str
    items: list[ResultItem]


class SpaceProposal(Model):
    spaces: list[Space]


class RunRequest(Model):
    role: Literal["analyst", "explorer", "organizer"]
    photo_ids: list[str] = Field(default_factory=list, max_length=1000)
    explore: ExploreInput | None = None
    idempotency_key: str = Field(default_factory=new_id, max_length=160)

    @model_validator(mode="after")
    def required(self):
        if self.role == "explorer" and self.explore is None:
            raise ValueError("explore is required")
        if self.role == "analyst" and len(self.photo_ids) != 1:
            raise ValueError("One durable analysis run per photo")
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
