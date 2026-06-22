"""Tests for app/release_schema.py — written BEFORE implementation (TDD RED phase)."""
import copy
import pytest

from app.release_schema import validate_release, ReleaseValidationError

# ---------------------------------------------------------------------------
# Shared fixture: a real, valid twentyday block
# ---------------------------------------------------------------------------
VALID = {
    "twentyday": {
        "tab": "1~20일 속보",
        "tabDay": "21일 발표 · 관세청",
        "granularity": "partial",
        "period": "2026년 6월 1~20일",
        "status": "순별 잠정 · 최신",
        "src": "관세청",
        "date": "2026.06.21",
        "totals": {
            "exports": 620.0,
            "exportsYoY": 60.4,
            "imports": 445.0,
            "importsYoY": 23.2,
            "balance": 175.0,
            "dailyAvg": None,
            "dailyAvgYoY": None,
        },
        "semiShare": {
            "value": 41.2,
            "label": "반도체 수출 비중",
            "note": "…",
        },
        "items": [
            {"name": "반도체", "value": 255.1, "yoy": 188.4, "star": True},
            {"name": "컴퓨터주변기기", "value": None, "yoy": 293.3},
        ],
        "regions": [],
        "note": "…",
    }
}


# ---------------------------------------------------------------------------
# 1. Valid twentyday passes and correct value is returned
# ---------------------------------------------------------------------------
def test_valid_twentyday_passes():
    result = validate_release(VALID)
    assert result["twentyday"]["totals"]["exports"] == 620.0


# ---------------------------------------------------------------------------
# 2. Negative trade balance is legal (deficit)
# ---------------------------------------------------------------------------
def test_negative_balance_allowed():
    data = copy.deepcopy(VALID)
    data["twentyday"]["totals"]["balance"] = -30.0
    result = validate_release(data)
    assert result["twentyday"]["totals"]["balance"] == -30.0


# ---------------------------------------------------------------------------
# 3. Negative exports must be rejected
# ---------------------------------------------------------------------------
def test_negative_export_rejected():
    data = copy.deepcopy(VALID)
    data["twentyday"]["totals"]["exports"] = -5
    with pytest.raises(ReleaseValidationError):
        validate_release(data)


# ---------------------------------------------------------------------------
# 4. YoY value that exceeds 1000 must be rejected
# ---------------------------------------------------------------------------
def test_insane_yoy_rejected():
    data = copy.deepcopy(VALID)
    data["twentyday"]["items"][0]["yoy"] = 99999
    with pytest.raises(ReleaseValidationError):
        validate_release(data)


# ---------------------------------------------------------------------------
# 5. Extra / injected fields must be rejected (prompt-injection guard)
# ---------------------------------------------------------------------------
def test_extra_field_rejected():
    data = copy.deepcopy(VALID)
    data["twentyday"]["injected"] = "x"
    with pytest.raises(ReleaseValidationError):
        validate_release(data)


# ---------------------------------------------------------------------------
# 6. Empty object (no block present) must be rejected
# ---------------------------------------------------------------------------
def test_empty_object_rejected():
    with pytest.raises(ReleaseValidationError):
        validate_release({})


# ---------------------------------------------------------------------------
# 7. Input dict must not be mutated after a successful validate
# ---------------------------------------------------------------------------
def test_input_not_mutated():
    original = copy.deepcopy(VALID)
    validate_release(VALID)
    assert VALID == original
