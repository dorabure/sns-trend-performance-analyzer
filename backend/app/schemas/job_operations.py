from datetime import time
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import Field, model_validator
from app.schemas.settings import Contract


class ScheduleFields(Contract):
    schedule_mode: Literal['INTERVAL', 'DAILY']
    interval_seconds: int | None = Field(default=None, ge=60, strict=True)
    daily_time: time | None = None
    timezone: str | None = Field(default=None, max_length=64)

    @model_validator(mode='after')
    def validate_schedule(self):
        if self.schedule_mode == 'INTERVAL':
            if self.interval_seconds is None or self.daily_time is not None:
                raise ValueError('Invalid interval fields')
        elif self.interval_seconds is not None or self.daily_time is None or self.timezone is None:
            raise ValueError('Invalid daily fields')
        if self.daily_time is not None and self.daily_time.tzinfo is not None:
            raise ValueError('Use a local daily time')
        if self.timezone is not None:
            try:
                ZoneInfo(self.timezone)
            except (ZoneInfoNotFoundError, ValueError):
                raise ValueError('Invalid IANA timezone') from None
        return self


class ScheduleCreate(ScheduleFields):
    provider_connection_id: UUID
    schedule_type: Literal['PROVIDER_SYNC_PIPELINE'] = 'PROVIDER_SYNC_PIPELINE'
    enabled: bool = Field(default=False, strict=True)


class SchedulePatch(Contract):
    schedule_mode: Literal['INTERVAL', 'DAILY'] | None = None
    interval_seconds: int | None = Field(default=None, ge=60, strict=True)
    daily_time: time | None = None
    timezone: str | None = Field(default=None, max_length=64)
