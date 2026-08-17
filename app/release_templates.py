"""release.json 블록별 LLM 출력 템플릿과 코드 상수 헤더.

- ``TEMPLATES[kind]``      : 모델에게 보여줄 목표 JSON 형태(값은 예시/null). release_schema와 1:1.
- ``HEADER_CONST[kind]``   : LLM 출력을 믿지 않고 코드가 덮어쓰는 고정 필드.
- ``prompt_template(kind)``: 프롬프트에 삽입할 JSON 문자열(래퍼 키 포함).

라이브 회귀(2026-08-17): 시스템 프롬프트에 출력 형태가 없어 모델이 임의 구조로 답해
스키마 검증(extra=forbid)에서 100% 실패했다. 이 모듈이 그 간극을 메운다.
"""

from __future__ import annotations

import json

_TOTALS = {
    "exports": 213.0, "exportsYoY": 45.3,
    "imports": 195.0, "importsYoY": 23.1,
    "balance": 18.0,
    "dailyAvg": 30.4, "dailyAvgYoY": 45.3,
}

_ITEM_EXAMPLES = [
    {"name": "반도체", "value": 99.5, "yoy": 155.4, "star": True},
    {"name": "석유제품", "value": 20.0, "yoy": 65.3},
    {"name": "승용차", "value": None, "yoy": -80.9},
]

TEMPLATES: dict[str, dict] = {
    "monthly": {
        "period": "2026년 7월 (1~31일)",
        "status": "월간 잠정",
        "date": "2026.08.01",
        "totals": _TOTALS,
        "highlight": {"ytd": 1680.1, "note": "1~7월 누적 흑자 … 한 문장 요약"},
        "groups": [
            {"name": "IT·반도체", "items": [
                {"name": "반도체", "value": 410.1, "yoy": 178.8, "star": True},
                {"name": "컴퓨터(SSD)", "value": 47.9, "yoy": 404.0},
                {"name": "디스플레이", "value": None, "yoy": 2.4},
                {"name": "무선통신기기", "value": 18.1, "yoy": 51.0},
            ]},
            {"name": "모빌리티", "items": [
                {"name": "자동차", "value": 62.4, "yoy": 7.0},
                {"name": "선박", "value": 32.9, "yoy": 46.9},
                {"name": "자동차부품", "value": 19.5, "yoy": 2.2},
                {"name": "이차전지", "value": 6.8, "yoy": 17.2},
            ]},
            {"name": "에너지·화학", "items": [
                {"name": "석유제품", "value": 56.8, "yoy": 34.1},
                {"name": "석유화학", "value": 41.8, "yoy": 10.3},
            ]},
            {"name": "소재·기계", "items": [
                {"name": "일반기계", "value": 45.3, "yoy": 5.9},
                {"name": "철강", "value": 23.6, "yoy": 4.4},
                {"name": "비철금속", "value": 17.3, "yoy": 23.9},
            ]},
            {"name": "소비재·바이오", "items": [
                {"name": "바이오헬스", "value": 15.7, "yoy": 30.4},
                {"name": "화장품", "value": 13.5, "yoy": 37.8},
                {"name": "농수산식품", "value": 10.9, "yoy": 2.3},
                {"name": "가전", "value": 6.1, "yoy": -4.1},
            ]},
        ],
        "regions": [
            {"name": "중국", "value": 216.8, "yoy": 96.2},
            {"name": "미국", "value": 174.3, "yoy": 68.7},
            {"name": "아세안", "value": 188.0, "yoy": 73.7},
            {"name": "EU", "value": 93.8, "yoy": 55.7},
            {"name": "중동", "value": 18.3, "yoy": 24.7},
        ],
        "imports": {
            "energy": 144.8, "energyYoY": 50.1,
            "crude": 93.0, "crudeYoY": 54.2,
            "nonEnergy": 540.8, "nonEnergyYoY": 21.4,
        },
    },
    "tenday": {
        "period": "2026년 8월 1~10일",
        "status": "순별 잠정",
        "date": "2026.08.11",
        "totals": _TOTALS,
        "workdays": {"now": 7.0, "prev": 7.0},
        "items": _ITEM_EXAMPLES,
        "regions": [],
        "note": "발표일·조업일수·반도체 비중·주요 국가 증감률을 담은 2~3문장 해설",
    },
    "twentyday": {
        "period": "2026년 7월 1~20일",
        "status": "순별 잠정",
        "date": "2026.07.21",
        "totals": _TOTALS,
        "semiShare": {
            "value": 40.3,
            "label": "반도체 수출 비중",
            "note": "전체 수출의 40.3% (전년동기비 +18.4%p). 반도체 221.1억 달러(+180.6%).",
        },
        "items": _ITEM_EXAMPLES,
        "regions": [],
        "note": "발표일·조업일수·주요 국가 증감률을 담은 2~3문장 해설",
    },
}

HEADER_CONST: dict[str, dict[str, str]] = {
    "monthly": {
        "tab": "월간 동향", "tabDay": "1일 발표 · 산업부",
        "granularity": "full", "src": "산업통상부", "status": "월간 잠정",
    },
    "tenday": {
        "tab": "1~10일 속보", "tabDay": "11일 발표 · 관세청",
        "granularity": "partial", "src": "관세청", "status": "순별 잠정",
    },
    "twentyday": {
        "tab": "1~20일 속보", "tabDay": "21일 발표 · 관세청",
        "granularity": "partial", "src": "관세청", "status": "순별 잠정",
    },
}


def prompt_template(kind: str) -> str:
    """모델에게 보여줄 목표 JSON(래퍼 키 포함) 문자열을 반환한다."""
    return json.dumps({kind: TEMPLATES[kind]}, ensure_ascii=False, indent=1)


def overlay_header(kind: str, block: dict) -> dict:
    """LLM 블록 위에 코드 상수 헤더를 덮어쓴 새 dict를 반환한다(입력 불변)."""
    return {**block, **HEADER_CONST[kind]}
