"""draft_declaration과 신고서 PDF. 담당: 검증. 규칙: .kiro/steering/agent-design.md 7번, 형식: docs/schema.md

작업: e2e-plan.md C4·C5 (P1), C6 (P2, 신고서 PDF). 칸 목록과 출처는 docs/schema.md에 먼저 적고 여기 표로 옮긴다.
PDF는 render_declaration_pdf가 DeclarationDraft를 받아 바이트로 만든다. 저장·내려받기 주소(pdf_url)는 api/ 몫이다.
"""

import io
import re
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

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


# ---------------------------------------------------------------------------
# 신고서 PDF (C6 #24). 한글 글꼴(나눔고딕, SIL OFL 1.1)을 PDF에 넣는다. 모델은 쓰지 않는다 (agent-design.md 7번)
# ---------------------------------------------------------------------------
FONT_DIR = Path(__file__).parent / "fonts"
_FONT_REGULAR, _FONT_BOLD = "NanumGothic", "NanumGothic-Bold"
_KST = ZoneInfo("Asia/Seoul")  # Lambda 시계는 UTC라 한국 시간으로 고쳐 적는다
_MAX_TEXT = 300  # 서류에서 온 글자 한 덩이의 길이 상한 (표가 한 쪽을 넘어가지 않게)
PDF_TITLE = "수입신고서 초안 (간이 양식)"
PDF_NOTICE = f"{DRAFT_NOTICE} · 실제 신고 전송이 아닙니다"
BLANK_MARK = "(비움)"
_ITEM_INDEX = re.compile(r"items\[(\d+)\]")
_HS_INDEX = re.compile(r"hs\[(\d+)\]")


def _register_fonts() -> None:
    """나눔고딕 보통·굵게를 reportlab에 등록한다. 이미 했으면 건너뛴다."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    registered = set(pdfmetrics.getRegisteredFontNames())
    for name, file in ((_FONT_REGULAR, "NanumGothic-Regular.ttf"), (_FONT_BOLD, "NanumGothic-Bold.ttf")):
        if name not in registered:
            pdfmetrics.registerFont(TTFont(name, str(FONT_DIR / file)))


def _show(value: str | int | float | None) -> str:
    """신고서에 찍을 글자. 숫자는 천 단위 쉼표, 서류에서 온 글자는 한 줄로 정리하고 길이를 자른다. XML 특수 문자는 이스케이프한다."""
    if value is None:
        return BLANK_MARK
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        text = f"{value:,.3f}".rstrip("0").rstrip(".") if isinstance(value, float) else f"{value:,}"
    else:
        kept = "".join(ch if ch.isprintable() else " " for ch in str(value))
        text = " ".join(kept.split())
        text = text if len(text) <= _MAX_TEXT else text[:_MAX_TEXT] + "…"
    return escape(text)  # Paragraph가 <img src>·<a href> 같은 표시를 해석하지 못하게 서류 글자는 데이터로만 넣는다


def _line_of(field: DeclarationField, hs: list[HSResult] | None) -> int | None:
    """품목 칸이면 몇 번째 줄(1부터)인지. 서류 전체 칸이면 None. HS 칸은 hs[i]의 줄 번호를 쓴다."""
    m = _ITEM_INDEX.search(field.source)
    if m:
        return int(m.group(1)) + 1
    h = _HS_INDEX.fullmatch(field.source.split(".")[0])
    if h:
        idx = int(h.group(1))
        return hs[idx].line if hs is not None and idx < len(hs) else idx + 1
    return None


def render_declaration_pdf(
    draft: DeclarationDraft,
    *,
    hs: list[HSResult] | None = None,
    job_id: str | None = None,
    now: datetime | None = None,
) -> bytes:
    """신고서 초안을 한글 PDF로 만든다. 모델을 쓰지 않고 draft에 있는 칸만 찍는다 (agent-design.md 7번).
    언제: 화면이나 API가 '신고서 PDF 받기'를 눌렀을 때. 초안이 바뀌면(사람이 HS를 고름) 다시 만든다.
    받는 것: draft_declaration 결과, 선택으로 품목별 HS 결과(HS 칸의 줄 번호를 맞추는 데 씀), 작업 ID, 만든 시각(없으면 지금).
    반환: PDF 바이트. 맨 위에 '사람 검토 전 초안'을 적고, 칸마다 값과 출처(서류.칸)를 보인다.
    문제가 남아 비운 칸은 '(비움)'으로 보이고, 서류에서 온 글자는 데이터로만 넣는다(표시 해석 안 함).
    """
    print(f"[tool] render_declaration_pdf fields={len(draft.fields)} blanks={len(draft.blank_fields)}")
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    _register_fonts()
    stamp = (now or datetime.now(_KST)).astimezone(_KST).strftime("%Y-%m-%d %H:%M")
    base = ParagraphStyle("base", fontName=_FONT_REGULAR, fontSize=9, leading=12)
    small = ParagraphStyle("small", parent=base, fontSize=8, leading=10, textColor=colors.HexColor("#555555"))
    head = ParagraphStyle("head", parent=base, fontName=_FONT_BOLD, fontSize=10, textColor=colors.white)
    title = ParagraphStyle("title", parent=base, fontName=_FONT_BOLD, fontSize=17, leading=22)
    section = ParagraphStyle("section", parent=base, fontName=_FONT_BOLD, fontSize=11, leading=15, spaceBefore=8, spaceAfter=4)
    notice = ParagraphStyle(
        "notice", parent=base, fontName=_FONT_BOLD, fontSize=11, leading=15, alignment=TA_CENTER, textColor=colors.HexColor("#b00020")
    )
    blank_style = ParagraphStyle("blank", parent=base, textColor=colors.HexColor("#999999"))

    by_label = {f.name: f for f in draft.fields if _line_of(f, hs) is None}
    blank_keys = set(draft.blank_fields)

    def table(rows: list[tuple[str, str, str, bool]]) -> Table:
        data = [[Paragraph("칸", head), Paragraph("값", head), Paragraph("출처", head)]]
        for label, value, source, is_blank in rows:
            data.append([Paragraph(escape(label), base), Paragraph(value, blank_style if is_blank else base), Paragraph(escape(source), small)])
        t = Table(data, colWidths=[38 * mm, 78 * mm, 62 * mm], repeatRows=1)
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#37474f")),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b0bec5")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f7f8")]),
                ]
            )
        )
        return t

    story: list = [Paragraph(escape(PDF_TITLE), title), Spacer(1, 3 * mm), Paragraph(escape(PDF_NOTICE), notice), Spacer(1, 2 * mm)]
    meta = f"만든 시각 {stamp} (한국 시간)" + (f" · 작업 {_show(job_id)}" if job_id else "")  # _show가 이미 이스케이프한다
    story += [Paragraph(meta, small), Spacer(1, 2 * mm)]

    general = [(label, FIELD_KEYS[i]) for i, (label, _) in enumerate(DECLARATION_FIELDS[:_ITEM_FROM])]
    rows = []
    for label, key in general:
        f = by_label.get(label)
        rows.append((label, _show(f.value) if f else BLANK_MARK, f.source if f else "", f is None))
    story += [Paragraph("신고 내용", section), table(rows)]

    item_labels = [(FIELD_KEYS[i], label) for i, (label, _) in enumerate(DECLARATION_FIELDS) if i >= _ITEM_FROM]
    lines = sorted({ln for f in draft.fields if (ln := _line_of(f, hs)) is not None} | {int(m.group(1)) + 1 for k in blank_keys if (m := _ITEM_INDEX.match(k))})
    for line in lines:
        rows = []
        for key, label in item_labels:
            f = next((x for x in draft.fields if x.name == label and _line_of(x, hs) == line), None)
            rows.append((label, _show(f.value) if f else BLANK_MARK, f.source if f else "", f is None))
        story.append(KeepTogether([Paragraph(f"품목 {line}행", section), table(rows)]))
    if not lines:
        story.append(Paragraph("품목 칸이 없습니다.", base))

    legend = (
        f"{BLANK_MARK}: 불일치·확인 필요가 남았거나, HS가 확정되지 않았거나, 서류에서 읽지 못한 칸입니다. "
        f"비운 칸은 {len(draft.blank_fields)}개입니다. 검토하고 채운 뒤 신고하세요."
    )
    story += [Spacer(1, 4 * mm), Paragraph(escape(legend), small)]

    def footer(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont(_FONT_REGULAR, 8)
        canvas.setFillColor(colors.HexColor("#777777"))
        canvas.drawString(16 * mm, 10 * mm, PDF_NOTICE)
        canvas.drawRightString(A4[0] - 16 * mm, 10 * mm, f"{doc.page}쪽")
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=16 * mm, bottomMargin=18 * mm,
        title=PDF_TITLE, author="team06", invariant=1,
    )
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()