"""C1 HS 후보 검색 단위 테스트. AWS와 Bedrock을 부르지 않는다. 담당: 검증."""
import pytest

from tools.hs import MAX_CANDIDATES, CsvHSTable, _norm, _Row, keep_in_candidates, load_hs_table
from tools.models import HSCandidate


def _row(hsk: str, ko: str, en: str) -> _Row:
    return _Row(hsk, ko, en, _norm(ko + " " + en))


@pytest.fixture
def small() -> CsvHSTable:
    return CsvHSTable(
        [
            _row("8507600010", "리튬이온 축전지", "Lithium-ion accumulators"),
            _row("8507600090", "기타 리튬이온 축전지", "Other lithium-ion accumulators"),
            _row("8507800000", "기타 축전지", "Other accumulators"),
            _row("2825201000", "산화리튬", "Lithium oxide"),
            _row("0101219000", "기타", "Other"),
        ]
    )


def _cand(hs: str, reason: str = "r") -> HSCandidate:
    return HSCandidate(hs=hs, name="n", reason=reason)


def test_구절이_통째로_맞는_코드가_먼저(small):
    got = small.search(["lithium-ion accumulators"])
    assert [c.hs for c in got[:2]] == ["8507600010", "8507600090"]


def test_한글과_영문_동의어를_함께_주면_양쪽이_맞는_코드가_위로(small):
    got = small.search(["리튬이온 축전지", "lithium-ion battery"])
    assert got[0].hs == "8507600010"


def test_흔한_말만_있는_검색어는_아무것도_찾지_않는다(small):
    assert small.search(["기타", "other"]) == []


def test_영문은_단어_앞부분에서만_맞는다():
    t = CsvHSTable([_row("1111111111", "물개", "Sea lions"), _row("2222222222", "폴리술폰", "Polysulphones")])
    assert t.search(["ion", "phone"]) == []
    assert [c.hs for c in t.search(["lion"])] == ["1111111111"]


def test_안_맞으면_빈_목록(small):
    assert small.search(["냉장고"]) == []
    assert small.search([]) == []


def test_후보는_최대_30개(small):
    many = CsvHSTable([_row(f"{i:010d}", f"볼트 {i}", f"Bolt {i}") for i in range(100)])
    assert len(many.search(["볼트"])) == MAX_CANDIDATES
    assert len(many.search(["볼트"], limit=500)) == MAX_CANDIDATES
    assert len(many.search(["볼트"], limit=5)) == 5
    assert many.search(["볼트"], limit=0) == []


def test_점수가_같으면_부호_순(small):
    got = small.search(["accumulators"])
    codes = [c.hs for c in got]
    assert codes == sorted(codes)


def test_이유에_맞은_검색어가_적힌다(small):
    got = small.search(["산화리튬"])
    assert "산화리튬" in got[0].reason


def test_under는_앞_6자리_아래_코드를_부호_순으로(small):
    assert [c.hs for c in small.under("850760")] == ["8507600010", "8507600090"]
    assert [c.hs for c in small.under("8507.60")] == ["8507600010", "8507600090"]


def test_under는_자리가_모자라면_빈_목록(small):
    assert small.under("85") == []
    assert small.under("") == []


def test_exists(small):
    assert small.exists("8507600010")
    assert not small.exists("8507600011")
    assert not small.exists("850760")


def test_후보_밖_코드는_버린다():
    cands = [_cand("1111111111"), _cand("2222222222")]
    picks = [_cand("9999999999", "모델이 지어냄"), _cand("2222222222", "송장 품명 칸")]
    got = keep_in_candidates(picks, cands)
    assert [p.hs for p in got] == ["2222222222"]
    assert got[0].reason == "송장 품명 칸"


def test_같은_코드는_한_번만_최대_3개():
    cands = [_cand(f"{i}" * 10) for i in range(1, 6)]
    picks = [_cand("1" * 10), _cand("1" * 10), _cand("2" * 10), _cand("3" * 10), _cand("4" * 10)]
    assert [p.hs for p in keep_in_candidates(picks, cands)] == ["1" * 10, "2" * 10, "3" * 10]


def test_품목명은_후보_쪽_값을_쓴다():
    cands = [HSCandidate(hs="1" * 10, name="표의 품목명", reason="x")]
    got = keep_in_candidates([HSCandidate(hs="1" * 10, name="모델이 바꾼 이름", reason="송장 품명")], cands)
    assert got[0].name == "표의 품목명"


def _cat_row(hsk: str, ko: str, en: str, category: str) -> _Row:
    return _Row(hsk, ko, en, _norm(f"{ko} {en} {category}"), category)


def test_이름이_기타뿐인_줄도_상위_분류로_찾는다():
    t = CsvHSTable([_cat_row("9401699000", "기타", "Other", "가구"), _cat_row("0101219000", "기타", "Other", "말")])
    assert [c.hs for c in t.search(["가구"])] == ["9401699000"]


def test_후보_이름에_상위_분류가_붙는다():
    t = CsvHSTable([_cat_row("9401699000", "기타", "Other", "가구"), _row("7318152000", "볼트", "Bolts")])
    names = {c.hs: c.name for c in t.search(["가구", "bolt"])}
    assert names["9401699000"].endswith("[가구]")
    assert "[" not in names["7318152000"]


def test_숫자가_든_단어는_검색어에서_뺀다():
    t = CsvHSTable([_row("1111111111", "볼트", "Bolts"), _row("2222222222", "수량 10", "Quantity 10")])
    assert [c.hs for c in t.search(["BOLT M10X50 A2-70 10 50L"])] == ["1111111111"]


def test_드문_단어가_흔한_단어보다_위():
    common = [_row(f"{i:010d}", "흰색 물건", f"White item {i}") for i in range(1, 30)]
    t = CsvHSTable(common + [_row("9999999999", "멜라민 접시", "Melamine plate")])
    assert t.search(["white melamine"])[0].hs == "9999999999"


def test_단어_그대로_맞는_줄이_앞부분만_맞는_줄보다_위():
    t = CsvHSTable([_row("1111111111", "가자미", "Pleuronectes platessa"), _row("2222222222", "접시", "Plate")])
    assert [c.hs for c in t.search(["plate"])] == ["2222222222", "1111111111"]


def test_실제_CSV는_모든_줄에_상위_분류가_있다():
    table = load_hs_table()
    assert all(r.category for r in table._rows)


def test_실제_CSV를_읽는다():
    table = load_hs_table()
    assert table.exists("0101211000")
    assert len(table.under("010121")) >= 1
    got = table.search(["리튬", "lithium"])
    assert 0 < len(got) <= MAX_CANDIDATES
    assert all(table.exists(c.hs) for c in got)
