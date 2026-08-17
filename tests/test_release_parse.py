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


# ---------------------------------------------------------------------------
# 라이브 회귀(2026-08-17): 프롬프트에 출력 형태가 없어 모델이 임의 구조로 답함
# ---------------------------------------------------------------------------
class RecordingClient(FakeClient):
    def complete(self, system: str, user: str) -> str:
        self.system, self.user = system, user
        return self.payload


@pytest.mark.parametrize("kind,required", [
    ("monthly", ["totals", "highlight", "groups", "regions", "imports"]),
    ("tenday", ["totals", "workdays", "items", "regions", "note"]),
    ("twentyday", ["totals", "semiShare", "items", "regions", "note"]),
])
def test_prompt_includes_kind_json_template(kind, required):
    """유저 프롬프트에 해당 kind의 JSON 템플릿(래퍼 키 + 필수 필드)이 들어가야 한다."""
    from app.release_parse import parse_release_text
    from tests.test_release_parse import VALID  # noqa: F401 (twentyday만 유효 페이로드)

    payload_block = _valid_block_for(kind)
    client = RecordingClient(json.dumps({kind: payload_block}))
    parse_release_text("본문", kind, client=client)

    assert f'"{kind}"' in client.user, "래퍼 키가 프롬프트에 없음"
    for key in required + ["exports", "exportsYoY", "period", "date"]:
        assert f'"{key}"' in client.user, f"템플릿에 {key} 없음"


def test_header_constants_are_overlaid_by_code():
    """tab/tabDay/granularity/src 는 LLM 출력과 무관하게 코드 상수로 채워진다."""
    from app.release_parse import parse_release_text

    llm_block = {k: v for k, v in VALID.items() if k not in ("tab", "tabDay", "granularity", "src")}
    llm_block["status"] = "아무거나"
    client = FakeClient(json.dumps({"twentyday": llm_block}))

    out = parse_release_text("본문", "twentyday", client=client)["twentyday"]

    assert out["tab"] == "1~20일 속보"
    assert out["tabDay"] == "21일 발표 · 관세청"
    assert out["granularity"] == "partial"
    assert out["src"] == "관세청"
    assert out["status"] == "순별 잠정"


def _valid_block_for(kind: str) -> dict:
    header = {"period": "2026년 8월", "date": "2026.08.11", "tab": "", "tabDay": "", "granularity": "", "status": "", "src": ""}
    totals = {"exports": 1.0, "exportsYoY": 1.0, "imports": 1.0, "importsYoY": 1.0, "balance": 0.0, "dailyAvg": None, "dailyAvgYoY": None}
    if kind == "monthly":
        return {**header, "totals": totals, "highlight": {"ytd": 1.0, "note": "n"}, "groups": [], "regions": [],
                "imports": {"energy": 1, "crude": 1, "nonEnergy": 1, "energyYoY": 1, "crudeYoY": 1, "nonEnergyYoY": 1}}
    if kind == "tenday":
        return {**header, "totals": totals, "workdays": {"now": 7.0, "prev": 7.0}, "items": [], "regions": [], "note": "n"}
    return {**header, "totals": totals, "semiShare": {"value": 1.0, "label": "l", "note": "n"}, "items": [], "regions": [], "note": "n"}


@pytest.mark.parametrize("kind", ["monthly", "tenday", "twentyday"])
def test_templates_validate_against_schema(kind):
    """프롬프트 템플릿 + 헤더 상수는 그대로 release_schema를 통과해야 한다(템플릿 드리프트 방지)."""
    from app.release_schema import validate_release
    from app.release_templates import TEMPLATES, overlay_header

    validate_release({kind: overlay_header(kind, TEMPLATES[kind])})


def test_tenday_all_null_workdays_becomes_none():
    """EIEC 요약에 조업일수가 없어 LLM이 workdays 를 전부 null 로 내면 블록의 workdays 는 None 이어야 한다(검증 실패 금지)."""
    from app.release_parse import parse_release_text

    block = {**_valid_block_for("tenday"), "workdays": {"now": None, "prev": None}}
    out = parse_release_text("본문", "tenday", client=FakeClient(json.dumps({"tenday": block})))["tenday"]

    assert out["workdays"] is None
    assert out["totals"]["exports"] == 1.0


def test_twentyday_all_null_semishare_becomes_none():
    """semiShare.value 가 null 이면 semiShare 는 None 으로 정규화된다."""
    from app.release_parse import parse_release_text

    block = {**_valid_block_for("twentyday"), "semiShare": {"value": None, "label": None, "note": None}}
    out = parse_release_text("본문", "twentyday", client=FakeClient(json.dumps({"twentyday": block})))["twentyday"]

    assert out["semiShare"] is None
