"""Photo-detail context is an internal prepared view, never a saved Space."""
from datetime import timedelta, timezone
from typing import Literal
from pydantic import Field, field_validator, model_validator
from connected_gallery.domain.models import Model, ResultGroup

CONTEXT_SPEC = 9
CONTEXT_POLICY = "photo-context-v9-integrated-grounded-review"
CONTEXT_WORDING_MODEL = "gpt-5.4-mini"
MAX_CONTEXT_IMAGES = 24
MAX_CATALOG_PHOTOS = 100


class ReviewedContextMember(Model):
    group_id: str
    photo_id: str


class ContextEvidence(Model):
    gallery_revision: int = Field(ge=0)
    source_version: str
    inspected_photo_ids: list[str] = Field(min_length=1, max_length=MAX_CONTEXT_IMAGES + 1)
    photo_versions: dict[str, str]
    reviewed_members: list[ReviewedContextMember] = Field(max_length=MAX_CONTEXT_IMAGES)
    summary_reviewed: Literal[True]
    planned_photo_ids: list[str] = Field(max_length=MAX_CONTEXT_IMAGES)
    wording_review_model: str
    wording_reviewed: Literal[True]
    wording_checked_paths: list[str] = Field(min_length=1, max_length=17)


class ContextGroup(ResultGroup):
    title: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=1, max_length=240)


class PhotoContext(Model):
    summary: str = Field(min_length=1, max_length=250)
    groups: list[ContextGroup] = Field(default_factory=list, max_length=8)
    complete: bool

    @field_validator("summary")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Context summary must not be blank")
        return value

    @model_validator(mode="after")
    def membership(self):
        if len({g.id for g in self.groups}) != len(self.groups):
            raise ValueError("Duplicate context group IDs")
        members = [pid for g in self.groups for pid in g.photo_ids]
        if len(members) > MAX_CONTEXT_IMAGES:
            raise ValueError("Context membership image budget exceeded")
        for group in self.groups:
            if len(group.photo_ids) != len(set(group.photo_ids)):
                raise ValueError("Duplicate photo within context group")
        return self


def context_wording_fields(context):
    """Stable checked paths are generated from final fields, never supplied by the model."""
    value = context.model_dump(mode="json") if isinstance(context, PhotoContext) else context
    fields = [{"path": "/summary", "text": value["summary"]}]
    for index, group in enumerate(value["groups"]):
        for field in ("title", "reason"):
            fields.append({"path": f"/groups/{index}/{field}", "text": group[field],
                           "member_photo_ids": group["photo_ids"]})
    return fields


def capture_metadata(asset):
    """Modern demo calendar policy: explicit Asia/Seoul UTC+09; unknown dates are absent."""
    if (asset.captured_at is None or asset.captured_at.tzinfo is None
            or asset.time_source not in ("exif", "media_store", "demo_fixture")):
        return None
    return {"value": asset.captured_at.isoformat(), "source": asset.time_source,
            "timezone": "Asia/Seoul",
            "date": asset.captured_at.astimezone(timezone(timedelta(hours=9))).date().isoformat()}
