"""Tests for app/release_parse.py — written FIRST (TDD RED phase).

FakeClient injects controlled LLM responses so no network/SDK is needed.
"""
import json
import pytest

# ---------------------------------------------------------------------------
# Shared VALID fixture — a complete twentyday block
# ---------------------------------------------------------------------------
VALID = {
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


# ---------------------------------------------------------------------------
# Fake client — no network, no anthropic SDK
# ---------------------------------------------------------------------------
class FakeClient:
    def __init__(self, payload: str):
        self.payload = payload

    def complete(self, system: str, user: str) -> str:
        return self.payload


# ---------------------------------------------------------------------------
# 1. Happy path — wrapped twentyday dict
# ---------------------------------------------------------------------------
def test_parse_returns_validated_twentyday():
    from app.release_parse import parse_release_text

    payload = json.dumps({"twentyday": VALID})
    result = parse_release_text("dummy article", "twentyday", client=FakeClient(payload))
    assert result["twentyday"]["totals"]["exports"] == 620.0


# ---------------------------------------------------------------------------
# 2. Markdown code fences are stripped before JSON parsing
# ---------------------------------------------------------------------------
def test_parse_strips_code_fences():
    from app.release_parse import parse_release_text

    payload = "```json\n" + json.dumps({"twentyday": VALID}) + "\n```"
    result = parse_release_text("dummy article", "twentyday", client=FakeClient(payload))
    assert result["twentyday"]["totals"]["exports"] == 620.0


# ---------------------------------------------------------------------------
# 3. Bare block (no "twentyday" wrapper) is auto-wrapped
# ---------------------------------------------------------------------------
def test_parse_wraps_bare_block():
    from app.release_parse import parse_release_text

    payload = json.dumps(VALID)  # no "twentyday" key — bare block with "totals"
    result = parse_release_text("dummy article", "twentyday", client=FakeClient(payload))
    assert "twentyday" in result
    assert result["twentyday"]["totals"]["exports"] == 620.0


# ---------------------------------------------------------------------------
# 4. Unparseable JSON raises ReleaseParseError
# ---------------------------------------------------------------------------
def test_parse_invalid_json_raises():
    from app.release_parse import parse_release_text, ReleaseParseError

    result = pytest.raises(ReleaseParseError, parse_release_text,
                           "article", "twentyday", client=FakeClient("not json at all"))
    assert result is not None


# ---------------------------------------------------------------------------
# 5. Schema violation (negative exports) raises ReleaseParseError
# ---------------------------------------------------------------------------
def test_parse_schema_violation_raises():
    from app.release_parse import parse_release_text, ReleaseParseError

    bad = {**VALID, "totals": {**VALID["totals"], "exports": -1}}
    payload = json.dumps({"twentyday": bad})
    with pytest.raises(ReleaseParseError):
        parse_release_text("article", "twentyday", client=FakeClient(payload))


# ---------------------------------------------------------------------------
# 6. Unknown kind raises ReleaseParseError
# ---------------------------------------------------------------------------
def test_bad_kind_raises():
    from app.release_parse import parse_release_text, ReleaseParseError

    with pytest.raises(ReleaseParseError):
        parse_release_text("x", "weekly", client=FakeClient("{}"))


# ---------------------------------------------------------------------------
# 7. SYSTEM_PROMPT contains the injection-guard phrase
# ---------------------------------------------------------------------------
def test_system_prompt_has_injection_guard():
    from app.release_parse import SYSTEM_PROMPT

    assert "신뢰할 수 없는" in SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# 8. Module imports fine even when anthropic SDK is not installed
# ---------------------------------------------------------------------------
def test_module_imports_without_anthropic():
    # If the lazy-import is broken, collection of this test would already fail.
    import app.release_parse  # noqa: F401
