from datetime import date
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field

from app.dto.normalized import Platform


class Classification(StrEnum):
    OPPORTUNITY = 'OPPORTUNITY'
    BALANCED = 'BALANCED'
    HIGH_COVERAGE = 'HIGH_COVERAGE'
    LOW_PRIORITY = 'LOW_PRIORITY'


class GapItem(BaseModel):
    topic_id: UUID
    topic_name: str
    platform: Platform
    trend_date: date | None
    trend_score: float | None
    own_posts: int
    own_total_posts: int
    own_post_ratio: float | None
    competitor_posts: int
    competitor_total_posts: int
    competitor_post_ratio: float | None
    gap_score: float | None
    classification: Classification | None


class GapAnalysis(BaseModel):
    timezone: str = 'UTC'
    start: date = Field(serialization_alias='from')
    end: date = Field(serialization_alias='to')
    score_window_days: int = 7
    trend_threshold: float
    own_ratio_threshold: float
    items: list[GapItem]
