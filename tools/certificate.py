"""검수 완료서 PDF (X1 #258). 사람이 승인해 WMS에 등록한 작업의 결과를 한글 PDF 한 부로 옮긴다.

모델을 쓰지 않는다. 저장된 작업 결과(문제 목록, HS, WMS 상태)와 읽은 서류에 있는 값만 찍고,
없는 칸은 '없음'으로 적는다 (agent-design.md 7번: 문서는 코드가 채운다). 서류에서 온 글자는 데이터로만 넣는다.
글꼴과 글자 정리는 신고서 PDF(tools/declaration.py)가 쓰는 것을 그대로 가져온다. 새 의존성은 없다.
"""
import io
from datetime import datetime
from xml.sax.saxutils import escape

from tools.declaration import _FONT_BOLD, _FONT_REGULAR, _KST, _register_fonts, _show
from tools.models import DOC_TYPE_KO, Cell, ExtractedDocument, HSBy, HSResult, Issue, Job

CERT_TITLE = "검수 완료서"
CERT_NOTICE = "시스템 기록용이며 전자서명이 아닙니다"
NONE_MARK = "없음"

# 확정 방식 이름 (화면 HsPicker와 같은 뜻)
_HS_BY_KO: dict[HSBy, str] = {"history": "확정 이력", "auto_match": "서류 일치 자동 확정", "human": "사람이 고름"}


class NotIssuable(ValueError):
    """사람 승인으로 등록된 작업이 아니라 검수 완료서를 만들 수 없다. 메시지는 화면·API가 그대로 보여 준다."""


def _text(cell: Cell | None) -> str | None:
    """칸의 글자. 푼 글자(value)가 있으면 그것, 없으면 적힌 그대로(raw). 둘 다 없으면 None."""
    if cell is None:
        return None
    return cell.value if isinstance(cell.value, str) else cell.raw


def _bl_no(docs: list[ExtractedDocument]) -> str | None:
    return next((_text(d.doc_no) for d in docs if d.doc_type == "bill_of_lading" and _text(d.doc_no)), None)


def _approved_text(approved_at: str) -> str:
    """승인 시각을 '2026-11-21 09:30:12 (한국 시간)'으로. 풀 수 없으면 저장된 글자 그대로."""
    try:
        return datetime.fromisoformat(approved_at).astimezone(_KST).strftime("%Y-%m-%d %H:%M:%S") + " (한국 시간)"
    except ValueError:
        return approved_at


def check_issuable(job: Job) -> None:
    """검수 완료서를 만들 수 있는지 본다. 못 만들면 NotIssuable(이유). API가 409로 바꾼다."""
    wms = job.result.wms if job.result else None
    if wms is None or wms.status != "등록됨":
        raise NotIssuable("사람이 승인해 등록한 작업만 발급합니다 (아직 승인 대기 중이거나 등록되지 않았습니다)")
    if wms.by != "human":
        raise NotIssuable("사람이 승인해 등록한 작업만 발급합니다 (자동 등록 건은 검수자가 없습니다)")
    if not wms.approver or not wms.approved_at:
        raise NotIssuable("검수자 이름이 기록되지 않은 옛 작업은 발급할 수 없습니다")


def make_certificate(job: Job, docs: list[ExtractedDocument], *, importer: str | None = None) -> bytes:
    """검수 완료서 PDF를 만든다. 모델·AWS를 부르지 않는다.

    언제: GET /jobs/{id}/certificate 가 사람 승인으로 등록된 작업을 받았을 때. 파일은 저장하지 않고 부를 때마다 만든다.
    받는 것: job(문제 목록·HS·WMS 상태가 든 작업), docs(읽은 서류), importer(수입자. 없으면 '없음').
    반환: PDF 바이트. 같은 입력은 같은 바이트다 (만든 시각 대신 저장된 승인 시각을 쓴다).
    실패: 사람 승인으로 등록된 작업이 아니면 NotIssuable.
    """
    check_issuable(job)
    assert job.result is not None and job.result.wms is not None  # check_issuable이 보장한다
    result, wms = job.result, job.result.wms
    print(f"[tool] make_certificate job={job.job_id} docs={len(docs)} issues={len(result.issues)} hs={len(result.hs)}")

    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    _register_fonts()
    base = ParagraphStyle("base", fontName=_FONT_REGULAR, fontSize=9, leading=12)
    small = ParagraphStyle("small", parent=base, fontSize=8, leading=10, textColor=colors.HexColor("#555555"))
    head = ParagraphStyle("head", parent=base, fontName=_FONT_BOLD, fontSize=10, textColor=colors.white)
    bold = ParagraphStyle("bold", parent=base, fontName=_FONT_BOLD)
    title = ParagraphStyle("title", parent=base, fontName=_FONT_BOLD, fontSize=18, leading=24)
    section = ParagraphStyle("section", parent=base, fontName=_FONT_BOLD, fontSize=11, leading=15, spaceBefore=10, spaceAfter=4)
    notice = ParagraphStyle(
        "notice", parent=base, fontName=_FONT_BOLD, fontSize=10, leading=14, alignment=TA_CENTER, textColor=colors.HexColor("#b00020")
    )

    def p(value, style=base) -> Paragraph:
        return Paragraph(_show(NONE_MARK if value is None else value), style)  # _show가 글자를 정리하고 이스케이프한다

    def grid(rows: list[list], widths: list[float], *, header: bool) -> Table:
        t = Table(rows, colWidths=[w * mm for w in widths], repeatRows=1 if header else 0)
        style = [
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b0bec5")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]
        if header:
            style += [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#37474f")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f7f8")]),
            ]
        else:
            style += [("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eceff1"))]
        t.setStyle(TableStyle(style))
        return t

    story: list = [Paragraph(escape(CERT_TITLE), title), Spacer(1, 2 * mm), Paragraph(escape(CERT_NOTICE), notice), Spacer(1, 3 * mm)]

    # 1. 검수와 등록
    info = [
        ("작업 번호", job.job_id),
        ("B/L 번호", _bl_no(docs) or NONE_MARK),
        ("수입자", importer or NONE_MARK),
        ("검수자", wms.approver),
        ("승인 시각", _approved_text(wms.approved_at or "")),
        ("승인 방식", "사람 승인 (불일치를 판독 오류로 확인)" if wms.override_reason else "사람 승인"),
        ("WMS 번호", wms.wms_id or NONE_MARK),
    ]
    if wms.override_reason:
        info.append(("예외 사유", wms.override_reason))
    story += [Paragraph("검수와 등록", section), grid([[p(k, bold), p(v)] for k, v in info], [36, 140], header=False)]

    # 2. 읽은 서류
    story.append(Paragraph("읽은 서류", section))
    if docs:
        rows = [[p("종류", head), p("파일", head)]] + [
            [p(DOC_TYPE_KO.get(d.doc_type, d.doc_type)), p(d.file.rsplit("/", 1)[-1])] for d in docs
        ]
        story.append(grid(rows, [40, 136], header=True))
    else:
        story.append(p("읽은 서류 기록이 없습니다."))

    # 3. 대조 결과
    mismatch = [i for i in result.issues if i.grade == "불일치"]
    check = [i for i in result.issues if i.grade == "확인 필요"]
    story.append(Paragraph("대조 결과", section))
    story.append(p(f"불일치 {len(mismatch)}건, 확인 필요 {len(check)}건 (참고는 제외)"))
    shown = [i for i in result.issues if i.grade in ("불일치", "확인 필요")]
    if shown:
        story.append(Spacer(1, 2 * mm))
        rows = [[p("등급", head), p("규칙", head), p("근거", head), p("서류·칸", head)]] + [
            [p(i.grade), p(i.rule_id), p(i.evidence), p(_cells(i))] for i in shown
        ]
        story.append(grid(rows, [18, 22, 90, 46], header=True))
    else:
        story.append(p("남은 문제가 없습니다."))

    # 4. HS
    story.append(Paragraph("품목별 HS", section))
    if result.hs:
        rows = [[p("행", head), p("품명", head), p("서류 HS", head), p("최종 HS", head), p("확정 방식", head)]] + [
            [p(h.line), p(h.item_name), p(h.doc_hs_code), p(h.hs_code or "미확정"), p(_hs_by(h))] for h in result.hs
        ]
        story.append(grid(rows, [12, 62, 28, 32, 42], header=True))
    else:
        story.append(p("품목별 HS 결과가 없습니다."))

    story += [Spacer(1, 5 * mm), p("승인 시각은 저장된 값이고, 이 문서는 요청할 때마다 저장된 작업 결과에서 다시 만듭니다.", small)]

    def footer(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont(_FONT_REGULAR, 8)
        canvas.setFillColor(colors.HexColor("#777777"))
        canvas.drawString(16 * mm, 10 * mm, f"{CERT_NOTICE} · 작업 {job.job_id}")
        canvas.drawRightString(A4[0] - 16 * mm, 10 * mm, f"{doc.page}쪽")
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=16 * mm, bottomMargin=18 * mm,
        title=CERT_TITLE, author="team06", invariant=1,
    )
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


def _cells(issue: Issue) -> str:
    """문제가 짚은 칸들을 '상업송장.items[0].gross_kg, 포장명세서.items[0].gross_kg'로."""
    return ", ".join(f"{DOC_TYPE_KO.get(c.doc, c.doc)}.{c.field}" for c in issue.cells) or NONE_MARK


def _hs_by(h: HSResult) -> str:
    return _HS_BY_KO.get(h.by, NONE_MARK) if h.by else NONE_MARK
