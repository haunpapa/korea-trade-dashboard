"""Calendar constraints shared by release selection and parsed-data validation."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Final, Literal

from typing_extensions import assert_never

ReleaseKind = Literal["monthly", "tenday", "twentyday"]
_MONTH: Final = re.compile(r"^(\d{4})년\s*(\d{1,2})월")
_RANGE: Final = re.compile(r"1일?[~∼〜](?:\d{1,2}월)?(\d{1,2})일")


def period_month(text: str) -> tuple[int, int] | None:
    """Read the explicit year/month; never infer a missing year from the clock."""
    match = _MONTH.match(text.strip())
    if match:
        return int(match[1]), int(match[2])
    return None


@dataclass(frozen=True, slots=True)
class ReleaseTarget:
    kind: ReleaseKind
    date: dt.date

    @property
    def month(self) -> dt.date:
        first = self.date.replace(day=1)
        return first - dt.timedelta(days=1) if self.kind == "monthly" else first

    def matches_period(self, text: str) -> bool:
        if period_month(text) != (self.month.year, self.month.month):
            return False
        span = _RANGE.search(re.sub(r"\s+", "", text))
        match self.kind:
            case "monthly":
                return (span is None and re.search(r"\d+일", text) is None) or (
                    span is not None and int(span[1]) == self.month.day
                )
            case "tenday":
                return span is not None and span[1] == "10"
            case "twentyday":
                return span is not None and span[1] == "20"
            case unreachable:
                assert_never(unreachable)

    def matches_publication_date(self, text: str) -> bool:
        try:
            published = dt.date.fromisoformat(text.replace(".", "-"))
        except ValueError:
            return False
        match self.kind:
            case "monthly":
                earliest = self.date.replace(day=1)
            case "tenday":
                earliest = self.date.replace(day=11)
            case "twentyday":
                earliest = self.date.replace(day=21)
            case unreachable:
                assert_never(unreachable)
        return earliest <= published <= self.date
