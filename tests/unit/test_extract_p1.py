"""B2 P1 읽기 단위 테스트: 남은 칸, B/L·원산지증명서 종류별 Raw 모델, 날짜·금액 풀기. 모델은 가짜 (Bedrock 호출 없음)."""

import pytest

from tools import extract
from tools.declaration import draft_declaration
from tools.extract import parse_date, read_document, system_prompt, to_extracted
from tools.models import (
    RAW_MODELS, RAW_REQUIRED_NEW, SITE_FIELDS, RawBillOfLading, RawDocument, RawItem, RawOrigin,
)


def cell(raw):
    return {"raw": raw} if raw is not None else {"raw": None, "unreadable": "칸 없음"}


BL = {
    "doc_no": cell("SMLNSGN26012216"), "shipper_name": cell("BINH DUONG EXAMPLE FURNITURE JSC"),
    "consignee_name": cell("EXAMPLE HOME LIVING CO., LTD."), "notify_name": cell("SAME AS CONSIGNEE"),
    "vessel_voyage": cell("EXAMPLE VOYAGER 236N"), "port_loading": cell("HO CHI MINH CITY, VIETNAM"),
    "port_discharge": cell("BUSAN, KOREA"), "onboard_date": cell("25 OCT 2026"),
    "container_no": cell("SMCU8393918 SMCU2669249"), "freight_term": cell("FREIGHT PREPAID"),
    "total_packages": cell("535 CARTONS"), "total_gross_kg": cell("7,914.600"), "total_cbm": cell("63.610"),
}
CO = {
    "doc_no": cell("BDF-2026-259"), "co_no": cell("VN-KR 26/04/02422"),
    "exporter_name": cell("BINH DUONG EXAMPLE FURNITURE JSC"), "consignee_name": cell("SAMPLE TRADING KOREA CO., LTD."),
    "departure_date": cell("10/11/2026"), "invoice_date": cell("04/11/2026"), "issue_date": cell("NOV. 12, 2026"),
    "issued_retroactively": cell(None),
    "items": [{"line": 1, "name": cell("WOODEN DINING CHAIR"), "hs_code": cell("HS CODE: 9401.69"),
               "qty": cell("351 PCS"), "origin_criterion": cell("RVC 40%")}],
}
INV = {
    "doc_no": cell("BDF-2026-259"), "exporter_name": cell("BINH DUONG EXAMPLE FURNITURE JSC"),
    "consignee_name": cell("SAMPLE TRADING KOREA CO., LTD."), "incoterms": cell("FOB HO CHI MINH CITY"),
    "payment_term": cell("T/T 30 DAYS"), "origin": cell("VIETNAM"),
    "items": [{"line": 1, "name": cell("WOODEN DINING CHAIR"), "hs_code": cell("9401.69"), "qty": cell("351 PCS"),
               "unit_price": cell("USD 28.00"), "amount": cell("USD 9,828.00"), "gross_kg": cell("2,352.60")}],
    "total_qty": cell("351 PCS"), "total_gross_kg": cell("2,352.60 KGS"), "total_amount": cell("USD 9,828.00"),
}
PL = {
    "doc_no": cell("BDF-2026-259"), "exporter_name": cell("BINH DUONG EXAMPLE FURNITURE JSC"),
    "consignee_name": cell("SAMPLE TRADING KOREA CO., LTD."), "total_packages": cell("SAY TOTAL 176 CARTONS ONLY"),
    "items": [{"line": 1, "name": cell("WOODEN DINING CHAIR"), "qty": cell("351 PCS"), "gross_kg": cell("2,352.60"),
               "net_kg": cell("2,100.00")}],
    "total_qty": cell("351 PCS"), "total_gross_kg": cell("2,352.60 KGS"),
}


def test_bill_of_lading_cells_and_values():
    doc = to_extracted(RawBillOfLading.model_validate(BL), "bill_of_lading", "uploads/s/bl.pdf")
    assert doc.doc_no.value == "SMLNSGN26012216" and doc.shipper_name.value == "BINH DUONG EXAMPLE FURNITURE JSC"
    assert doc.consignee_name.value == "EXAMPLE HOME LIVING CO., LTD."  # #133과 같은 칸
    assert doc.onboard_date.value == "2026-10-25" and doc.onboard_date.raw == "25 OCT 2026"
    assert (doc.total_packages.value, doc.total_packages.unit) == (535, "CTN")
    assert doc.total_gross_kg.value == 7914.6 and doc.total_cbm.value == 63.61
    assert doc.items == []


def test_origin_dates_are_day_first_and_items_keep_criterion():
    doc = to_extracted(RawOrigin.model_validate(CO), "certificate_of_origin", "uploads/s/co.pdf")
    assert doc.departure_date.value == "2026-11-10" and doc.invoice_date.value == "2026-11-04"
    assert doc.issue_date.value == "2026-11-12"
    assert doc.issued_retroactively.raw is None and doc.issued_retroactively.unreadable == "칸 없음"
    [item] = doc.items
    assert item.hs_code.value == "940169" and item.origin_criterion.value == "RVC 40%"
    assert doc.doc_no.value == "BDF-2026-259"  # 원산지증명서의 doc_no는 송장 번호


def test_invoice_new_cells_keep_currency_and_old_cells_unchanged():
    doc = to_extracted(RawDocument.model_validate(INV), "commercial_invoice", "uploads/s/inv.pdf")
    assert (doc.total_amount.value, doc.total_amount.unit) == (9828.0, "USD")
    item = doc.items[0]
    assert (item.unit_price.value, item.unit_price.unit) == (28.0, "USD") and item.amount.value == 9828.0
    assert doc.incoterms.value == "FOB HO CHI MINH CITY" and doc.origin.value == "VIETNAM"
    assert doc.total_gross_kg.value == 2352.6 and doc.total_qty.value == 351 and doc.doc_no.value == "BDF-2026-259"


def test_old_fake_answers_without_new_cells_still_validate():
    """다른 담당의 가짜 응답(새 칸 없음)도 그대로 검증된다. 새 칸은 None."""
    doc = to_extracted(RawDocument.model_validate({"doc_no": cell("INV-1"), "items": [{"line": 1}]}), "packing_list", "x.pdf")
    assert doc.total_packages is None and doc.items[0].unit_price is None


@pytest.mark.parametrize("raw,expected", [
    ("25 OCT 2026", "2026-10-25"), ("OCT. 25, 2026", "2026-10-25"), ("2026-11-02", "2026-11-02"),
    ("10/11/2026", "2026-11-10"), ("10.11.2026", "2026-11-10"), ("SHIPPED ON BOARD: 02-NOV-2026", "2026-11-02"),
    ("31/02/2026", None), ("SAME AS ABOVE", None),
])
def test_parse_date(raw, expected):
    assert parse_date(raw) == expected


def test_new_cells_are_required_nullable_in_model_schemas():
    """Bedrock 구조화 출력의 선택 속성 한도(12개) 때문에 새 칸은 스키마에서 필수(null 허용)다."""
    assert set(RAW_REQUIRED_NEW) <= set(RawDocument.model_json_schema()["required"])
    assert {"unit_price", "amount"} <= set(RawItem.model_json_schema()["required"])
    for doc_type, model in RAW_MODELS.items():
        schema = model.model_json_schema()
        assert set(schema["required"]) == set(schema["properties"]), doc_type
    with pytest.raises(Exception):
        RawBillOfLading.model_validate({"doc_no": cell("X")})  # 칸을 빠뜨린 답은 형식 오류 → 한 번 다시 묻는다


def test_default_reader_uses_type_model(monkeypatch):
    seen = []

    def fake_structured(blocks, prompt, user_text, output_model):
        seen.append(output_model)
        return output_model.model_validate(BL if output_model is RawBillOfLading else INV)

    monkeypatch.setattr(extract, "_strands_structured", fake_structured)
    bl = read_document("uploads/s/bl.pdf", b"%PDF-1.7", "bill_of_lading", no_cache=True)
    inv = read_document("uploads/s/inv.pdf", b"%PDF-1.7", "commercial_invoice", no_cache=True)
    assert seen == [RawBillOfLading, RawDocument]
    assert bl.vessel_voyage.value == "EXAMPLE VOYAGER 236N" and inv.total_amount.value == 9828.0


def test_two_argument_fake_reader_is_still_used_for_every_type(monkeypatch):
    """다른 테스트처럼 _strands_reader를 (blocks, prompt) 가짜로 바꿔 끼우면 B/L도 그 가짜로 읽는다 (Bedrock을 부르지 않는다)."""
    monkeypatch.setattr(extract, "_strands_reader", lambda blocks, prompt: RawDocument.model_validate({"doc_no": cell("BL-1")}))
    doc = read_document("uploads/s/bl.pdf", b"%PDF-1.7", "bill_of_lading", no_cache=True)
    assert doc.doc_no.value == "BL-1"


def test_prompts_have_rules_for_new_cells():
    assert "Booking No." in system_prompt("bill_of_lading") and "Seal No." in system_prompt("bill_of_lading")
    co = system_prompt("certificate_of_origin")
    assert "10번 칸" in co and "co_no" in co and "ISSUED RETROACTIVELY" in co
    assert "incoterms" in system_prompt("commercial_invoice") and "total_packages" in system_prompt("packing_list")


def test_declaration_draft_fills_sources_that_were_missing():
    """칸이 생기면 신고서 초안(2번 tools/declaration.py)이 고치지 않아도 그 칸을 채운다."""
    docs = [
        to_extracted(RawDocument.model_validate(INV), "commercial_invoice", "inv.pdf"),
        to_extracted(RawDocument.model_validate(PL), "packing_list", "pl.pdf"),
        to_extracted(RawBillOfLading.model_validate(BL), "bill_of_lading", "bl.pdf"),
        to_extracted(RawOrigin.model_validate(CO), "certificate_of_origin", "co.pdf"),
    ]
    filled = {f.name: f.value for f in draft_declaration(docs, [], []).fields}
    assert filled["선기명"] == "EXAMPLE VOYAGER 236N" and filled["적출국"] == "HO CHI MINH CITY, VIETNAM"
    assert filled["수입자"] == "SAMPLE TRADING KOREA CO., LTD." and filled["해외공급자"] == "BINH DUONG EXAMPLE FURNITURE JSC"
    assert filled["인도조건"] == "FOB HO CHI MINH CITY" and filled["결제금액"] == 9828.0 and filled["결제방법"] == "T/T 30 DAYS"
    assert filled["총포장갯수"] == 176 and filled["단가"] == 28.0 and filled["금액"] == 9828.0
    assert filled["원산지"] == "VIETNAM" and filled["원산지결정기준"] == "RVC 40%"


# ---------------------------------------------------------------------------
# 현장 칸: 화인·컨테이너 줄·품목별 포장 수 (B12 #228)
# ---------------------------------------------------------------------------
def _optional_count(node) -> int:
    """JSON 스키마에서 필수가 아닌 속성 수 (Bedrock 구조화 출력 한도 12개)."""
    if isinstance(node, list):
        return sum(_optional_count(v) for v in node)
    if not isinstance(node, dict):
        return 0
    own = len(set(node.get("properties", {})) - set(node.get("required", [])))
    return own + sum(_optional_count(v) for v in node.values())


def test_현장_칸도_선택_속성_한도_안():
    for model in (RawDocument, RawBillOfLading):
        assert _optional_count(model.model_json_schema()) <= 12
    assert "marks" in RawDocument.model_json_schema()["required"]
    assert {"marks", "containers"} <= set(RawBillOfLading.model_json_schema()["required"])


def test_새_칸_없는_옛_응답도_받는다():
    raw = RawDocument.model_validate({"doc_no": {"raw": "X"}, "items": [{"line": 1, "qty": {"raw": "1 PCS"}}]})
    assert raw.marks is None and raw.items[0].packages is None


def test_현장_칸_목록():
    assert "containers.seal_no" in SITE_FIELDS["bill_of_lading"]
    assert "items.packages" in SITE_FIELDS["packing_list"]
    assert "total_amount" not in SITE_FIELDS["commercial_invoice"]  # 관리자만
    assert SITE_FIELDS["certificate_of_origin"] == frozenset()


BL_SITE = {
    **BL, "marks": cell("EXAMPLE HOME LIVING\nBUSAN, KOREA C/NO. 1-535"),
    "containers": [
        {"line": 1, "container_no": cell("SMCU8393918"), "seal_no": cell("SM1470293"), "size_type": cell("40'HC (45G1)"),
         "packages": cell("300 CTNS"), "gross_kg": cell("4,400.000 KGS"), "cbm": cell("35.000 CBM")},
        {"line": 2, "container_no": cell("SMCU2669249"), "seal_no": cell("SM1470294"), "size_type": cell("40'HC (45G1)"),
         "packages": cell("235 CTNS"), "gross_kg": cell("3,514.600 KGS"), "cbm": cell("28.610 CBM")},
    ],
}


def test_컨테이너_줄이_여럿이면_줄마다_푼다():
    doc = to_extracted(RawBillOfLading.model_validate(BL_SITE), "bill_of_lading", "bl.pdf")
    assert [c.line for c in doc.containers] == [1, 2]
    c = doc.containers[1]
    assert (c.seal_no.value, c.packages.value, c.packages.unit, c.gross_kg.value, c.cbm.value) == (
        "SM1470294", 235, "CTN", 3514.6, 28.61,
    )
    assert doc.container_no.raw == "SMCU8393918 SMCU2669249"  # 기존 칸 그대로


def test_화인은_대문자_공백_하나로_푼다():
    doc = to_extracted(RawBillOfLading.model_validate(BL_SITE), "bill_of_lading", "bl.pdf")
    assert doc.marks.raw == "EXAMPLE HOME LIVING\nBUSAN, KOREA C/NO. 1-535"
    assert doc.marks.value == "EXAMPLE HOME LIVING BUSAN, KOREA C/NO. 1-535"


def test_포장명세서_품목별_포장_수():
    raw = {**PL, "items": [{**PL["items"][0], "packages": cell("286")}]}
    doc = to_extracted(RawDocument.model_validate(raw), "packing_list", "pl.pdf")
    assert doc.items[0].packages.value == 286


def test_지시문에_현장_칸_설명이_있다():
    assert "CONTAINER DETAILS" in system_prompt("bill_of_lading") and "봉인 번호" in system_prompt("bill_of_lading")
    assert "packages" in system_prompt("packing_list") and "marks" in system_prompt("packing_list")
