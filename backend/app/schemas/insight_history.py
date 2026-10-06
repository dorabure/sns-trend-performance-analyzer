"""Read-only snapshot contracts for the Phase 11 history UI."""
from datetime import date, datetime
from uuid import UUID

from app.schemas.insights import InsightResponse, StrictModel
from app.schemas.my_account import AnalysisPlatform


class InsightHistoryItem(StrictModel):
    insight_id: UUID
    project_id: UUID
    data_mode: str
    platform: AnalysisPlatform
    analysis_from: date
    analysis_to: date
    generated_at: datetime
    model_name: str | None
    prompt_version: str | None
    input_summary_hash: str
    is_legacy: bool


class InsightHistoryPage(StrictModel):
    items: list[InsightHistoryItem]
    next_cursor: str | None


class InsightHistoryDetail(InsightResponse):
    data_mode: str
    input_summary_hash: str
    is_legacy: bool


class InsightComparisonMetadata(StrictModel):
    has_previous: bool
    changed: bool | None
    input_changed: bool | None
    prompt_version_changed: bool | None
    model_changed: bool | None
    content_changed: bool | None
    evidence_changed: bool | None
    generated_at_delta_seconds: float | None


class InsightComparePreviousResponse(StrictModel):
    current: InsightHistoryDetail
    previous: InsightHistoryDetail | None
    comparison: InsightComparisonMetadata
