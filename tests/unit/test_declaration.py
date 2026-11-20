"""C5 draft_declaration 단위 테스트. AWS와 Bedrock을 부르지 않는다. 담당: 검증."""
from tools.declaration import DECLARATION_FIELDS, draft_declaration
from tools.models import Cell, ExtractedDocument, ExtractedItem, HSResult, Issue, IssueCell


def _item(line=1, **cells):
    return ExtractedItem(line=line, **cells)


def _docs(lines=1):
    inv_items = [
        _item(
            i,
            name=Cell(raw=f"Bicycle Tyre {i}", value=f"bicycle tyre {i}"),
            qty=Cell(raw=f"{2650 + i} PCS", value=2650 + i, unit="PCS"),
        )
        for i in range(1, lines + 1)
    ]
    pl_items = [_item(i, net_kg=Cell(raw=f"{795 + i} KGS", value=795.0 + i, unit="KG")) for i in range(1, lines + 1)]
    return [
        ExtractedDocument(doc_type="commercial_invoice", file="a", doc_no=Cell(raw="INV-1", value="inv1"), items=inv_items),
        ExtractedDocument(
            doc_type="packing_list", file="b", items=pl_items, total_gross_kg=Cell(raw="842.7 KGS", value=842.7, unit="KG")
        ),
        ExtractedDocument(doc_type="bill_of_lading", file="c", doc_no=Cell(raw="EXSHTAO26027846", value="exshtao26027846")),
        ExtractedDocument(doc_type="certificate_of_origin", file="d"),
    ]


def _hs(line=1, status="자동 확정", code="4011500000"):
    return HSResult(line=line, status=status, by="history" if code else None, hs_code=code, candidates=[])


def _issue(doc, field, grade="불일치"):
    return Issue(rule_id="X-T", grade=grade, cells=[IssueCell(doc=doc, field=field, raw="1")], evidence="근거")


def _by_name(draft):
    return {f.name: f for f in draft.fields}


def test_읽은_값과_출처로_채운다():
    d = _by_name(draft_declaration(_docs(), [], [_hs()]))
    assert d["B/L 번호"].value == "EXSHTAO26027846" and d["B/L 번호"].source == "bill_of_lading.bl_no"
    assert d["총중량(kg)"].value == 842.7
    assert d["품명"].value == "Bicycle Tyre 1"  # 정규화한 value가 아니라 적힌 그대로
    assert d["수량"].value == 2651 and d["수량"].source == "commercial_invoice.items[0].qty"
    assert d["단위"].value == "PCS"
    assert d["순중량(kg)"].value == 796.0
    assert d["세번부호"].value == "4011500000" and d["세번부호"].source == "hs[0].hs_code"
    assert d["원산지증명서 유무"].value == "Y"


def test_모든_칸이_채움_또는_비움_둘_중_하나():
    draft = draft_declaration(_docs(), [], [_hs()])
    assert len(draft.fields) + len(draft.blank_fields) == len(DECLARATION_FIELDS)


def test_읽는_칸이_없는_칸은_비운다():
    draft = draft_declaration(_docs(), [], [_hs()])
    for key in ("vessel", "importer", "incoterms", "total_amount", "items[0].unit_price", "items[0].origin_criterion", "items[0].fta"):
        assert key in draft.blank_fields
    assert "선기명" not in _by_name(draft)


def test_HS가_확정_전이면_비운다():
    draft = draft_declaration(_docs(), [], [_hs(status="사람 확인 필요", code=None)])
    assert "items[0].hs_code" in draft.blank_fields
    assert "세번부호" not in _by_name(draft)


def test_HS_결과가_없는_줄도_비운다():
    assert "items[0].hs_code" in draft_declaration(_docs(), [], []).blank_fields


def test_사람_확정_HS는_채운다():
    d = _by_name(draft_declaration(_docs(), [], [_hs(status="사람 확정")]))
    assert d["세번부호"].value == "4011500000"


def test_불일치가_짚은_칸은_비운다():
    draft = draft_declaration(_docs(), [_issue("packing_list", "total_gross_kg")], [_hs()])
    assert "total_gross_kg" in draft.blank_fields
    assert "총중량(kg)" not in _by_name(draft)


def test_확인_필요도_비운다():
    draft = draft_declaration(_docs(), [_issue("packing_list", "total_gross_kg", "확인 필요")], [_hs()])
    assert "total_gross_kg" in draft.blank_fields


def test_참고는_비우지_않는다():
    draft = draft_declaration(_docs(), [_issue("packing_list", "total_gross_kg", "참고")], [_hs()])
    assert _by_name(draft)["총중량(kg)"].value == 842.7


def test_수량_칸_문제는_수량과_단위를_함께_비운다():
    draft = draft_declaration(_docs(), [_issue("commercial_invoice", "items[0].qty")], [_hs()])
    assert {"items[0].qty", "items[0].unit"} <= set(draft.blank_fields)
    assert "품명" in _by_name(draft)


def test_다른_서류의_같은_칸_문제는_상관없다():
    draft = draft_declaration(_docs(), [_issue("commercial_invoice", "total_gross_kg")], [_hs()])
    assert "총중량(kg)" in _by_name(draft)


def test_송장_번호_문제는_B_L_번호를_비우지_않는다():
    draft = draft_declaration(_docs(), [_issue("commercial_invoice", "doc_no"), _issue("packing_list", "invoice_no")], [_hs()])
    assert "B/L 번호" in _by_name(draft)


def test_B_L_번호_문제는_B_L_번호를_비운다():
    draft = draft_declaration(_docs(), [_issue("bill_of_lading", "doc_no")], [_hs()])
    assert "bl_no" in draft.blank_fields


def test_서류가_없으면_그_서류_칸은_비우고_원산지증명서는_N():
    docs = [d for d in _docs() if d.doc_type not in ("bill_of_lading", "certificate_of_origin")]
    draft = draft_declaration(docs, [], [_hs()])
    assert "bl_no" in draft.blank_fields
    assert _by_name(draft)["원산지증명서 유무"].value == "N"


def test_못_읽은_칸은_비운다():
    docs = _docs()
    docs[1].total_gross_kg = Cell(raw=None, value=None, unreadable="흐림")
    draft = draft_declaration(docs, [], [_hs()])
    assert "total_gross_kg" in draft.blank_fields


def test_여러_줄은_줄마다_하나씩_줄번호_빼기_1():
    draft = draft_declaration(_docs(2), [_issue("commercial_invoice", "items[1].qty")], [_hs(1), _hs(2, status="사람 확인 필요", code=None)])
    d = {(f.name, f.source): f.value for f in draft.fields}
    assert d[("수량", "commercial_invoice.items[0].qty")] == 2651
    assert ("수량", "commercial_invoice.items[1].qty") not in d
    assert {"items[1].qty", "items[1].unit", "items[1].hs_code"} <= set(draft.blank_fields)
    assert len(draft.fields) + len(draft.blank_fields) == 13 + 10 * 2


def test_서류가_없으면_초안은_서류_전체_칸만_비운다():
    draft = draft_declaration([], [], [])
    assert draft.fields[0].name == "원산지증명서 유무"
    assert len(draft.fields) == 1 and "total_gross_kg" in draft.blank_fields


def test_입력_서류를_바꾸지_않는다():
    docs = _docs()
    before = [d.model_dump() for d in docs]
    draft_declaration(docs, [_issue("packing_list", "total_gross_kg")], [_hs()])
    assert [d.model_dump() for d in docs] == before
