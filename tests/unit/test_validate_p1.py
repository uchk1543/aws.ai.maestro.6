"""cross_check P1 규칙 단위 테스트 (FB06 #163). 가짜 추출 결과를 쓰고 AWS와 Bedrock을 부르지 않는다. 담당: 검증."""

import pytest

from tools.models import Cell, ExtractedDocument, ExtractedItem
from tools.validate import container_check_digit, cross_check


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

# --- X-CNTR-01 컨테이너 번호 체크 디지트 (ISO 6346) ---------------------------------


def bl(container_no, raw=None, unreadable=None):
    cell = Cell(raw=raw or container_no, value=container_no, unreadable=unreadable)
    return doc("bill_of_lading", container_no=cell)


@pytest.mark.parametrize(
    ("first10", "digit"),
    [
        ("CSQU305438", 3),  # ISO 6346 표준 예시
        ("SMLU777929", 2),  # 정답지 D016의 원래 번호 SMLU7779292
        ("MSKU000000", 6),  # 합 424, 424 % 11 = 6
        ("MSKU000008", 0),  # 합 4520, 4520 % 11 = 10 이면 0
    ],
)
def test_체크_디지트_계산(first10, digit):
    assert container_check_digit(first10) == digit


def test_글자값은_11의_배수를_건너뛴다():
    # K=21, L=23이라서 L이 든 번호는 K와 값이 달라야 한다 (건너뛰지 않으면 같은 자리에서 틀어진다)
    assert container_check_digit("ABCL123456") != container_check_digit("ABCK123456")
    assert container_check_digit("TLLU123456") == 6  # 합 5561, 5561 % 11 = 6 (L을 22로 세면 값이 달라진다)


def test_컨테이너_번호가_맞으면_문제_없음():
    assert only([bl("SMLU7779292")], "X-CNTR-01") == []


def test_체크_디지트가_틀리면_불일치와_맞는_숫자를_알려_준다():
    [issue] = only([bl("SMLU7779294")], "X-CNTR-01")
    assert issue.grade == "불일치"
    assert issue.evidence == "선하증권 컨테이너 번호 SMLU7779294의 체크 디지트가 맞지 않습니다(끝 숫자는 2이어야 함)."
    assert [(c.doc, c.field, c.raw) for c in issue.cells] == [("bill_of_lading", "container_no", "SMLU7779294")]


def test_컨테이너가_여럿이면_틀린_것만_짚는다():
    issues = only([bl("SMLU7779294 SMCU4612216")], "X-CNTR-01")
    assert [i.grade for i in issues] == ["불일치"]
    assert "SMLU7779294" in issues[0].evidence and "SMCU4612216" not in issues[0].evidence


def test_글자_사이_공백과_하이픈은_무시한다():
    assert only([bl("SMLU 777929 2")], "X-CNTR-01") == []
    assert [i.grade for i in only([bl("SMLU-777929-4")], "X-CNTR-01")] == ["불일치"]


def test_소문자로_읽어도_같게_본다():
    assert only([bl("smlu7779292")], "X-CNTR-01") == []


def test_번호_형식이_아니면_확인_필요():
    [issue] = only([bl("SMLU77792")], "X-CNTR-01")  # 한 자리 모자람
    assert (issue.grade, issue.evidence) == ("확인 필요", "선하증권 컨테이너 번호를 확인하지 못했습니다(컨테이너 번호 형식이 아님).")


def test_컨테이너_번호를_못_읽으면_일치로_세지_않고_확인_필요():
    [issue] = only([doc("bill_of_lading", container_no=Cell(unreadable="가려짐"))], "X-CNTR-01")
    assert (issue.grade, issue.evidence) == ("확인 필요", "선하증권 컨테이너 번호를 확인하지 못했습니다(가려짐).")


def test_컨테이너_칸이_없으면_판정하지_않는다():
    assert only([doc("bill_of_lading")], "X-CNTR-01") == []
    assert only([doc("bill_of_lading", container_no=Cell(unreadable="칸 없음"))], "X-CNTR-01") == []


def test_컨테이너_번호는_선하증권에서만_본다():
    other = doc("commercial_invoice", container_no=no_cell("SMLU7779294"))
    assert only([other], "X-CNTR-01") == []


# --- X-SUM-01 상업송장 줄 금액 합 = 총금액 ---------------------------------------------


def amt(value, raw=None):
    return Cell(raw=raw or f"USD {value:,.2f}", value=value, unit="USD")


def invoice(total, *line_amounts, total_raw=None):
    items = [ExtractedItem(line=n, amount=a) for n, a in enumerate(line_amounts, start=1)]
    return doc("commercial_invoice", total_amount=total, items=items)


def test_줄_금액_합이_총금액과_같으면_문제_없음():
    assert only([invoice(amt(11130.0), amt(9828.0), amt(1302.0))], "X-SUM-01") == []


def test_줄_금액_합이_총금액과_다르면_불일치와_근거():
    [issue] = only([invoice(amt(29701.0), amt(15000.0), amt(14710.0))], "X-SUM-01")
    assert issue.grade == "불일치"
    assert issue.evidence == "상업송장 줄 금액 합 29,710과 총금액 29,701이 다릅니다."


def test_줄_금액_불일치는_총금액과_줄_칸을_모두_짚는다():
    [issue] = only([invoice(amt(29701.0), amt(15000.0), amt(14710.0))], "X-SUM-01")
    assert [(c.doc, c.field) for c in issue.cells] == [
        ("commercial_invoice", "total_amount"),
        ("commercial_invoice", "items[0].amount"),
        ("commercial_invoice", "items[1].amount"),
    ]


def test_센트_단위_합은_부동소수_오차를_무시한다():
    assert only([invoice(amt(0.3), amt(0.1), amt(0.2))], "X-SUM-01") == []  # 0.1 + 0.2 != 0.3 (부동소수)


def test_허용_오차_0_01_안의_차이는_참고():
    [issue] = only([invoice(amt(100.0), amt(50.0), amt(50.01))], "X-SUM-01")
    assert issue.grade == "참고"
    assert issue.evidence == "상업송장 줄 금액 합 100.01과 총금액 100이 허용 오차 0.01 안에서 다릅니다."


def test_허용_오차를_넘으면_불일치():
    assert [i.grade for i in only([invoice(amt(100.0), amt(50.0), amt(50.02))], "X-SUM-01")] == ["불일치"]


def test_줄_금액을_못_읽으면_일치로_세지_않고_확인_필요():
    docs = [invoice(amt(100.0), amt(60.0), Cell(unreadable="흐림"))]
    [issue] = only(docs, "X-SUM-01")
    assert (issue.grade, issue.evidence) == ("확인 필요", "상업송장 줄 금액 합과 총금액을 비교하지 못했습니다(2행 금액 흐림).")
    assert [c.field for c in issue.cells] == ["total_amount"]


def test_줄_금액_칸이_없으면_확인_필요():
    [issue] = only([invoice(amt(100.0), None)], "X-SUM-01")
    assert (issue.grade, issue.evidence) == ("확인 필요", "상업송장 줄 금액 합과 총금액을 비교하지 못했습니다(1행 금액 칸 없음).")


def test_품목_행이_하나도_없으면_확인_필요():
    [issue] = only([invoice(amt(100.0))], "X-SUM-01")
    assert issue.grade == "확인 필요" and "줄 금액 칸 없음" in issue.evidence


def test_총금액을_못_읽으면_확인_필요():
    [issue] = only([invoice(Cell(unreadable="가려짐"), amt(100.0))], "X-SUM-01")
    assert (issue.grade, issue.evidence) == ("확인 필요", "상업송장 줄 금액 합과 총금액을 비교하지 못했습니다(총금액 가려짐).")


def test_총금액_칸이_없는_송장은_판정하지_않는다():
    assert only([invoice(None, amt(100.0))], "X-SUM-01") == []


def test_줄_금액_합은_상업송장에서만_본다():
    other = doc("packing_list", total_amount=amt(1.0), items=[ExtractedItem(line=1, amount=amt(5.0))])
    assert only([other], "X-SUM-01") == []


def test_서류_한_장만_있어도_한_장_안_규칙은_돈다():
    assert [i.rule_id for i in cross_check([bl("SMLU7779294")])] == ["X-CNTR-01"]
