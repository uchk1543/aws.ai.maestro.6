"""C2 HS 확정 단위 테스트. AWS와 Bedrock을 부르지 않는다. 모델 응답은 가짜다. 담당: 검증."""
import pytest

from tests.unit.fakes import MemoryHSHistory
from tools.hs import CsvHSTable, _norm, _Row, confirm_by_human, is_known_hs, item_key, recommend_hs
from tools.models import Cell, ExtractedDocument, ExtractedItem, HSCandidate, HSPick, HSSearchTerms

BATT = "8507603000"  # 에너지 저장장치용 (정답이라고 가정)
BATT_OTHER = "8507609000"
TRAP = "8507200000"


def _row(hsk: str, ko: str, en: str) -> _Row:
    return _Row(hsk, ko, en, _norm(ko + " " + en))


@pytest.fixture
def table() -> CsvHSTable:
    return CsvHSTable(
        [
            _row(BATT, "에너지 저장장치용", "For energy storage systems lithium-ion battery"),
            _row(BATT_OTHER, "기타", "Other"),
            _row(TRAP, "연산 축전지", "Other lead-acid accumulators"),
            _row("7318152000", "볼트", "Bolts"),
        ]
    )


def _doc(doc_type: str, hs: str | None, *, code: str | None = "BP-200", name: str | None = "LITHIUM-ION BATTERY PACK") -> ExtractedDocument:
    item = ExtractedItem(
        line=1,
        item_code=Cell(raw=code, value=code) if code else None,
        name=Cell(raw=name, value=name) if name else None,
        hs_code=Cell(raw=hs, value=hs) if hs else None,
    )
    return ExtractedDocument(doc_type=doc_type, file=f"uploads/{doc_type}.pdf", items=[item])


def _cand(hs: str, reason: str = "송장 품명 칸") -> HSCandidate:
    return HSCandidate(hs=hs, name="n", reason=reason)


def picker_of(*codes: str):
    return lambda name, cands: HSPick(picks=[_cand(c) for c in codes])


def reader_of(*terms: str):
    return lambda name: HSSearchTerms(terms=list(terms))


def run(docs, table, history=None, *, picker=None, reader=None, importer="수입자A"):
    return recommend_hs(docs, 1, importer, history=history or MemoryHSHistory(), table=table, terms_reader=reader, picker=picker)


# --- item_key ---------------------------------------------------------------


def test_품목_키는_코드가_있으면_코드():
    assert item_key(_doc("commercial_invoice", None, code="bp 200"), 1) == "code:BP200"


def test_품목_키는_코드가_없으면_정규화한_품명():
    assert item_key(_doc("commercial_invoice", None, code=None, name="Lithium-Ion  Battery Pack"), 1) == "name:lithium ion battery pack"


def test_품목_키는_행이_없거나_둘_다_비면_오류():
    with pytest.raises(ValueError):
        item_key(_doc("commercial_invoice", None), 2)
    with pytest.raises(ValueError):
        item_key(_doc("commercial_invoice", None, code=None, name=None), 1)


# --- 확정 이력 ----------------------------------------------------------------


def test_이력이_있으면_모델을_부르지_않고_자동_확정(table):
    h = MemoryHSHistory()
    h.put("수입자A", "code:BP-200", BATT, "job-1")

    def boom(*a):
        raise AssertionError("모델을 부르면 안 됨")

    r = run([_doc("commercial_invoice", None)], table, h, picker=boom, reader=boom)
    assert (r.status, r.by, r.hs_code) == ("자동 확정", "history", BATT)


def test_이력은_수입자가_다르면_쓰지_않는다(table):
    h = MemoryHSHistory()
    h.put("수입자B", "code:BP-200", BATT, "job-1")
    assert run([_doc("commercial_invoice", None)], table, h).status == "사람 확인 필요"


def test_이력의_코드가_표에_없으면_믿지_않는다(table):
    h = MemoryHSHistory()
    h.put("수입자A", "code:BP-200", "9999999999", "job-1")
    r = run([_doc("commercial_invoice", None)], table, h)
    assert r.status == "사람 확인 필요" and r.hs_code is None


def test_두번째부터_자동_사람이_한번_고르면_다음엔_이력으로(table):
    h = MemoryHSHistory()
    docs = [_doc("commercial_invoice", None)]
    first = run(docs, table, h, reader=reader_of("lithium-ion battery"), picker=picker_of(BATT))
    assert first.status == "사람 확인 필요"
    done = confirm_by_human(first, BATT, "수입자A", item_key(docs[0], 1), "job-1", history=h)
    assert (done.status, done.by, done.hs_code) == ("사람 확정", "human", BATT)
    second = run(docs, table, h)
    assert (second.status, second.by, second.hs_code) == ("자동 확정", "history", BATT)


# --- 자동 확정(auto_match) ------------------------------------------------------


def test_서류_10자리가_같고_표에_있고_1순위와_같으면_자동_확정(table):
    docs = [_doc("commercial_invoice", BATT), _doc("certificate_of_origin", "8507.60.3000")]
    r = run(docs, table, reader=reader_of("battery"), picker=picker_of(BATT, BATT_OTHER))
    assert (r.status, r.by, r.hs_code) == ("자동 확정", "auto_match", BATT)


def test_1순위가_다르면_사람_확인(table):
    docs = [_doc("commercial_invoice", BATT)]
    r = run(docs, table, reader=reader_of("battery"), picker=picker_of(BATT_OTHER, BATT))
    assert r.status == "사람 확인 필요" and r.hs_code is None


def test_서류끼리_다르면_사람_확인(table):
    docs = [_doc("commercial_invoice", BATT), _doc("certificate_of_origin", BATT_OTHER)]
    r = run(docs, table, reader=reader_of("battery"), picker=picker_of(BATT))
    assert r.status == "사람 확인 필요"


def test_6자리와_10자리가_섞이면_사람_확인(table):
    docs = [_doc("commercial_invoice", BATT), _doc("certificate_of_origin", "850760")]
    assert run(docs, table, picker=picker_of(BATT)).status == "사람 확인 필요"


def test_6자리만_있으면_그_아래_10자리가_후보로_나온다(table):
    r = run([_doc("commercial_invoice", "850760")], table, picker=picker_of(BATT, BATT_OTHER))
    assert r.status == "사람 확인 필요"
    assert [c.hs for c in r.candidates] == [BATT, BATT_OTHER]


def test_표에_없는_10자리면_사람_확인(table):
    docs = [_doc("commercial_invoice", "8507601234")]
    r = run(docs, table, picker=picker_of("8507601234"))
    assert r.status == "사람 확인 필요"


def test_서류에_HS가_없으면_사람_확인(table):
    r = run([_doc("commercial_invoice", None)], table, reader=reader_of("lithium-ion battery"), picker=picker_of(BATT))
    assert r.status == "사람 확인 필요" and [c.hs for c in r.candidates] == [BATT]


def test_함정_서류가_틀린_HS를_같이_적어도_모델이_다르면_자동_확정_안_함(table):
    """송장과 원산지증명서에 같은 헷갈리는 HS가 적혀 있어도, 모델 1순위와 다르면 사람에게 넘긴다."""
    docs = [_doc("commercial_invoice", TRAP), _doc("certificate_of_origin", TRAP)]
    r = run(docs, table, picker=picker_of(BATT))
    assert r.status == "사람 확인 필요" and r.hs_code is None


def test_모델이_함정과_같은_코드를_골라도_서류가_같으면_자동_확정된다_이_경우는_이력과_사람이_막는다(table):
    """알려진 한계: 서류와 모델이 같은 틀린 코드를 가리키면 6번 조건만으로는 못 막는다. 현재 동작을 고정해 둔다."""
    docs = [_doc("commercial_invoice", TRAP), _doc("certificate_of_origin", TRAP)]
    r = run(docs, table, picker=picker_of(TRAP))
    assert r.by == "auto_match"


# --- 모델이 없거나 틀릴 때 ---------------------------------------------------------


def test_후보_밖_코드는_버린다(table):
    r = run([_doc("commercial_invoice", None)], table, reader=reader_of("battery"), picker=picker_of("1234567890", BATT))
    assert [c.hs for c in r.candidates] == [BATT]


def test_모델이_없으면_자동_확정_없이_품명으로_검색한_후보를_낸다(table):
    r = run([_doc("commercial_invoice", BATT, name="lithium-ion battery")], table)
    assert r.status == "사람 확인 필요"
    assert BATT in [c.hs for c in r.candidates]


def test_모델이_예외를_내면_자동_확정_없이_사람_확인(table):
    def boom(*a):
        raise RuntimeError("timeout")

    docs = [_doc("commercial_invoice", BATT)]
    r = run(docs, table, reader=boom, picker=boom)
    assert r.status == "사람 확인 필요"


def test_후보를_3개_넘게_고르면_3개만(table):
    r = run([_doc("commercial_invoice", None)], table, reader=reader_of("battery", "bolt"), picker=picker_of(BATT, BATT_OTHER, TRAP, "7318152000"))
    assert len(r.candidates) <= 3


# --- 사람 확정 -----------------------------------------------------------------


def test_사람_확정은_10자리_숫자만_받고_틀리면_이력에_쓰지_않는다(table):
    h = MemoryHSHistory()
    first = run([_doc("commercial_invoice", None)], table, h)
    for bad in ("850760", "85076030AB", "8507.603000", ""):
        with pytest.raises(ValueError):
            confirm_by_human(first, bad, "수입자A", "code:BP-200", "job-1", history=h)
    assert h.rows == {}


def test_사람_확정은_후보를_그대로_남긴다(table):
    first = run([_doc("commercial_invoice", None)], table, reader=reader_of("battery"), picker=picker_of(BATT, BATT_OTHER))
    done = confirm_by_human(first, BATT_OTHER, "수입자A", "code:BP-200", "job-1", history=MemoryHSHistory())
    assert done.hs_code == BATT_OTHER and done.candidates == first.candidates

# --- 품명·서류 HS를 결과에 담기 (FB07 #164) -------------------------------------------


def test_사람_확인_결과에_품명과_서류_HS가_담긴다(table):
    docs = [_doc("commercial_invoice", "8507.60", name="KNOCK-DOWN DINING CHAIR")]
    r = run(docs, table, reader=reader_of("battery"), picker=picker_of(BATT))
    assert r.status == "사람 확인 필요"
    assert (r.item_name, r.doc_hs_code) == ("KNOCK-DOWN DINING CHAIR", "8507.60")


def test_서류에_HS가_없으면_서류_HS는_null이고_품명은_담긴다(table):
    r = run([_doc("commercial_invoice", None)], table)
    assert (r.item_name, r.doc_hs_code) == ("LITHIUM-ION BATTERY PACK", None)


def test_품명을_못_읽었으면_품명은_null(table):
    r = run([_doc("commercial_invoice", None, name=None)], table)
    assert r.item_name is None


def test_이력으로_자동_확정해도_품명과_서류_HS가_담긴다(table):
    h = MemoryHSHistory()
    h.put("수입자A", "code:BP-200", BATT, "job-1")
    r = run([_doc("commercial_invoice", "8507.60")], table, h)
    assert (r.by, r.item_name, r.doc_hs_code) == ("history", "LITHIUM-ION BATTERY PACK", "8507.60")


def test_자동_확정_auto_match도_품명과_서류_HS가_담긴다(table):
    r = run([_doc("commercial_invoice", BATT)], table, reader=reader_of("battery"), picker=picker_of(BATT))
    assert (r.by, r.item_name, r.doc_hs_code) == ("auto_match", "LITHIUM-ION BATTERY PACK", BATT)


def test_서류_HS는_상업송장부터_우선한다(table):
    docs = [_doc("packing_list", "9999.99"), _doc("commercial_invoice", "8507.60")]
    assert run(docs, table).doc_hs_code == "8507.60"


def test_사람_확정해도_품명과_서류_HS를_남긴다(table):
    first = run([_doc("commercial_invoice", "8507.60")], table, reader=reader_of("battery"), picker=picker_of(BATT))
    done = confirm_by_human(first, BATT, "수입자A", "code:BP-200", "job-1", history=MemoryHSHistory())
    assert (done.item_name, done.doc_hs_code) == ("LITHIUM-ION BATTERY PACK", "8507.60")


# --- 직접 입력한 HS가 표에 있는지 (FB07 #164, 서버 #181이 400에 쓴다) ------------------


def test_표에_있는_10자리_코드만_참(table):
    assert is_known_hs(BATT, table) is True
    assert is_known_hs("9999999999", table) is False  # 10자리지만 표에 없음


@pytest.mark.parametrize("bad", ["", "850760", "8507603000 ", "8507.603000", "85076030AB", "８５０７６０３０００"])
def test_10자리_숫자가_아니면_거짓(table, bad):
    assert is_known_hs(bad, table) is False
