"""불일치 통지 문서 PDF (F13 #263). 담당: 서버. 확인 요청 메일(api/notify.py)에 붙일 첨부를 만든다.

왜 PDF인가: 받는 쪽 메일 서버가 HTML 첨부가 붙은 메일을 버렸다 (2026-11-21 실제 SES 발송 시험: HTML 첨부는 매번 도착하지 않고 PDF 첨부는 매번 도착).
내용은 C7 tools.validate.notice_document가 만든 마크다운 그대로다. 이 파일은 그 마크다운을 PDF로 옮기기만 하고 문장을 새로 쓰지 않는다.
쓰는 마크다운: '# 제목', '## 소제목', '> 인용', '- 목록', '  - 하위 목록', 빈 줄, 일반 문단. 표시 문법 앞의 '\\' 이스케이프는 풀어서 찍는다.
서류에서 온 글자는 데이터로만 넣는다 (XML 이스케이프해서 reportlab 마크업으로 쓰이지 않게). 모델·AWS 호출 없음, 새 의존성 없음.
"""
import io
import re
from xml.sax.saxutils import escape

from tools.declaration import _FONT_BOLD, _FONT_REGULAR, _register_fonts
from tools.models import NoticeDocument

TITLE = "불일치 통지 문서"
_UNESCAPE = re.compile(r"\\([\\`*_{}\[\]()#+!|<>~&])")  # tools/validate.py _MD_SPECIAL 이 붙인 이스케이프


def _text(markdown: str) -> str:
    """마크다운 한 줄의 글자: 이스케이프를 풀고 reportlab용으로 XML 이스케이프한다."""
    return escape(_UNESCAPE.sub(r"\1", markdown))


def render_notice_pdf(notice: NoticeDocument) -> bytes:
    """불일치 통지 문서(NoticeDocument)의 마크다운을 A4 PDF로 옮긴다.

    언제: 확인 요청 메일에 통지 문서를 붙일 때 (api/notify.build_attachments).
    받는 것: notice(C7 notice_document 결과).
    반환: PDF 바이트. 같은 문서는 같은 바이트다 (invariant). 한글은 나눔고딕(tools/fonts/)으로 찍는다.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    print(f"[tool] render_notice_pdf job={notice.job_id} 불일치 {notice.mismatch_count} 확인 필요 {notice.check_count}")
    _register_fonts()
    base = ParagraphStyle("base", fontName=_FONT_REGULAR, fontSize=9.5, leading=13)
    styles = {
        "h1": ParagraphStyle("h1", parent=base, fontName=_FONT_BOLD, fontSize=15, leading=20, spaceAfter=4),
        "h2": ParagraphStyle("h2", parent=base, fontName=_FONT_BOLD, fontSize=11, leading=15, spaceBefore=8, spaceAfter=3),
        "quote": ParagraphStyle("quote", parent=base, fontName=_FONT_BOLD, textColor=colors.HexColor("#b00020"), spaceAfter=3),
        "li": ParagraphStyle("li", parent=base, leftIndent=4 * mm, bulletIndent=0),
        "li2": ParagraphStyle("li2", parent=base, fontSize=8.5, leading=11.5, leftIndent=9 * mm, bulletIndent=5 * mm,
                              textColor=colors.HexColor("#444444")),
        "p": base,
    }
    story: list = []
    for line in notice.markdown.splitlines():
        if not line.strip():
            story.append(Spacer(1, 1.5 * mm))
        elif line.startswith("## "):
            story.append(Paragraph(_text(line[3:]), styles["h2"]))
        elif line.startswith("# "):
            story.append(Paragraph(_text(line[2:]), styles["h1"]))
        elif line.startswith("> "):
            story.append(Paragraph(_text(line[2:]), styles["quote"]))
        elif line.startswith("  - "):
            story.append(Paragraph(_text(line[4:]), styles["li2"], bulletText="-"))
        elif line.startswith("- "):
            story.append(Paragraph(_text(line[2:]), styles["li"], bulletText="·"))
        else:
            story.append(Paragraph(_text(line), styles["p"]))

    def footer(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont(_FONT_REGULAR, 8)
        canvas.setFillColor(colors.HexColor("#777777"))
        canvas.drawString(16 * mm, 10 * mm, f"{TITLE} · 자동 생성 문서 · 작업 {notice.job_id}")
        canvas.drawRightString(A4[0] - 16 * mm, 10 * mm, f"{doc.page}쪽")
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=16 * mm, bottomMargin=18 * mm,
        title=TITLE, author="team06", invariant=1,
    )
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
