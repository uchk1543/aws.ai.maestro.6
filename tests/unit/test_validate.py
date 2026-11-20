"""cross_check(X-WT-01 총중량) 단위 테스트. 가짜 추출 결과를 쓴다."""

from tools.models import Cell, ExtractedDocument, ExtractedItem
from tools.validate import cross_check


def weight(docs):
    """총중량 규칙(X-WT-01)의 결과만 본다. 다른 칸은 이 테스트에서 채우지 않는다."""
    return [i for i in cross_check(docs) if i.rule_id == "X-WT-01"]


def doc(doc_type, total_raw=None, total=None, items=None, unreadable=None):
    total_cell = None
    if total_raw is not None or unreadable is not None:
        total_cell = Cell(raw=total_raw, value=total, unreadable=unreadable)
    return ExtractedDocument(
        doc_type=doc_type,
        file=f"uploads/s/{doc_type}.pdf",
        items=items or [],
        total_gross_kg=total_cell,
    )


def test_match_gives_no_issue():
    docs = [doc("commercial_invoice", "6,520.00 KGS", 6520.0), doc("packing_list", "6,520 KG", 6520.0)]
    assert weight(docs) == []


def test_mismatch_two_docs():
    docs = [doc("commercial_invoice", "6,250.00 KGS", 6250.0), doc("packing_list", "6,520.00 KGS", 6520.0)]
    [issue] = weight(docs)
    assert issue.rule_id == "X-WT-01" and issue.grade == "불일치"
    assert issue.suspect is None
    assert issue.evidence == "상업송장 총중량 6,250kg과 포장명세서 6,520kg이 다릅니다."
    assert [(c.doc, c.raw) for c in issue.cells] == [
        ("commercial_invoice", "6,250.00 KGS"),
        ("packing_list", "6,520.00 KGS"),
    ]


def test_unreadable_is_not_counted_as_match():
    docs = [doc("commercial_invoice", "6,520.00 KGS", 6520.0), doc("packing_list", unreadable="흐림")]
    [issue] = weight(docs)
    assert issue.grade == "확인 필요"
    assert issue.cells[0].doc == "packing_list"
    assert issue.evidence == "포장명세서 총중량을 읽지 못했습니다(흐림)."


def test_within_tolerance_is_note():
    docs = [doc("commercial_invoice", "6,520.00", 6520.0), doc("packing_list", "6,520.05", 6520.05)]
    [issue] = weight(docs)
    assert issue.grade == "참고"


def test_majority_picks_suspect_with_three_docs():
    docs = [
        doc("commercial_invoice", "6,250", 6250.0),
        doc("bill_of_lading", "6,250", 6250.0),
        doc("packing_list", "6,520", 6520.0),
    ]
    [issue] = weight(docs)
    assert issue.grade == "불일치" and issue.suspect == "packing_list"
    assert issue.evidence == "포장명세서 총중량 6,520kg과 상업송장·선하증권 6,250kg이 다릅니다."


def test_item_sum_used_when_no_total_cell():
    items = [
        ExtractedItem(line=1, gross_kg=Cell(raw="3,000 KGS", value=3000.0)),
        ExtractedItem(line=2, gross_kg=Cell(raw="3,520 KGS", value=3520.0)),
    ]
    docs = [doc("commercial_invoice", "6,520", 6520.0), doc("packing_list", items=items)]
    assert weight(docs) == []


def test_item_row_unreadable_means_check_needed():
    items = [
        ExtractedItem(line=1, gross_kg=Cell(raw="3,000 KGS", value=3000.0)),
        ExtractedItem(line=2, gross_kg=Cell(raw=None, value=None, unreadable="가려짐")),
    ]
    docs = [doc("commercial_invoice", "6,520", 6520.0), doc("packing_list", items=items)]
    [issue] = weight(docs)
    assert issue.grade == "확인 필요"
    assert issue.evidence == "포장명세서 총중량을 읽지 못했습니다(가려짐)."
    assert issue.cells[0].field == "items[1].gross_kg"


def test_single_doc_has_nothing_to_compare():
    assert weight([doc("packing_list", "6,520", 6520.0)]) == []


# ---------------------------------------------------------------------------
# X-QTY-01 총수량, X-INV-01 송장 번호, 정규화 (B7)
# ---------------------------------------------------------------------------
def qdoc(doc_type, qty_raw=None, qty=None, no=None, no_unreadable=None, items=None, qty_unreadable=None):
    """총수량과 송장 번호만 채운 가짜 추출 결과."""
    qty_cell = None
    if qty_raw is not None or qty_unreadable is not None:
        qty_cell = Cell(raw=qty_raw, value=qty, unreadable=qty_unreadable)
    no_cell = None
    if no is not None or no_unreadable is not None:
        no_cell = Cell(raw=no, value=no.strip() if no else None, unreadable=no_unreadable)
    return ExtractedDocument(
        doc_type=doc_type, file=f"uploads/s/{doc_type}.pdf", items=items or [], total_qty=qty_cell, doc_no=no_cell
    )


def only(issues, rule_id):
    return [i for i in issues if i.rule_id == rule_id]


def test_qty_match_gives_no_issue():
    docs = [qdoc("commercial_invoice", "2,650 PCS", 2650), qdoc("packing_list", "2650 PCS", 2650)]
    assert only(cross_check(docs), "X-QTY-01") == []


def test_qty_digit_swap_is_mismatch():
    docs = [qdoc("commercial_invoice", "3,450 PCS", 3450), qdoc("packing_list", "4,350 PCS", 4350)]
    [issue] = only(cross_check(docs), "X-QTY-01")
    assert issue.grade == "불일치"
    assert issue.evidence == "상업송장 총수량 3,450과 포장명세서 4,350이 다릅니다."
    assert [c.field for c in issue.cells] == ["total_qty", "total_qty"]


def test_qty_one_carton_difference_is_mismatch():
    docs = [qdoc("commercial_invoice", "13,560 PCS", 13560), qdoc("packing_list", "13,500 PCS", 13500)]
    [issue] = only(cross_check(docs), "X-QTY-01")
    assert issue.grade == "불일치"


def test_qty_unreadable_is_check_needed():
    docs = [qdoc("commercial_invoice", "2,650 PCS", 2650), qdoc("packing_list", qty_unreadable="가려짐")]
    [issue] = only(cross_check(docs), "X-QTY-01")
    assert issue.grade == "확인 필요"
    assert issue.evidence == "포장명세서 총수량을 읽지 못했습니다(가려짐)."


def test_qty_unit_spelling_only_is_note():
    docs = [qdoc("commercial_invoice", "500 CTNS", 500), qdoc("packing_list", "500 CARTONS", 500)]
    [issue] = only(cross_check(docs), "X-QTY-01")
    assert issue.grade == "참고"
    assert issue.evidence == "상업송장 총수량 500 CTNS과 포장명세서 500 CARTONS은 단위 표기만 다릅니다."


def test_qty_same_unit_spelling_gives_no_note():
    docs = [qdoc("commercial_invoice", "500 CTNS", 500), qdoc("packing_list", "500 CTNS", 500)]
    assert only(cross_check(docs), "X-QTY-01") == []


def test_qty_sums_item_rows_when_no_total():
    items = [
        ExtractedItem(line=1, qty=Cell(raw="1,000 PCS", value=1000)),
        ExtractedItem(line=2, qty=Cell(raw="1,650 PCS", value=1650)),
    ]
    docs = [qdoc("commercial_invoice", items=items), qdoc("packing_list", "2,650 PCS", 2650)]
    assert only(cross_check(docs), "X-QTY-01") == []


def test_invoice_no_match_gives_no_issue():
    docs = [qdoc("commercial_invoice", no="QDT/26/0289"), qdoc("packing_list", no="QDT/26/0289")]
    assert only(cross_check(docs), "X-INV-01") == []


def test_invoice_no_char_swap_is_mismatch():
    # 정답지 D001: 포장명세서 끝 번호 두 자리가 바뀜
    docs = [qdoc("commercial_invoice", no="QDT/26/0289"), qdoc("packing_list", no="QDT/26/0829")]
    [issue] = only(cross_check(docs), "X-INV-01")
    assert issue.grade == "불일치"
    assert issue.evidence == "상업송장 송장 번호 QDT/26/0289과 포장명세서 QDT/26/0829이 다릅니다."
    assert [c.field for c in issue.cells] == ["doc_no", "doc_no"]


def test_invoice_no_digit_typo_is_mismatch():
    # 정답지 D009: 끝 한 자리 오타
    docs = [qdoc("commercial_invoice", no="HSF-26-0283"), qdoc("packing_list", no="HSF-26-0285")]
    [issue] = only(cross_check(docs), "X-INV-01")
    assert issue.grade == "불일치"


def test_invoice_no_separator_only_is_note_not_mismatch():
    # 정답지 D020: 같은 번호를 구분 기호만 다르게 적음. 오탐이면 안 된다
    docs = [qdoc("commercial_invoice", no="QDT/26/0279"), qdoc("packing_list", no="QDT26/0279")]
    [issue] = only(cross_check(docs), "X-INV-01")
    assert issue.grade == "참고"
    assert issue.evidence == "상업송장 송장 번호 QDT/26/0279과 포장명세서 QDT26/0279은 구분 기호만 다릅니다."


def test_invoice_no_case_and_space_only_is_note():
    docs = [qdoc("commercial_invoice", no="SHE-2026-0214"), qdoc("packing_list", no="she-2026 0214")]
    [issue] = only(cross_check(docs), "X-INV-01")
    assert issue.grade == "참고"


def test_invoice_no_missing_is_check_needed():
    docs = [qdoc("commercial_invoice", no="QDT/26/0289"), qdoc("packing_list")]
    [issue] = only(cross_check(docs), "X-INV-01")
    assert issue.grade == "확인 필요"
    assert issue.evidence == "포장명세서 송장 번호를 읽지 못했습니다(칸 없음)."


def test_invoice_no_unreadable_reason_is_kept():
    docs = [qdoc("commercial_invoice", no="QDT/26/0289"), qdoc("packing_list", no_unreadable="흐림")]
    [issue] = only(cross_check(docs), "X-INV-01")
    assert issue.grade == "확인 필요" and "흐림" in issue.evidence


def test_p0_rules_report_independently():
    # 한 세트에서 세 칸이 모두 틀리면 규칙마다 따로 하나씩 나온다
    docs = [
        qdoc("commercial_invoice", "3,450 PCS", 3450, no="A-1"),
        qdoc("packing_list", "4,350 PCS", 4350, no="A-2"),
    ]
    docs[0] = docs[0].model_copy(update={"total_gross_kg": Cell(raw="100 KGS", value=100.0)})
    docs[1] = docs[1].model_copy(update={"total_gross_kg": Cell(raw="200 KGS", value=200.0)})
    issues = cross_check(docs)
    assert sorted(i.rule_id for i in issues) == ["X-INV-01", "X-QTY-01", "X-WT-01"]
    assert {i.grade for i in issues} == {"불일치"}


def test_invoice_no_not_compared_with_bill_of_lading():
    # X-INV-01 대상은 상업송장·포장명세서. B/L 번호와 비교하지 않는다
    docs = [
        qdoc("commercial_invoice", no="QDT/26/0289"),
        qdoc("packing_list", no="QDT/26/0289"),
        qdoc("bill_of_lading", no="MSKU123456"),
    ]
    assert only(cross_check(docs), "X-INV-01") == []


def test_normalize_unit_aliases():
    from tools.validate import normalize_unit

    assert {normalize_unit(a) for a in ("CTNS", "ctn", "Carton", "CARTONS", "박스")} == {"CTN"}
    assert normalize_unit("PCS") == normalize_unit("ea") == "EA"
    assert normalize_unit("KGS") == "KG" and normalize_unit("LBS") == "LB"
    assert normalize_unit("UNKNOWN") == "UNKNOWN"  # 표에 없으면 대문자만 맞춘다


def test_normalize_text_rules():
    from tools.validate import normalize_text

    assert normalize_text("invoice_no", "QDT/26/0279") == normalize_text("invoice_no", "qdt26 0279") == "QDT260279"
    assert normalize_text("name", "  Hex  BOLT, M10x50 ") == "hex bolt m10x50"
    assert normalize_text("name", "CO., LTD.") == normalize_text("name", "CO.,LTD") == "co ltd"
