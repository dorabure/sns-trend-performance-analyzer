"""Explicit settings contracts. Unknown/immutable fields are rejected."""
from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.dto.normalized import Platform
from app.providers.base import CsvDatasetType

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
TermText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]


class Role(StrEnum):
    OWN = "OWN"
    COMPETITOR = "COMPETITOR"


class DataMode(StrEnum):
    DEMO = "DEMO"
    LIVE = "LIVE"


class TermType(StrEnum):
    KEYWORD = "KEYWORD"
    HASHTAG = "HASHTAG"


class ImportStatus(StrEnum):
    PROCESSING = "PROCESSING"
    SUCCESS = "SUCCESS"
    PARTIAL_ERROR = "PARTIAL_ERROR"
    FAILED = "FAILED"


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class Patch(Contract):
    @model_validator(mode="after")
    def reject_null_required(self):
        nullable = {"description", "display_name", "platform_account_id", "profile_url"}
        if any(getattr(self, key) is None for key in self.model_fields_set - nullable):
            raise ValueError("Required fields cannot be null")
        return self


class Platforms(Contract):
    platforms: list[Platform] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_platforms(self):
        if len(set(self.platforms)) != len(self.platforms):
            raise ValueError("Platforms must be unique")
        return self


class ProjectCreate(Platforms):
    data_mode: DataMode = DataMode.DEMO
    name: Name
    description: str | None = None


class ProjectPatch(Patch):
    name: Name | None = None
    description: str | None = None
    is_active: bool | None = None


class ProjectResponse(Contract):
    data_mode: DataMode
    project_id: UUID
    name: str
    description: str | None
    is_active: bool
    platforms: list[Platform]
    created_at: datetime
    updated_at: datetime


class AccountCreate(Contract):
    platform: Platform
    account_name: Name
    account_role: Role
    display_name: str | None = Field(default=None, max_length=200)
    platform_account_id: str | None = Field(default=None, max_length=255)
    profile_url: str | None = None


class AccountPatch(Patch):
    account_name: Name | None = None
    display_name: str | None = Field(default=None, max_length=200)
    platform_account_id: str | None = Field(default=None, max_length=255)
    profile_url: str | None = None
    is_active: bool | None = None


class AccountResponse(AccountCreate):
    account_id: UUID
    project_id: UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime


class TermCreate(Contract):
    term: TermText
    term_type: TermType


class TermPatch(Patch):
    term: TermText | None = None
    term_type: TermType | None = None
    is_active: bool | None = None


class TermResponse(TermCreate):
    term_id: UUID
    normalized_term: str
    is_active: bool


class TopicCreate(Contract):
    topic_name: Name
    description: str | None = None
    terms: list[TermCreate] = Field(default_factory=list)


class TopicPatch(Patch):
    topic_name: Name | None = None
    description: str | None = None
    is_active: bool | None = None


class TopicResponse(Contract):
    topic_id: UUID
    project_id: UUID
    topic_name: str
    description: str | None
    is_active: bool
    terms: list[TermResponse]


class ImportErrorDetail(Contract):
    row: int | None
    field: str
    code: str
    message: str


class HistoryResponse(Contract):
    import_id: UUID
    import_type: CsvDatasetType
    filename: str
    total_count: int
    success_count: int
    error_count: int
    status: ImportStatus
    imported_at: datetime


class HistoryDetail(HistoryResponse):
    error_detail: list[ImportErrorDetail]


class HistoryPage(Contract):
    items: list[HistoryResponse]
    total: int
    page: int
    page_size: int
    limit: int
    offset: int
