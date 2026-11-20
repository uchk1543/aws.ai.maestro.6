"""HS 확인 요청서 PDF (X2 #260). HS를 서류에서 확정하지 못한 품목을 관세사에게 알리는 문서.

언제 쓰나: 작업 결과의 HS에 '사람 확인 필요' 품목이 남았을 때. 관세사가 분류하려면 서류 값과 후보뿐 아니라
제품 정보(재질·용도·구성품·사양서·사진)가 필요한데, 서류에서는 읽지 못한다. 그래서 읽은 값과 후보를 보여 주고,
제품 정보는 화주에게 받아 달라는 요청 목록으로 적는다.

모델을 쓰지 않는다. 저장된 작업 결과와 읽은 서류에 있는 값만 찍고, 없는 칸은 '없음'으로 적는다 (agent-design.md 7번).
HS는 AI가 확정하지 않는다 (6번). 이 문서의 후보는 참고이고 최종 품목분류는 관세사가 한다.
서류에서 온 글자는 데이터로만 넣는다. 글꼴과 글자 정리는 신고서 PDF(tools/declaration.py)가 쓰는 것을 가져온다. 새 의존성은 없다.
"""
import io
import re
from datetime import datetime
from xml.sax.saxutils import escape

from tools.declaration import _FONT_BOLD, _FONT_REGULAR, _KST, _register_fonts, _show
from tools.models import DOC_TYPE_KO, Cell, ExtractedDocument, ExtractedItem, HSResult, Job

TITLE = "HS 확인 요청서"
NOTICE = "자동 생성 문서입니다. 사람이 검토한 뒤 전달하세요. 후보는 참고이고 최종 품목분류는 관세사가 합니다"
NONE_MARK = "없음"

# 서류에서 읽지 못하는 제품 정보. 관세사가 분류하려면 필요하다 (관세사 실무 참고)
REQUEST_ITEMS = [
    "재질 (주된 소재와 비율)",
    "용도와 기능",
    "형상 (모양과 크기)",
    "구성품과 수량 (세트인지, 따로 파는지)",
    "사양서·설명서 (최신본)와 제품 사진",
    "성분 (화학품·화장품 등 해당할 때)",
]
REQUEST_NOTE = "서류에서 읽지 못한 정보입니다. 화주에게 받아 관세사에게 함께 전달해 주세요. 분류가 어려우면 관세사가 품목분류 사전심사를 신청할 수 있습니다."


class NothingToRequest(ValueError):
    """HS를 사람이 확인해야 하는 품목이 없어 요청서를 만들 수 없다. 메시지는 API가 그대로 보여 준다."""


def pending_hs(job: Job) -> list[HSResult]:
    """HS가 '사람 확인 필요'로 남은 품목 결과."""
    return [h for h in (job.result.hs if job.result else []) if h.status == "사람 확인 필요"]


def check_requestable(job: Job) -> list[HSResult]:
    """요청서를 만들 수 있는지 본다. 만들 수 있으면 미확정 품목 목록, 아니면 NothingToRequest."""
    pending = pending_hs(job)
    if not pending:
        raise NothingToRequest("HS를 사람이 확인해야 하는 품목이 없습니다")
    return pending


def _text(cell: Cell | None) -> str | None:
    """칸의 글자. 푼 글자(value)가 있으면 그것, 없으면 적힌 그대로(raw). 읽지 못한 이유만 있으면 '읽지 못함(이유)'."""
    if cell is None:
        return None
    if cell.value is not None:
        return str(cell.value)
    if cell.raw is not None:
        return cell.raw
    return f"읽지 못함({cell.unreadable})" if cell.unreadable else None


def _first(docs: list[ExtractedDocument], doc_type: str | None, attr: str) -> str | None:
    """doc_type 서류(없으면 모든 서류) 중 처음으로 값이 있는 칸의 글자."""
    for d in docs:
        if doc_type is None or d.doc_type == doc_type:
            text = _text(getattr(d, attr, None))
            if text:
                return text
    return None


def _digits(text: str | None) -> str:
    return re.sub(r"\D", "", text or "")


def format_hs(code: str) -> str:
    """1234567890 → 1234.56-7890. 10자리가 아니면 그대로."""
    return f"{code[:4]}.{code[4:6]}-{code[6:]}" if re.fullmatch(r"[0-9]{10}", code) else code


def _doc_items(docs: list[ExtractedDocument], line: int) -> list[tuple[ExtractedDocument, ExtractedItem]]:
    """품목 행 번호가 같은 줄을 가진 서류와 그 줄 (서류 순서대로)."""
    out = []
    for d in docs:
        item = next((i for i in d.items if i.line == line), None)
        if item is not None:
            out.append((d, item))
    return out


def reasons(h: HSResult, rows: list[tuple[ExtractedDocument, ExtractedItem]]) -> list[str]:
    """이 품목이 자동 확정되지 못한 사유. 저장된 값으로 판단할 수 있는 사실만 적는다 (모델 호출 없음)."""
    out: list[str] = []
    seen = [_digits(_text(i.hs_code)) for _, i in rows]
    seen = [s for s in dict.fromkeys(seen) if s]
    if not h.candidates:
        out.append("HS 표에서 후보를 찾지 못했습니다")
    if not seen:
        out.append("서류에 HS가 적혀 있지 않습니다")
    else:
        if len({s[:6] for s in seen}) > 1:
            out.append("서류끼리 HS가 다릅니다 (" + " / ".join(seen) + ")")
        if all(len(s) < 10 for s in seen):
            out.append("서류 HS가 10자리가 아니라 한국 10자리 코드를 정할 수 없습니다")
        top = h.candidates[0].hs if h.candidates else ""
        if top and any(len(s) >= 6 and s[:6] != top[:6] for s in seen):
            out.append("서류 HS 앞 6자리와 1순위 후보가 다릅니다")
    return out or ["자동 확정 조건(서류 HS 10자리, 서류끼리 일치, 후보 1순위와 일치)을 채우지 못했습니다"]


def make_hs_request(job: Job, docs: list[ExtractedDocument], *, importer: str | None = None, now: datetime | None = None) -> bytes:
    """HS 확인 요청서 PDF를 만든다. 모델·AWS를 부르지 않는다.

    언제: GET /jobs/{id}/hs-request 가 HS 미확정 품목이 있는 작업을 받았을 때. 파일은 저장하지 않고 부를 때마다 만든다.
    받는 것: job(품목별 HS 결과가 든 작업), docs(읽은 서류), importer(수입자. 없으면 상업송장 수하인), now(만든 시각. 없으면 지금).
    반환: PDF 바이트. 품목마다 서류별 값, 후보 3개와 근거, 미확정 사유를 담고, 끝에 화주에게 받을 제품 정보 목록을 적는다.
    실패: 사람이 확인해야 하는 HS 품목이 없으면 NothingToRequest.
    """
    pending = check_requestable(job)
    print(f"[tool] make_hs_request job={job.job_id} docs={len(docs)} pending={len(pending)}")

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
    bold = ParagraphStyle("bold", parent=base, fontName=_FONT_BOLD)
    title = ParagraphStyle("title", parent=base, fontName=_FONT_BOLD, fontSize=18, leading=24)
    section = ParagraphStyle("section", parent=base, fontName=_FONT_BOLD, fontSize=11, leading=15, spaceBefore=10, spaceAfter=4)
    notice = ParagraphStyle(
        "notice", parent=base, fontName=_FONT_BOLD, fontSize=9.5, leading=13, alignment=TA_CENTER, textColor=colors.HexColor("#b00020")
    )

    def p(value, style=base) -> Paragraph:
        return Paragraph(_show(NONE_MARK if value is None else value), style)  # _show가 글자를 정리하고 이스케이프한다

    def grid(rows: list[list], widths: list[float], *, header: bool) -> Table:
        t = Table(rows, colWidths=[w * mm for w in widths], repeatRows=1 if header else 0)
        style = [("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b0bec5")), ("VALIGN", (0, 0), (-1, -1), "TOP")]
        if header:
            style += [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#37474f")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f7f8")]),
            ]
        else:
            style += [("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eceff1"))]
        t.setStyle(TableStyle(style))
        return t

    story: list = [Paragraph(escape(TITLE), title), Spacer(1, 2 * mm), Paragraph(escape(NOTICE), notice), Spacer(1, 3 * mm)]

    # 1. 식별 번호와 당사자
    info = [
        ("작업 번호", job.job_id),
        ("B/L 번호", _first(docs, "bill_of_lading", "doc_no")),
        ("송장 번호", _first(docs, "commercial_invoice", "doc_no")),
        ("수입자", importer or _first(docs, "commercial_invoice", "consignee_name")),
        ("수출자", _first(docs, None, "exporter_name")),
        ("원산지", _first(docs, None, "origin")),
        ("거래 조건", _first(docs, "commercial_invoice", "incoterms")),
        ("만든 시각", f"{stamp} (한국 시간)"),
    ]
    story += [Paragraph("화물", section), grid([[p(k, bold), p(v)] for k, v in info], [32, 144], header=False)]
    story.append(Paragraph(f"HS 확인이 필요한 품목 {len(pending)}개", section))

    # 2. 품목마다
    for h in pending:
        rows = _doc_items(docs, h.line)
        name = h.item_name or next((_text(i.name) for _, i in rows if _text(i.name)), None)
        block: list = [Paragraph(_show(f"{h.line}행 · {name or NONE_MARK}"), bold), Spacer(1, 1.5 * mm)]
        if rows:
            data = [[p("서류", head), p("서류 HS", head), p("수량", head), p("총중량", head), p("순중량", head), p("금액", head)]] + [
                [
                    p(DOC_TYPE_KO.get(d.doc_type, d.doc_type)), p(_text(i.hs_code)), p(_text(i.qty)),
                    p(_text(i.gross_kg)), p(_text(i.net_kg)), p(_text(i.amount)),
                ]
                for d, i in rows
            ]
            block.append(grid(data, [30, 30, 30, 30, 28, 28], header=True))
        else:
            block.append(p("이 품목 행을 가진 서류 기록이 없습니다."))
        block.append(Spacer(1, 2 * mm))
        if h.candidates:
            data = [[p("후보 HS", head), p("HS 표의 품목명", head), p("근거 (서류의 어느 칸)", head)]] + [
                [p(format_hs(c.hs)), p(c.name), p(c.reason)] for c in h.candidates
            ]
            block.append(grid(data, [32, 64, 80], header=True))
        else:
            block.append(p("후보 HS: 없음"))
        block += [Spacer(1, 2 * mm), p("자동 확정하지 못한 이유", bold)]
        block += [p(f"· {why}") for why in reasons(h, rows)]
        block.append(Spacer(1, 4 * mm))
        story.append(KeepTogether(block))

    # 3. 화주에게 받을 제품 정보
    story.append(Paragraph("화주에게 받을 제품 정보", section))
    story += [p(REQUEST_NOTE, small), Spacer(1, 1.5 * mm)]
    story += [p(f"[  ] {item}") for item in REQUEST_ITEMS]  # 나눔고딕에 ☐ 글자가 없어 대괄호로 쓴다

    def footer(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont(_FONT_REGULAR, 8)
        canvas.setFillColor(colors.HexColor("#777777"))
        canvas.drawString(16 * mm, 10 * mm, f"{TITLE} · 자동 생성 문서 · 작업 {job.job_id}")
        canvas.drawRightString(A4[0] - 16 * mm, 10 * mm, f"{doc.page}쪽")
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=16 * mm, bottomMargin=18 * mm,
        title=TITLE, author="team06", invariant=1,
    )
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
