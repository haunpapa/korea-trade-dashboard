"""release_schema.py — Pydantic v2 schema for Korean trade dashboard release objects.

Validates a "release" dict holding up to three headline blocks:
  monthly, tenday, twentyday.

Numbers: value = 억 달러 (USD 100M), yoy = YoY % change.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------

class ReleaseValidationError(Exception):
    """Raised when a release dict fails pydantic validation."""


# ---------------------------------------------------------------------------
# Shared constraints
# ---------------------------------------------------------------------------

_NON_NEG = Field(default=None, ge=0)
_YOY = Field(default=None, ge=-100, le=1000)


# ---------------------------------------------------------------------------
# Shared header (all blocks carry these seven str fields)
# ---------------------------------------------------------------------------

class _Header(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tab: str
    tabDay: str
    granularity: str
    period: str
    status: str
    src: str
    date: str


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------

class Totals(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exports: Optional[float] = Field(default=None, ge=0)
    exportsYoY: Optional[float] = Field(default=None, ge=-100, le=1000)
    imports: Optional[float] = Field(default=None, ge=0)
    importsYoY: Optional[float] = Field(default=None, ge=-100, le=1000)
    # balance CAN be negative (trade deficit) — no lower bound
    balance: Optional[float] = None
    dailyAvg: Optional[float] = Field(default=None, ge=0)
    dailyAvgYoY: Optional[float] = Field(default=None, ge=-100, le=1000)


class Item(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    value: Optional[float] = Field(default=None, ge=0)
    yoy: Optional[float] = Field(default=None, ge=-100, le=1000)
    star: Optional[bool] = None
    est: Optional[bool] = None
    valuePrefix: Optional[str] = None
    tag: Optional[str] = None


class Group(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    items: list[Item]


class Region(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    value: Optional[float] = Field(default=None, ge=0)
    yoy: Optional[float] = Field(default=None, ge=-100, le=1000)


class Highlight(BaseModel):
    """Monthly-only highlight block."""
    model_config = ConfigDict(extra="forbid")

    ytd: float
    note: str


class ImportsBreakdown(BaseModel):
    """Monthly-only imports breakdown."""
    model_config = ConfigDict(extra="forbid")

    energy: float
    crude: float
    nonEnergy: float
    energyYoY: float
    crudeYoY: float
    nonEnergyYoY: float


class Workdays(BaseModel):
    """Tenday-only workday comparison."""
    model_config = ConfigDict(extra="forbid")

    now: float
    prev: float


class SemiShare(BaseModel):
    """Twentyday-only semiconductor share block."""
    model_config = ConfigDict(extra="forbid")

    value: float
    label: str
    note: str


# ---------------------------------------------------------------------------
# Block models (header fields inlined via inheritance + extra fields)
# ---------------------------------------------------------------------------

class Monthly(_Header):
    totals: Totals
    highlight: Highlight
    groups: list[Group]
    regions: list[Region]
    imports: ImportsBreakdown


class Tenday(_Header):
    totals: Totals
    workdays: Optional[Workdays] = None  # 순별 요약에 조업일수가 없을 수 있음
    items: list[Item]
    regions: list[Region]
    note: str


class Twentyday(_Header):
    totals: Totals
    semiShare: Optional[SemiShare] = None  # 요약에 반도체 비중이 없을 수 있음
    items: list[Item]
    regions: list[Region]
    note: str


# ---------------------------------------------------------------------------
# Top-level Release model
# ---------------------------------------------------------------------------

class Release(BaseModel):
    model_config = ConfigDict(extra="forbid")

    monthly: Optional[Monthly] = None
    tenday: Optional[Tenday] = None
    twentyday: Optional[Twentyday] = None

    @model_validator(mode="after")
    def at_least_one_block(self) -> "Release":
        if self.monthly is None and self.tenday is None and self.twentyday is None:
            raise ValueError("release must contain at least one block: monthly, tenday, or twentyday")
        return self


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_release(obj: dict) -> dict:
    """Validate a release dict and return its serialised form.

    Args:
        obj: Raw release dict. Never mutated.

    Returns:
        Serialised dict (model_dump with None values included).

    Raises:
        ReleaseValidationError: If validation fails for any reason.
    """
    try:
        model = Release.model_validate(obj)
    except Exception as exc:
        raise ReleaseValidationError(str(exc)) from exc

    return model.model_dump(exclude_none=False)
