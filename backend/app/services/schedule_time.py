"""UTC boundaries; missed interval runs collapse to one execution."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def next_run(schedule, now, previous=None):
    now = now.astimezone(timezone.utc)
    if schedule.schedule_mode == 'INTERVAL':
        seconds = schedule.interval_seconds
        if previous is None:
            return now + timedelta(seconds=seconds)
        missed = max(1, int((now - previous).total_seconds() // seconds) + 1)
        return previous + timedelta(seconds=seconds * missed)
    zone = ZoneInfo(schedule.timezone)
    day = now.astimezone(zone).date()
    for offset in range(3):
        wall = datetime.combine(day + timedelta(days=offset), schedule.daily_time)
        # First fold only: one run per local date. Gaps advance to first valid minute.
        for minute in range(181):
            local = wall + timedelta(minutes=minute)
            candidate = local.replace(tzinfo=zone, fold=0).astimezone(timezone.utc)
            if candidate.astimezone(zone).replace(tzinfo=None) == local:
                if candidate > now:
                    return candidate
                break
    raise ValueError('Daily boundary unavailable')
