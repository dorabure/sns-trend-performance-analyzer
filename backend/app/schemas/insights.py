"""Ver1.1 section names are preserved; references supplement its examples."""
from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.schemas.my_account import AnalysisPlatform

Text = Annotated[str, Field(min_length=1, max_length=1600)]
Refs = Annotated[list[Annotated[str, Field(min_length=1, max_length=120)]], Field(min_length=1, max_length=8)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class References(StrictModel):
    market_trend: Refs
    own_analysis: Refs
    improvement_points: list[Refs] = Field(max_length=5)
    post_ideas: list[Refs] = Field(max_length=5)


class Sections(StrictModel):
    market_trend: Text
    own_analysis: Text
    improvement_points: list[Text] = Field(max_length=5)
    post_ideas: list[Text] = Field(max_length=5)


class AIInsightContent(Sections):
    summary: Text
    references: References
    cautions: list[Text] = Field(max_length=5)

    @model_validator(mode='after')
    def aligned_references(self):
        for name in ('improvement_points', 'post_ideas'):
            if len(getattr(self, name)) != len(getattr(self.references, name)):
                raise ValueError('Each proposal must have its own references')
        return self


class GenerateRequest(StrictModel):
    platform: AnalysisPlatform = AnalysisPlatform.ALL
    start: date = Field(alias='from')
    end: date = Field(alias='to')


class EvidenceItem(StrictModel):
    id: str
    label: str
    values: dict[str, JsonValue]


class Evidence(StrictModel):
    kpis: list[EvidenceItem]
    trends: list[EvidenceItem]
    competitors: list[EvidenceItem]
    opportunities: list[EvidenceItem]

    def ids(self):
        return {item.id for group in (self.kpis, self.trends, self.competitors, self.opportunities) for item in group}


class InsightResponse(StrictModel):
    insight_id: UUID
    project_id: UUID
    platform: AnalysisPlatform
    analysis_from: date
    analysis_to: date
    generated_at: datetime
    sections: Sections
    content: AIInsightContent | None
    evidence: Evidence
    input_summary: dict[str, JsonValue]
    model_name: str | None
    prompt_version: str | None
    legacy_evidence: dict[str, JsonValue] | None = None


class LatestResponse(StrictModel):
    insight: InsightResponse | None
    ai_generation_available: bool


class ErrorDetail(StrictModel):
    loc: list[str | int] | None = None
    type: str | None = None
    message: str | None = None


class ErrorBody(StrictModel):
    code: str
    message: str
    details: list[ErrorDetail]


class ErrorResponse(StrictModel):
    error: ErrorBody
