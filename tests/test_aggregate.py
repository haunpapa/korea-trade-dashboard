"""집계 순수 함수 단위 테스트."""

import pytest

from app.aggregate import deduct_overlaps, month_seq, prev_year, region_of, yoy

pytestmark = pytest.mark.unit


class TestMonthSeq:
    def test_basic(self):
        assert month_seq("202601", 3) == ["202511", "202512", "202601"]

    def test_year_boundary(self):
        assert month_seq("202512", 2) == ["202511", "202512"]

    def test_single(self):
        assert month_seq("202605", 1) == ["202605"]


class TestYoY:
    def test_increase(self):
        assert yoy(110, 100) == 10.0

    def test_decrease(self):
        assert yoy(90, 100) == -10.0

    def test_zero_prev_returns_none(self):
        assert yoy(100, 0) is None

    def test_none_prev_returns_none(self):
        assert yoy(100, None) is None


def test_prev_year():
    assert prev_year("202605") == "202505"


class TestRegionOf:
    def test_exact(self):
        assert region_of("중국") == "중국"

    def test_indonesia_goes_to_asean_not_india(self):
        # '인도네시아'에 '인도'가 부분일치하지만 완전일치(아세안)가 우선
        assert region_of("인도네시아") == "아세안"

    def test_india(self):
        assert region_of("인도") == "인도"

    def test_partial_match(self):
        assert region_of("말레이시아") == "아세안"

    def test_mideast(self):
        assert region_of("튀르키예") == "중동"

    def test_unmapped(self):
        assert region_of("브라질") is None


class TestDeductOverlaps:
    def test_machinery_deducts_nested_codes(self):
        # 일반기계(84)에서 컴퓨터(8471)·가전(8415/8418/8450) 중복 차감
        code_val = {"84": 100.0, "8471": 10.0, "8415": 5.0, "8418": 5.0, "8450": 5.0}
        values = deduct_overlaps(code_val)
        assert values["일반기계"] == 75.0
        assert values["컴퓨터(SSD)"] == 10.0

    def test_no_overlap_unchanged(self):
        code_val = {"8541": 200.0, "8542": 100.0}
        values = deduct_overlaps(code_val)
        assert values["반도체"] == 300.0

    def test_missing_codes_are_zero(self):
        values = deduct_overlaps({})
        assert values["반도체"] == 0.0
