"""draft_declaration. 담당: 검증. 규칙: .kiro/steering/agent-design.md 7번, 형식: docs/schema.md

작업: e2e-plan.md C4·C5 (P1). 칸 목록과 출처는 docs/schema.md에 먼저 적고 여기 표로 옮긴다.
"""

from tools.models import Cell, DeclarationDraft, DeclarationField, ExtractedDocument, ExtractedItem, HSResult, Issue

# (신고서 칸 이름, 출처 "서류.칸") 목록. C4에서 채운다. 예: ("품명", "commercial_invoice.items[0].name")
# docs/schema.md '신고서 초안 칸' 표와 같다 (tests/unit/test_declaration_fields.py가 맞는지 본다). 서류 전체 칸 13개, 품목 칸 10개.
DECLARATION_FIELDS: list[tuple[str, str]] = [
    ("B/L 번호", "bill_of_lading.bl_no"),
    ("선기명", "bill_of_lading.vessel_voyage"),
    ("수입자", "commercial_invoice.consignee_name"),
    ("해외공급자", "commercial_invoice.exporter_name"),
    ("적출국", "bill_of_lading.port_loading"),
    ("총중량(kg)", "packing_list.total_gross_kg"),
    ("총포장갯수", "packing_list.total_packages"),
    ("포장종류", "packing_list"),
    ("인도조건", "commercial_invoice.incoterms"),
    ("통화", "commercial_invoice"),
    ("결제금액", "commercial_invoice.total_amount"),
    ("결제방법", "commercial_invoice.payment_term"),
    ("원산지증명서 유무", "certificate_of_origin"),
    ("품명", "commercial_invoice.items[0].name"),
    ("세번부호", "hs[0].hs_code"),
    ("수량", "commercial_invoice.items[0].qty"),
    ("단위", "commercial_invoice.items[0].qty"),
    ("순중량(kg)", "packing_list.items[0].net_kg"),
    ("단가", "commercial_invoice.items[0].unit_price"),
    ("금액", "commercial_invoice.items[0].amount"),
    ("원산지", "commercial_invoice.origin"),
    ("협정", "certificate_of_origin"),
    ("원산지결정기준", "certificate_of_origin.items[0].origin_criterion"),
]

DRAFT_NOTICE = "사람 검토 전 초안"  # 화면(DeclarationTable)이 항상 적는다. DeclarationDraft에는 칸이 없다.

# 칸 키(schema.md 표의 field). DECLARATION_FIELDS와 같은 순서. blank_fields에는 이 키로 적는다.
FIELD_KEYS: list[str] = [
    "bl_no", "vessel", "importer", "supplier", "export_country", "total_gross_kg", "total_packages",
    "package_kind", "incoterms", "currency", "total_amount", "payment", "co_present",
    "description", "hs_code", "qty", "unit", "net_kg", "unit_price", "amount", "origin", "fta", "origin_criterion",
]
_ITEM_FROM = FIELD_KEYS.index("description")  # 이 번호부터는 품목(줄)마다 하나씩
# 출처에 쓴 이름과 ExtractedDocument 칸 이름이 다른 것. 문제(Issue)의 칸 이름도 같이 맞춘다.
_ALIAS = {"bl_no": "doc_no", "invoice_no": "doc_no"}
_OK_HS = ("자동 확정", "사람 확정")


def _cell_value(cell: Cell | None) -> str | int | float | None:
    """칸에서 신고서에 쓸 값을 꺼낸다. 숫자는 value, 글자는 서류에 적힌 그대로(raw). 못 읽었으면 None."""
    if cell is None:
        return None
    if isinstance(cell.value, (int, float)) and not isinstance(cell.value, bool):
        return cell.value
    raw = (cell.raw or "").strip()
    return raw or None


def _split_source(source: str) -> tuple[str, str]:
    """'commercial_invoice.items[0].qty' → ('commercial_invoice', 'items[0].qty'). 서류만 있으면 경로는 빈 글자."""
    doc, _, path = source.partition(".")
    return doc, path


def _issue_cells(issues: list[Issue]) -> set[tuple[str, str]]:
    """비워야 할 칸: 불일치·확인 필요가 짚은 (서류, 칸 경로). 참고는 비우지 않는다."""
    out = set()
    for issue in issues:
        if issue.grade == "참고":
            continue
        for c in issue.cells:
            path = c.field
            for old, new in _ALIAS.items():
                if path == old:
                    path = new
            out.add((c.doc, path))
    return out


def _read_value(key: str, source: str, doc: ExtractedDocument | None, line: int | None) -> str | int | float | None:
    """서류에서 칸 하나의 값을 읽는다. 읽는 칸이 모델에 없거나 비었으면 None."""
    if doc is None:
        return None
    _, path = _split_source(source)
    if not path:  # 서류만 적힌 출처(포장종류·통화·협정)는 읽는 칸이 아직 없다
        return None
    name = _ALIAS.get(path.rsplit(".", 1)[-1], path.rsplit(".", 1)[-1])
    if line is None:
        return _cell_value(getattr(doc, name, None)) if name in ExtractedDocument.model_fields else None
    item = next((i for i in doc.items if i.line == line), None)
    if item is not None and name in ExtractedItem.model_fields:
        cell = getattr(item, name, None)
        if key == "unit":
            return (cell.unit or None) if cell is not None else None
        return _cell_value(cell)
    if name in ExtractedDocument.model_fields:  # 줄이 아닌 서류 칸을 줄마다 쓰는 경우(원산지)
        return _cell_value(getattr(doc, name, None))
    return None


def draft_declaration(docs: list[ExtractedDocument], issues: list[Issue], hs: list[HSResult]) -> DeclarationDraft:
    """신고서 초안을 코드로 채운다. 모델은 쓰지 않는다.
    언제: HS 결과가 나온 뒤, 그리고 사람이 HS를 고른 뒤 다시.
    받는 것: 읽은 서류, 남은 문제, 품목별 HS 결과.
    반환: DeclarationDraft. 문제가 남은 칸과 확정 안 된 HS 칸은 비우고 blank_fields에 적는다.
    칸 목록과 출처는 docs/schema.md '신고서 초안 칸'. 비우는 경우: 불일치·확인 필요가 그 칸을 짚음, HS 미확정,
    읽는 칸이 없음, 서류가 없음, 못 읽음. 비운 칸은 fields에 넣지 않고 blank_fields에 칸 키(품목 칸은 items[0].qty처럼)로만 적는다.
    """
    print(f"[tool] draft_declaration docs={[d.doc_type for d in docs]} issues={len(issues)}")
    by_type: dict[str, ExtractedDocument] = {}
    for d in docs:
        by_type.setdefault(d.doc_type, d)
    flagged = _issue_cells(issues)
    fields: list[DeclarationField] = []
    blanks: list[str] = []

    def put(key: str, label: str, source: str, value, blank_path: str, path_for_issue: str, doc_type: str) -> None:
        issue_path = _ALIAS.get(path_for_issue, path_for_issue)
        if value is None or (doc_type, issue_path) in flagged:
            blanks.append(blank_path)
        else:
            fields.append(DeclarationField(name=label, value=value, source=source))

    # 서류 전체 칸
    for key, (label, source) in list(zip(FIELD_KEYS, DECLARATION_FIELDS))[:_ITEM_FROM]:
        doc_type, path = _split_source(source)
        if key == "co_present":  # 원산지증명서가 올라왔는지. 없으면 N도 사실이라 채운다
            fields.append(DeclarationField(name=label, value="Y" if "certificate_of_origin" in by_type else "N", source=source))
            continue
        value = _read_value(key, source, by_type.get(doc_type), None)
        put(key, label, source, value, key, path, doc_type)

    # 품목 칸: 줄마다 하나씩
    lines = sorted({i.line for d in docs for i in d.items} | {r.line for r in hs})
    hs_at = {r.line: (idx, r) for idx, r in enumerate(hs)}
    for line in lines:
        for key, (label, source) in list(zip(FIELD_KEYS, DECLARATION_FIELDS))[_ITEM_FROM:]:
            blank_path = f"items[{line - 1}].{key}"
            if key == "hs_code":
                idx, r = hs_at.get(line, (None, None))
                if r is not None and r.status in _OK_HS and r.hs_code:
                    fields.append(DeclarationField(name=label, value=r.hs_code, source=f"hs[{idx}].hs_code"))
                else:
                    blanks.append(blank_path)
                continue
            doc_type, path = _split_source(source)
            path = path.replace("items[0]", f"items[{line - 1}]")
            src = f"{doc_type}.{path}" if path else doc_type
            value = _read_value(key, source, by_type.get(doc_type), line)
            put(key, label, src, value, blank_path, path, doc_type)
    return DeclarationDraft(fields=fields, blank_fields=blanks, pdf_url=None)
