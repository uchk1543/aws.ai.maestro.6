"""cross_check P1 규칙 단위 테스트 (FB06 #163). 가짜 추출 결과를 쓰고 AWS와 Bedrock을 부르지 않는다. 담당: 검증."""

import pytest

from tools.models import Cell, ExtractedContainer, ExtractedDocument, ExtractedItem
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


# --- 현장 칸 규칙 (B13 #229): X-MARK-01 화인, X-PKG-02 컨테이너 줄 포장 수, X-PKG-03 품목별 포장 수 -------------
def marks(text):
    """read_document가 푸는 방식대로: value는 대문자·공백 하나."""
    return Cell(raw=text, value=" ".join(text.upper().split()))
def unread(reason):
    """못 읽은 칸. reason이 '칸 없음'이면 그 양식에 없는 칸이다."""
    return Cell(raw=None, value=None, unreadable=reason)
def cont(line, n):
    return ExtractedContainer(line=line, packages=Cell(raw=f"{n} CTNS", value=n, unit="CTN"))
def test_화인_줄바꿈과_구두점만_다르면_문제_없음():
    docs = [
        doc("bill_of_lading", marks=marks("EXAMPLE DISTRIBUTION KOREA\nINC.\nBUSAN, KOREA\nC/NO. 1-53")),
        doc("packing_list", marks=marks("EXAMPLE \nDISTRIBUTION KOREA \nINC.\nBUSAN,KOREA\nC/NO.1-53")),
    ]
    assert only(docs, "X-MARK-01") == []
def test_화인이_다르면_확인_필요와_두_칸():
    docs = [
        doc("bill_of_lading", marks=marks("EXAMPLE BUSAN C/NO. 1-53")),
        doc("packing_list", marks=marks("EXAMPLE BUSAN C/NO. 1-35")),
    ]
    [issue] = only(docs, "X-MARK-01")
    assert issue.grade == "확인 필요"
    assert [(c.doc, c.field) for c in issue.cells] == [("bill_of_lading", "marks"), ("packing_list", "marks")]
    assert issue.evidence == (
        "선하증권과 포장명세서의 화인을 확인해 주세요"
        "(선하증권 'EXAMPLE BUSAN C/NO. 1-53'과 포장명세서 'EXAMPLE BUSAN C/NO. 1-35'이 다름)."
    )
def test_화인이_한쪽을_포함해도_번호_범위가_다르면_확인_필요():
    """'1-5'는 '1-53'의 앞부분이다. 포함 관계를 참고로 낮추면 번호 범위의 자리 빠짐을 놓친다."""
    docs = [doc("bill_of_lading", marks=marks("EXAMPLE C/NO. 1-53")), doc("packing_list", marks=marks("EXAMPLE C/NO. 1-5"))]
    assert [i.grade for i in only(docs, "X-MARK-01")] == ["확인 필요"]
def test_포장명세서에_화인_칸이_없으면_건너뜀():
    docs = [doc("bill_of_lading", marks=marks("EXAMPLE")), doc("packing_list", marks=unread("칸 없음"))]
    assert only(docs, "X-MARK-01") == []
    assert only([doc("bill_of_lading", marks=marks("EXAMPLE")), doc("packing_list")], "X-MARK-01") == []
def test_화인이_흐리면_확인_필요():
    docs = [doc("bill_of_lading", marks=marks("EXAMPLE")), doc("packing_list", marks=unread("흐림"))]
    [issue] = only(docs, "X-MARK-01")
    assert issue.grade == "확인 필요" and "포장명세서 화인 흐림" in issue.evidence
    assert [(c.doc, c.field) for c in issue.cells] == [("packing_list", "marks")]
def test_화인이_기호뿐이면_비교하지_않고_확인_필요():
    docs = [doc("bill_of_lading", marks=marks("EXAMPLE")), doc("packing_list", marks=marks("---"))]
    [issue] = only(docs, "X-MARK-01")
    assert issue.grade == "확인 필요" and "읽을 글자가 없음" in issue.evidence
def test_화인은_두_서류가_다_있어야_비교한다():
    assert only([doc("bill_of_lading", marks=marks("EXAMPLE"))], "X-MARK-01") == []
def test_컨테이너_줄_포장_수_합이_다르면_불일치():
    d = doc("bill_of_lading", total_packages=pkgs(535), containers=[cont(1, 300), cont(2, 230)])
    [issue] = only([d], "X-PKG-02")
    assert issue.grade == "불일치"
    assert issue.evidence == "선하증권 컨테이너 줄 포장 수 합 530과 총포장수 535이 다릅니다."
    assert [(c.field, c.raw) for c in issue.cells] == [
        ("containers[*].packages", "300 CTNS + 230 CTNS"),
        ("total_packages", "535 CARTONS"),
    ]
def test_컨테이너_줄_포장_수_합이_같으면_문제_없음():
    assert only([doc("bill_of_lading", total_packages=pkgs(535), containers=[cont(1, 300), cont(2, 235)])], "X-PKG-02") == []
def test_컨테이너_줄_하나가_흐리면_확인_필요():
    blurred = ExtractedContainer(line=2, packages=unread("흐림"))
    d = doc("bill_of_lading", total_packages=pkgs(535), containers=[cont(1, 300), blurred])
    [issue] = only([d], "X-PKG-02")
    assert issue.grade == "확인 필요" and "컨테이너 2번째 줄 포장 수 흐림" in issue.evidence
    assert [c.field for c in issue.cells] == ["containers[1].packages"]
def test_컨테이너_줄이_없으면_건너뜀():
    assert only([doc("bill_of_lading", total_packages=pkgs(535))], "X-PKG-02") == []
def test_컨테이너_줄_포장_수가_모두_칸_없음이면_건너뜀():
    d = doc("bill_of_lading", total_packages=pkgs(535), containers=[ExtractedContainer(line=1, packages=unread("칸 없음"))])
    assert only([d], "X-PKG-02") == []
def test_컨테이너_줄_합은_총포장수_칸이_없으면_건너뜀():
    assert only([doc("bill_of_lading", containers=[cont(1, 300)])], "X-PKG-02") == []
def test_총포장수를_못_읽으면_합을_비교하지_않고_확인_필요():
    d = doc("bill_of_lading", total_packages=unread("흐림"), containers=[cont(1, 300)])
    [issue] = only([d], "X-PKG-02")
    assert issue.grade == "확인 필요" and "총포장수 흐림" in issue.evidence
def test_품목_포장_수_합이_다르면_불일치():
    items = [ExtractedItem(line=1, packages=pkgs(286)), ExtractedItem(line=2, packages=pkgs(370))]
    [issue] = only([doc("packing_list", total_packages=pkgs(660), items=items)], "X-PKG-03")
    assert issue.grade == "불일치"
    assert issue.evidence == "포장명세서 품목별 포장 수 합 656과 총포장수 660이 다릅니다."
    assert [c.field for c in issue.cells] == ["items[*].packages", "total_packages"]
def test_품목_포장_수_합이_같으면_문제_없음():
    items = [ExtractedItem(line=1, packages=pkgs(286)), ExtractedItem(line=2, packages=pkgs(374))]
    assert only([doc("packing_list", total_packages=pkgs(660), items=items)], "X-PKG-03") == []
def test_품목_포장_수가_모두_칸_없음이면_건너뜀():
    items = [ExtractedItem(line=1, packages=unread("칸 없음")), ExtractedItem(line=2)]
    assert only([doc("packing_list", total_packages=pkgs(53), items=items)], "X-PKG-03") == []
def test_품목_포장_수_한_행이_가려지면_확인_필요():
    items = [ExtractedItem(line=1, packages=pkgs(286)), ExtractedItem(line=2, packages=unread("가려짐"))]
    [issue] = only([doc("packing_list", total_packages=pkgs(660), items=items)], "X-PKG-03")
    assert issue.grade == "확인 필요" and "2행 포장 수 가려짐" in issue.evidence
def test_현장_칸_규칙은_서류_종류를_가린다():
    """포장명세서에 컨테이너 줄이 있어도 X-PKG-02는 선하증권만, 선하증권에 품목 포장 수가 있어도 X-PKG-03은 포장명세서만 본다."""
    pl = doc("packing_list", total_packages=pkgs(535), containers=[cont(1, 1)])
    bl = doc("bill_of_lading", total_packages=pkgs(660), items=[ExtractedItem(line=1, packages=pkgs(1))])
    assert only([pl], "X-PKG-02") == [] and only([bl], "X-PKG-03") == []


# --- 운임·원산지기준·소급 발급 규칙 (FB06 #163): X-FRT-01, X-OC-01, X-RETRO-01 ---------------------------------
def text(value):
    return Cell(raw=value, value=value)
def date_cell(iso):
    return Cell(raw=iso, value=iso)
def co_item(line, criterion, hs):
    return ExtractedItem(
        line=line,
        origin_criterion=text(criterion) if criterion else None,
        hs_code=Cell(raw=hs, value="".join(ch for ch in hs if ch.isdigit())),
    )
def co(departure="2026-11-13", issued="2026-11-12", retro=None, items=()):
    return doc(
        "certificate_of_origin",
        departure_date=date_cell(departure) if departure else None,
        issue_date=date_cell(issued) if issued else None,
        issued_retroactively=text(retro) if retro else None,
        items=list(items),
    )
def test_FOB인데_운임_선불이면_확인_필요():
    docs = [doc("commercial_invoice", incoterms=text("FOB BUSAN")), doc("bill_of_lading", freight_term=text("FREIGHT PREPAID"))]
    [issue] = only(docs, "X-FRT-01")
    assert issue.grade == "확인 필요"
    assert [(c.doc, c.field) for c in issue.cells] == [("commercial_invoice", "incoterms"), ("bill_of_lading", "freight_term")]
    assert issue.evidence == (
        "인코텀즈와 선하증권 운임 조건이 맞는지 확인해 주세요"
        "(상업송장 FOB은 운임 후불이 보통인데 선하증권은 FREIGHT PREPAID(선불))."
    )
def test_CIF인데_운임_후불이면_확인_필요():
    docs = [doc("commercial_invoice", incoterms=text("CIF HO CHI MINH")), doc("bill_of_lading", freight_term=text("FREIGHT COLLECT"))]
    [issue] = only(docs, "X-FRT-01")
    assert "상업송장 CIF은 운임 선불이 보통인데 선하증권은 FREIGHT COLLECT(후불)" in issue.evidence
@pytest.mark.parametrize(
    ("term", "freight"),
    [("FOB QINGDAO", "FREIGHT COLLECT"), ("EXW NINGBO", "FREIGHT COLLECT"), ("CIF BUSAN", "FREIGHT PREPAID"), ("CFR BUSAN", "FREIGHT PREPAID")],
)
def test_인코텀즈와_운임이_맞으면_문제_없음(term, freight):
    docs = [doc("commercial_invoice", incoterms=text(term)), doc("bill_of_lading", freight_term=text(freight))]
    assert only(docs, "X-FRT-01") == []
def test_운임_조건을_못_풀면_확인_필요():
    docs = [doc("commercial_invoice", incoterms=text("FOB")), doc("bill_of_lading", freight_term=text("AS ARRANGED"))]
    [issue] = only(docs, "X-FRT-01")
    assert "선하증권 운임 조건을 선불·후불로 풀 수 없음" in issue.evidence
    assert [c.field for c in issue.cells] == ["freight_term"]
def test_인코텀즈를_못_풀면_확인_필요():
    docs = [doc("commercial_invoice", incoterms=text("AS PER CONTRACT")), doc("bill_of_lading", freight_term=text("FREIGHT PREPAID"))]
    [issue] = only(docs, "X-FRT-01")
    assert "상업송장 인코텀즈를 풀 수 없음" in issue.evidence
def test_운임이_흐리면_이유를_적고_확인_필요():
    docs = [doc("commercial_invoice", incoterms=text("FOB")), doc("bill_of_lading", freight_term=Cell(unreadable="흐림"))]
    [issue] = only(docs, "X-FRT-01")
    assert "선하증권 운임 조건 흐림" in issue.evidence
def test_운임_칸이나_서류가_없으면_건너뜀():
    inv = doc("commercial_invoice", incoterms=text("FOB"))
    assert only([inv, doc("bill_of_lading", freight_term=Cell(unreadable="칸 없음"))], "X-FRT-01") == []
    assert only([inv, doc("bill_of_lading")], "X-FRT-01") == []
    assert only([inv], "X-FRT-01") == []
    assert only([doc("bill_of_lading", freight_term=text("FREIGHT PREPAID"))], "X-FRT-01") == []
def test_제조품에_WO를_적으면_확인_필요():
    [issue] = only([co(items=[co_item(1, "WO", "6404.11")])], "X-OC-01")
    assert issue.grade == "확인 필요"
    assert [c.field for c in issue.cells] == ["items[0].origin_criterion", "items[0].hs_code"]
    assert issue.evidence == "원산지증명서 원산지결정기준을 확인해 주세요(1행 원산지결정기준이 WO(완전생산)인데 HS 6404.11는 제64류 제조품)."
@pytest.mark.parametrize("hs", ["0306.17", "0801.32", "0901.11", "2709.00"])
def test_농수산물과_광물의_WO는_문제_없음(hs):
    assert only([co(items=[co_item(1, "WO", hs)])], "X-OC-01") == []
def test_WO가_아닌_기준은_제조품이어도_문제_없음():
    assert only([co(items=[co_item(1, "PSR", "6404.11"), co_item(2, "RVC 40%", "8541.43")])], "X-OC-01") == []
def test_원산지기준은_소문자_공백도_WO로_본다_행마다_따로_짚는다():
    items = [co_item(1, "PSR", "6404.11"), co_item(2, " wo ", "6908.90")]
    [issue] = only([co(items=items)], "X-OC-01")
    assert [c.field for c in issue.cells] == ["items[1].origin_criterion", "items[1].hs_code"]
    assert "2행" in issue.evidence
def test_HS를_못_읽은_행은_WO여도_판단하지_않는다():
    item = ExtractedItem(line=1, origin_criterion=text("WO"), hs_code=Cell(unreadable="흐림"))
    assert only([co(items=[item])], "X-OC-01") == []
def test_기한을_넘겨_발급하고_소급_표시가_없으면_확인_필요():
    [issue] = only([co(departure="2026-10-21", issued="2026-11-10")], "X-RETRO-01")  # 출항 수요일 + 7근무일 = 10-30
    assert issue.grade == "확인 필요"
    assert [c.field for c in issue.cells] == ["issue_date", "departure_date"]
    assert issue.evidence == (
        "원산지증명서 발급 기한을 확인해 주세요"
        "(발급일 2026-11-10이 출항일 2026-10-21 뒤 7근무일(2026-10-30) 기한을 넘었는데 소급 발급 표시가 없음)."
    )
def test_기한_마지막_날_발급은_문제_없음():
    assert only([co(departure="2026-10-21", issued="2026-10-30")], "X-RETRO-01") == []
def test_기한_다음_날_발급은_확인_필요():
    assert len(only([co(departure="2026-10-21", issued="2026-10-31")], "X-RETRO-01")) == 1
def test_주말은_근무일에_넣지_않는다():
    """금요일 10-23 출항: 월 26·화 27·수 28·목 29·금 30·월 11-02·화 11-03이 7근무일이다 (주말 둘을 건너뛴다)."""
    assert only([co(departure="2026-10-23", issued="2026-11-03")], "X-RETRO-01") == []
    assert len(only([co(departure="2026-10-23", issued="2026-11-04")], "X-RETRO-01")) == 1
def test_소급_표시가_있으면_늦게_발급해도_문제_없음():
    assert only([co(departure="2026-10-21", issued="2026-11-10", retro="ISSUED RETROACTIVELY")], "X-RETRO-01") == []
def test_출항_전에_발급해도_문제_없음():
    assert only([co(departure="2026-11-13", issued="2026-11-11")], "X-RETRO-01") == []
def test_발급일을_날짜로_못_풀면_확인_필요():
    [issue] = only([co(issued="NOV. 10")], "X-RETRO-01")
    assert issue.grade == "확인 필요" and "발급일을 날짜로 풀 수 없음" in issue.evidence
    assert [c.field for c in issue.cells] == ["issue_date"]
def test_날짜_칸이_없으면_건너뜀():
    assert only([co(departure=None)], "X-RETRO-01") == []
    assert only([co(issued=None)], "X-RETRO-01") == []
def test_발급_기한_규칙은_원산지증명서만_본다():
    other = doc("commercial_invoice", departure_date=date_cell("2026-10-21"), issue_date=date_cell("2026-11-10"))
    assert only([other], "X-RETRO-01") == []