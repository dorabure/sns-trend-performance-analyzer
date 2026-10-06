"""Pure Decimal calculations shared by the Trend Engine and its unit tests."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP, localcontext

RAW_QUANTUM = Decimal("0.0001")
SCORE_QUANTUM = Decimal("0.01")
WEIGHTS = (Decimal("0.40"), Decimal("0.30"), Decimal("0.20"), Decimal("0.10"))


def calculate_engagement(likes: int | None, comments: int | None,
                         shares: int | None, saves: int | None) -> int | None:
    known = [value for value in (likes, comments, shares, saves) if value is not None]
    return sum(known) if known else None


@dataclass(frozen=True)
class WindowAggregate:
    post_count: int
    engagement_count: int
    known_engagement_post_count: int

    @property
    def avg_engagement(self) -> Decimal | None:
        if not self.known_engagement_post_count:
            return None
        with localcontext() as context:
            context.prec = 50
            return Decimal(self.engagement_count) / self.known_engagement_post_count


def calculate_engagement_growth(current: WindowAggregate, previous: WindowAggregate) -> Decimal | None:
    if not current.known_engagement_post_count or not previous.known_engagement_post_count:
        return None
    return calculate_growth_rate(current.engagement_count, previous.engagement_count)


def rounded(value: Decimal | None, quantum: Decimal) -> Decimal | None:
    if value is None:
        return None
    with localcontext() as context:
        context.prec = 50
        return value.quantize(quantum, rounding=ROUND_HALF_UP)


def calculate_growth_rate(current: int | Decimal | None,
                          previous: int | Decimal | None) -> Decimal | None:
    if current is None or previous is None or previous <= 0:
        return None
    with localcontext() as context:
        context.prec = 50
        return (Decimal(current) - Decimal(previous)) / Decimal(previous) * 100


def calculate_acceleration(current_growth: Decimal | None,
                           previous_growth: Decimal | None) -> Decimal | None:
    if current_growth is None or previous_growth is None:
        return None
    with localcontext() as context:
        context.prec = 50
        return current_growth - previous_growth


def normalize_scores(values: list[Decimal | None]) -> list[Decimal | None]:
    known = [value for value in values if value is not None]
    if not known:
        return [None] * len(values)
    low, high = min(known), max(known)
    with localcontext() as context:
        context.prec = 50
        return [None if value is None else Decimal("50.00") if low == high else
                rounded(max(Decimal(0), min(Decimal(100), (value - low) / (high - low) * 100)), SCORE_QUANTUM)
                for value in values]


def calculate_trend_score(post_growth: Decimal | None, engagement_growth: Decimal | None,
                          engagement_level: Decimal | None, acceleration: Decimal | None) -> Decimal | None:
    scores = (post_growth, engagement_growth, engagement_level, acceleration)
    if any(score is None for score in scores):
        return None
    with localcontext() as context:
        context.prec = 50
        return rounded(sum((score * weight for score, weight in zip(scores, WEIGHTS)), Decimal(0)), SCORE_QUANTUM)
