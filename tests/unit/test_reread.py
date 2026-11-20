"""reread_field·apply_rereads 단위 테스트. PDF 글자 뽑기와 모델은 가짜로 대신한다 (Bedrock·AWS 호출 없음)."""

import pytest

from tools.models import ExtractedDocument, Issue, IssueCell, OcrLine, OcrResult, RawDocument, RereadResult
from tools.reread import apply_rereads, field_raw, find_in_text, reread_field


def doc(file="uploads/s1/pl.pdf", **cells) -> ExtractedDocument:
    base = {"doc_type": "packing_list", "file": file, "items": [
        {"line": 1, "gross_kg": {"raw": "4,000.00 KGS"}}, {"line": 2, "gross_kg": {"raw": "2,520.00 KGS"}}]}
    return ExtractedDocument.model_validate({**base, **cells})


PL = doc(total_gross_kg={"raw": "6,520.00 KGS", "value": 6520.0}, doc_no={"raw": "QDT/26/0289"})
PDF_TEXT = "PACKING LIST\nNo. & Date of Invoice\nQDT/26/0289   OCT. 24, 2026\nTOTAL : 6,520.00\nKGS\n4,000.00 2,520.00"


def test_field_raw_paths():
    assert field_raw(PL, "total_gross_kg") == "6,520.00 KGS"
    assert field_raw(PL, "items[1].gross_kg") == "2,520.00 KGS"
    assert field_raw(PL, "items[*].gross_kg") == "4,000.00 KGS + 2,520.00 KGS"
    assert field_raw(PL, "items[5].gross_kg") is None and field_raw(PL, "total_qty") is None
    with pytest.raises(ValueError):
        field_raw(PL, "items[0]..gross")


def test_find_in_text_ignores_spacing_and_needs_every_part():
    assert find_in_text("6,520.00 KGS", PDF_TEXT) == "6,520.00 KGS"  # 줄바꿈으로 갈라져도 찾음
    assert find_in_text("TOTAL: 6,520.00", "TOTAL 6,520.00 KGS") == "6,520.00"  # 앞 글자가 달라도 숫자는 그대로 있음
    assert find_in_text("6,250.00 KGS", PDF_TEXT) is None  # 자리 바뀐 판독은 문서에 없다
    assert find_in_text("4,000.00 KGS + 2,520.00 KGS", PDF_TEXT) == "4,000.00 + 2,520.00"
    assert find_in_text("4,000.00 KGS + 9,999.00 KGS", PDF_TEXT) is None
    assert find_in_text("6,520.00", "") is None


def test_find_in_text_needs_number_boundary():  # #120
    assert find_in_text("241.4 kg", "Total 1241.40") is None  # 앞뒤로 더 긴 숫자
    assert find_in_text("6,520.00", "TOTAL 16,520.00 KGS") is None  # 앞에 숫자가 더 있음
    assert find_in_text("6,520.00 KGS", "TOTAL 16,520.00 KGS") is None  # raw 전체 비교도 같다
    assert find_in_text("241.4 kg", "Total 241.4 KG") == "241.4 kg"


def test_find_in_text_keeps_adjacent_columns():  # 옆 칸 숫자와 붙어 있어도 경계는 띄어쓰기로 본다
    assert find_in_text("2,520.00 KGS", "4,000.00 2,520.00") == "2,520.00"
    assert find_in_text("6,520.00 KGS", "TOTAL 6,520.\n00 KGS") == "6,520.00 KGS"  # 줄바꿈으로 갈라진 칸


def test_text_pdf_uses_pdf_text_without_model():
    def no_model(blocks, prompt):
        raise AssertionError("텍스트 PDF에서 모델을 부름")

    r = reread_field(PL, "total_gross_kg", b"%PDF", reader=no_model, pdf_text=lambda data: PDF_TEXT)
    assert (r.checked_by, r.same, r.second_raw, r.first_raw) == ("pdf_text", True, "6,520.00 KGS", "6,520.00 KGS")
    misread = doc(total_gross_kg={"raw": "6,250.00 KGS"})
    r = reread_field(misread, "total_gross_kg", b"%PDF", reader=no_model, pdf_text=lambda data: PDF_TEXT)
    assert (r.checked_by, r.same, r.second_raw) == ("pdf_text", False, None)


def test_scan_pdf_falls_to_textract_then_model():
    ocr = OcrResult(file="uploads/s1/pl.pdf", lines=[OcrLine(page=1, text="TOTAL 6,520.00 KGS", bbox=(0, 0, 1, 1))])
    r = reread_field(PL, "total_gross_kg", b"%PDF", ocr=ocr, pdf_text=lambda data: "  ")
    assert (r.checked_by, r.same) == ("textract", True)

    calls = []

    def reader(blocks, prompt):
        calls.append(prompt)
        return RawDocument.model_validate({"total_gross_kg": {"raw": "6,520.00 KGS"}})

    r = reread_field(PL, "total_gross_kg", b"%PDF", reader=reader, pdf_text=lambda data: "")
    assert (r.checked_by, r.same, r.second_raw) == ("model_reread", True, "6,520.00 KGS")
    assert len(calls) == 2 and "total_gross_kg 칸 하나만" in calls[0]


def test_model_reread_differs_or_unstable():
    answers = iter(["6,520.00 KGS", "6,250.00 KGS"])
    r = reread_field(doc(file="uploads/s1/pl.png", total_gross_kg={"raw": "6,520.00 KGS"}), "total_gross_kg", b"png",
                     reader=lambda b, p: RawDocument.model_validate({"total_gross_kg": {"raw": next(answers)}}))
    assert (r.checked_by, r.same) == ("model_reread", False)


def test_unread_first_raw_is_not_reread():
    r = reread_field(doc(), "total_qty", b"%PDF", pdf_text=lambda data: PDF_TEXT)
    assert (r.checked_by, r.same, r.first_raw) == ("none", False, None)


MISMATCH = Issue(
    rule_id="X-WT-01", grade="불일치",
    cells=[IssueCell(doc="commercial_invoice", field="total_gross_kg", raw="6,250.00 KGS"),
           IssueCell(doc="packing_list", field="total_gross_kg", raw="6,520.00 KGS")],
    evidence="상업송장 총중량 6,250kg과 포장명세서 6,520kg이 다릅니다.",
)
NOTE = MISMATCH.model_copy(update={"grade": "참고"})


def rr(doc_type, same=True, by="pdf_text", second="x"):
    return RereadResult(doc=doc_type, field="total_gross_kg", first_raw="x", second_raw=second, checked_by=by, same=same)


def test_apply_confirms_when_both_same_with_weakest_method():
    [issue] = apply_rereads([MISMATCH], [rr("commercial_invoice"), rr("packing_list", by="model_reread")])
    assert (issue.grade, issue.checked_by, issue.evidence) == ("불일치", "model_reread", MISMATCH.evidence)


def test_apply_downgrades_when_a_reread_differs():
    [issue] = apply_rereads([MISMATCH], [rr("commercial_invoice"), rr("packing_list", same=False, second=None)])
    assert (issue.grade, issue.checked_by) == ("확인 필요", "pdf_text")
    assert "읽기 오류일 수 있습니다" in issue.evidence and "찾지 못함" in issue.evidence


def test_apply_leaves_partial_or_other_grades():
    assert apply_rereads([MISMATCH], [rr("commercial_invoice")]) == [MISMATCH]  # 한 칸만 확인
    assert apply_rereads([MISMATCH], [rr("commercial_invoice"), rr("packing_list", by="none", same=False)]) == [MISMATCH]
    assert apply_rereads([NOTE], [rr("commercial_invoice"), rr("packing_list")]) == [NOTE]
    once = apply_rereads([MISMATCH], [rr("commercial_invoice"), rr("packing_list")])
    assert apply_rereads(once, [rr("commercial_invoice"), rr("packing_list")]) == once  # 다시 불러도 같음


def test_same_value_ignores_labels_but_not_numbers_or_units():
    from tools.reread import same_value

    # 실제로 나온 경우 (D006 스캔본): 첫 판독은 칸 이름까지, 다시 읽기는 값만
    assert same_value("total_gross_kg", "Total Gross Weight: 241.40 kg", "241.40 kg")
    assert same_value("total_gross_kg", "6,520.00 KGS", "6,520.00 KG")
    assert not same_value("total_gross_kg", "6,520.00 KGS", "6,250.00 KGS")
    assert not same_value("total_gross_kg", "1,947.12 kg", "1,947.12 LBS")
    assert same_value("items[*].gross_kg", "4,000 KGS + 2,520 KGS", "4,000 + 2,520")
    assert same_value("doc_no", "Invoice No.: QDT/26/0289", "QDT/26/0289")
    assert not same_value("doc_no", "QDT/26/0289", "QDT/26/0829")
    assert not same_value("doc_no", None, "QDT/26/0289")
