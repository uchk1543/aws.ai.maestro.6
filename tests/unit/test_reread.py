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


# ---------------------------------------------------------------------------
# B11 (#147): 깨진 PDF 글자층 · 빈 OCR · 다른 칸 값
# ---------------------------------------------------------------------------
from pathlib import Path  # noqa: E402

from tools import reread  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
GARBLED = "Ã¤Ã¶ 6ˆ520ˆ00 KGS Ã¤Ã¶ QDTˆ26ˆ0289 ÃÃ¤ 4ˆ000ˆ00"  # 폰트 매핑이 깨진 글자층


def model_answer(raw: str, calls: list):
    def reader(blocks, prompt):
        calls.append(prompt)
        return RawDocument.model_validate({"total_gross_kg": {"raw": raw}})

    return reader


def test_garbled_text_layer_falls_to_model():
    """판독한 다른 칸(송장 번호)이 글자층에 없으면 글자층을 믿지 않고 다음 방법으로 넘어간다."""
    calls: list = []
    r = reread_field(PL, "total_gross_kg", b"%PDF", reader=model_answer("6,520.00 KGS", calls), pdf_text=lambda data: GARBLED)
    assert (r.checked_by, r.same) == ("model_reread", True) and len(calls) == 2


def test_garbled_text_layer_falls_to_textract_when_ocr_exists():
    ocr = OcrResult(file=PL.file, lines=[OcrLine(page=1, text="TOTAL : 6,520.00 KGS", bbox=(0.1, 0.8, 0.3, 0.02))])
    r = reread_field(PL, "total_gross_kg", b"%PDF", ocr=ocr, pdf_text=lambda data: GARBLED)
    assert (r.checked_by, r.second_raw, r.same) == ("textract", "6,520.00 KGS", True)


def test_text_layer_is_trusted_when_nothing_to_compare():
    """다른 칸을 하나도 못 읽었으면 글자층을 판단할 수 없어 지금처럼 쓴다."""
    only_total = doc(total_gross_kg={"raw": "6,520.00 KGS"})
    r = reread_field(only_total, "total_gross_kg", b"%PDF", pdf_text=lambda data: PDF_TEXT)
    assert (r.checked_by, r.same) == ("pdf_text", True)


def test_empty_ocr_goes_to_model_with_log(capsys):
    calls: list = []
    photo = doc(file="uploads/s1/pl.png", total_gross_kg={"raw": "6,520.00 KGS"})
    r = reread_field(photo, "total_gross_kg", b"png", ocr=OcrResult(file=photo.file, lines=[]),
                     reader=model_answer("6,520.00 KGS", calls))
    assert r.checked_by == "model_reread" and len(calls) == 2
    assert "[reread] OCR 글자 없음 → model_reread" in capsys.readouterr().out


NET_THEN_GROSS = "Total Net Weight 6,000.00 KGS  Total Gross Weight 6,250.00 KGS"


def test_value_of_other_field_is_not_the_same():
    """순중량 6,000을 총중량 칸에 옮긴 판독은 문서에 '있어도' 같다고 보지 않는다 (이슈 예시)."""
    assert find_in_text("6,000.00 KGS", NET_THEN_GROSS) == "6,000.00 KGS"  # 칸을 모르면 지금처럼
    assert find_in_text("6,000.00 KGS", NET_THEN_GROSS, field="total_gross_kg") is None
    assert find_in_text("6,250.00 KGS", NET_THEN_GROSS, field="total_gross_kg") == "6,250.00 KGS"
    misread = doc(total_gross_kg={"raw": "6,000.00 KGS"}, doc_no={"raw": "QDT/26/0289"})
    r = reread_field(misread, "total_gross_kg", b"%PDF", pdf_text=lambda data: "Invoice No. QDT/26/0289\n" + NET_THEN_GROSS)
    assert (r.checked_by, r.second_raw, r.same) == ("pdf_text", None, False)


def test_gross_before_net_is_judged_by_the_closer_label():
    text = "Total Gross Weight 6,250.00 KGS  Total Net Weight 6,000.00 KGS"
    assert find_in_text("6,250.00 KGS", text, field="total_gross_kg") == "6,250.00 KGS"
    assert find_in_text("6,000.00 KGS", text, field="total_gross_kg") is None


def test_total_row_without_labels_is_still_found():
    """포장명세서 합계 줄은 머리글이 멀어 이름표가 없다. 맞서는 이름표가 없으면 지금처럼 찾은 것으로 본다."""
    text = ("Quantity Unit Net-Weight Gross Weight Measurement\n351PCS 2,035.80 2,352.60 19.360\n"
            "291PCS 9,312.00 10,330.50 72.750\nTOTAL 642PCS 11,347.80 KGS 12,683.10 92.110")
    assert find_in_text("12,683.10 KGS", text, field="total_gross_kg") == "12,683.10"
    assert find_in_text("642 PCS", text, field="total_qty") == "642 PCS"


def test_packages_are_not_quantity_and_label_in_raw_is_fine():
    text = "Total Packages: 660 CTNS   Total Gross Weight: 57,868.80 KGS"
    assert find_in_text("660", text, field="total_qty") is None  # 포장 개수를 총수량으로 읽음
    assert find_in_text("Total Gross Weight: 57,868.80", text, field="total_gross_kg") == "Total Gross Weight: 57,868.80"


def test_invoice_number_is_not_another_number():
    text = "Invoice No.: INV-2026-001   P.O. No.: PO-7781"
    assert find_in_text("INV-2026-001", text, field="doc_no") == "INV-2026-001"
    assert find_in_text("PO-7781", text, field="doc_no") is None


def test_d003_invoice_total_still_found_in_real_pdf():
    """지금 통과하는 정상 사례: 개발용 D003 상업송장(텍스트 PDF)의 총중량 21,683.10 KGS를 PDF 글자로 찾는다."""
    data = (ROOT / "samples/dev/D003/doc_a.pdf").read_bytes()
    invoice = ExtractedDocument.model_validate({
        "doc_type": "commercial_invoice", "file": "uploads/s1/doc_a.pdf",
        "total_gross_kg": {"raw": "21,683.10 KGS"}, "doc_no": {"raw": reread_doc_no(data)},
    })
    r = reread_field(invoice, "total_gross_kg", data)
    assert (r.checked_by, r.second_raw, r.same) == ("pdf_text", "21,683.10 KGS", True)
    net = invoice.model_copy(update={"total_gross_kg": invoice.total_gross_kg.model_copy(update={"raw": "11,347.80 KGS"})})
    assert reread_field(net, "total_gross_kg", data).same is False  # 순중량을 총중량으로 옮긴 판독


def reread_doc_no(data: bytes) -> str:
    """D003 상업송장의 송장 번호(정답지 eval/fields.csv)."""
    import csv

    rows = csv.DictReader((ROOT / "eval/fields.csv").open(encoding="utf-8"))
    return next(r["answer"] for r in rows if (r["set_id"], r["doc"], r["field"]) == ("D003", "commercial_invoice", "invoice_no"))


def test_label_window_constant():
    assert reread.LABEL_WINDOW == 60
