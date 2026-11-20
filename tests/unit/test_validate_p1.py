"""cross_check P1 규칙 단위 테스트 (FB06 #163). 가짜 추출 결과를 쓰고 AWS와 Bedrock을 부르지 않는다. 담당: 검증."""

import pytest

from tools.models import Cell, ExtractedDocument, ExtractedItem
from tools.validate import cross_check


def only(docs, rule_id):
    """한 규칙의 결과만 본다."""
    return [i for i in cross_check(docs) if i.rule_id == rule_id]


def doc(doc_type, **cells):
    """칸 이름 → Cell로 채운 가짜 추출 결과."""
    return ExtractedDocument(doc_type=doc_type, file=f"uploads/s/{doc_type}.pdf", **cells)


def no_cell(text):
    return Cell(raw=text, value=text)


def pkgs(n):
    return Cell(raw=f"{n:,} CARTONS", value=n, unit="CTN")


# --- X-INV-01 원산지증명서 송장 번호 -------------------------------------------------


def test_송장_번호는_원산지증명서도_함께_본다():
    docs = [
        doc("commercial_invoice", doc_no=no_cell("TNC-26-0269")),
        doc("packing_list", doc_no=no_cell("TNC-26-0269")),
        doc("certificate_of_origin", doc_no=no_cell("TNC-26-0296")),
    ]
    [issue] = only(docs, "X-INV-01")
    assert issue.grade == "불일치"
    assert issue.suspect == "certificate_of_origin"  # 셋 중 하나만 다르면 그 서류를 짚는다
    assert issue.evidence == "원산지증명서 송장 번호 TNC-26-0296과 상업송장·포장명세서 TNC-26-0269이 다릅니다."


def test_원산지증명서만_있는_조합에서도_송장과_대조한다():
    docs = [doc("commercial_invoice", doc_no=no_cell("A-1")), doc("certificate_of_origin", doc_no=no_cell("A-2"))]
    [issue] = only(docs, "X-INV-01")
    assert {c.doc for c in issue.cells} == {"commercial_invoice", "certificate_of_origin"}


def test_원산지증명서_송장_번호가_같으면_문제_없음():
    docs = [doc("commercial_invoice", doc_no=no_cell("A-1")), doc("certificate_of_origin", doc_no=no_cell("A-1"))]
    assert only(docs, "X-INV-01") == []


def test_선하증권은_송장_번호_대조에_넣지_않는다():
    docs = [doc("commercial_invoice", doc_no=no_cell("A-1")), doc("bill_of_lading", doc_no=no_cell("BL-9"))]
    assert only(docs, "X-INV-01") == []


# --- X-PKG-01 총포장수 -------------------------------------------------------------


def test_총포장수가_같으면_문제_없음():
    docs = [doc("packing_list", total_packages=pkgs(327)), doc("bill_of_lading", total_packages=pkgs(327))]
    assert only(docs, "X-PKG-01") == []


def test_총포장수가_다르면_불일치와_근거():
    docs = [doc("packing_list", total_packages=pkgs(327)), doc("bill_of_lading", total_packages=pkgs(325))]
    [issue] = only(docs, "X-PKG-01")
    assert issue.grade == "불일치"
    assert issue.evidence == "포장명세서 총포장수 327과 선하증권 325이 다릅니다."
    assert [(c.doc, c.field) for c in issue.cells] == [
        ("packing_list", "total_packages"),
        ("bill_of_lading", "total_packages"),
    ]


def test_총포장수는_허용_오차가_없어_한_박스_차이도_불일치():
    docs = [doc("packing_list", total_packages=pkgs(541)), doc("bill_of_lading", total_packages=pkgs(540))]
    assert [i.grade for i in only(docs, "X-PKG-01")] == ["불일치"]


def test_포장명세서에_총포장수_칸이_없으면_비교하지_않고_확인_필요도_내지_않는다():
    docs = [doc("packing_list"), doc("bill_of_lading", total_packages=pkgs(325))]
    assert only(docs, "X-PKG-01") == []


def test_칸_없음으로_표시된_칸도_비교에서_뺀다():
    docs = [
        doc("packing_list", total_packages=Cell(unreadable="칸 없음")),
        doc("bill_of_lading", total_packages=pkgs(325)),
    ]
    assert only(docs, "X-PKG-01") == []


def test_총포장수를_못_읽으면_일치로_세지_않고_확인_필요():
    docs = [
        doc("packing_list", total_packages=pkgs(327)),
        doc("bill_of_lading", total_packages=Cell(unreadable="흐림")),
    ]
    [issue] = only(docs, "X-PKG-01")
    assert issue.grade == "확인 필요"
    assert issue.evidence == "선하증권 총포장수를 읽지 못했습니다(흐림)."


def test_총포장수가_글자라_숫자로_못_풀면_확인_필요():
    docs = [
        doc("packing_list", total_packages=pkgs(327)),
        doc("bill_of_lading", total_packages=Cell(raw="SEE ATTACHED", value=None)),
    ]
    [issue] = only(docs, "X-PKG-01")
    assert (issue.grade, issue.evidence) == ("확인 필요", "선하증권 총포장수를 읽지 못했습니다(숫자로 풀 수 없음).")


def test_총포장수는_품목_수량_합계와_섞지_않는다():
    item = ExtractedItem(line=1, qty=Cell(raw="13,560 PCS", value=13560, unit="EA"))
    docs = [doc("packing_list", items=[item]), doc("bill_of_lading", total_packages=pkgs(325))]
    assert only(docs, "X-PKG-01") == []  # 줄 값을 더해 총포장수로 쓰지 않는다


@pytest.mark.parametrize("rule_id", ["X-INV-01", "X-PKG-01"])
def test_빈_목록과_한_장은_문제_없음(rule_id):
    assert only([], rule_id) == []
    assert only([doc("bill_of_lading", total_packages=pkgs(1), doc_no=no_cell("A"))], rule_id) == []
