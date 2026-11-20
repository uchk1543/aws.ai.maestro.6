"""불일치 통지 문서 PDF (F13 #263). 담당: 4번 서버. AWS 호출 없음.

받는 쪽 메일 서버가 HTML 첨부를 버려서(2026-11-21 실제 발송 시험), 메일에는 통지 문서를 PDF로 붙인다.
내용은 C7 notice_document의 마크다운 그대로이고, api/notice_pdf.py는 그 마크다운을 PDF로 옮기기만 한다.
"""
import io

from pypdf import PdfReader

from api.notice_pdf import render_notice_pdf
from tests.unit.test_hs_request import BL, docs
from tests.unit.test_notify import CHECK, JOB, MISMATCH
from tools.models import Issue
from tools.validate import notice_document


def text_of(pdf: bytes) -> str:
    return "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf)).pages)


def test_pdf_carries_notice_text():
    notice = notice_document(JOB, docs(), [MISMATCH, CHECK])
    pdf = render_notice_pdf(notice)
    text = text_of(pdf)
    assert pdf.startswith(b"%PDF")
    for part in (f"[불일치 확인 요청] B/L {BL}", "자동 생성 문서입니다", "X-WT-01", "6,520kg", "정정한 서류를 다시 보내 주세요", "X-QT-02"):
        assert part in text, part
    assert "\\[" not in text and "\\_" not in text  # 마크다운 이스케이프는 풀어서 찍는다


def test_markup_in_document_text_is_data():
    """서류에서 온 글자의 <b>·<img>·& 는 해석하지 않고 글자 그대로 찍는다 (reportlab 마크업으로 쓰이지 않게)."""
    odd = Issue(rule_id="X-WT-01", grade="불일치", cells=[], evidence="품명 <b>굵게</b> & <img src=x> 이 다릅니다.")
    text = text_of(render_notice_pdf(notice_document(JOB, docs(), [odd])))
    assert "<b>굵게</b> & <img src=x>" in text


def test_same_notice_same_bytes():
    notice = notice_document(JOB, docs(), [MISMATCH])
    assert render_notice_pdf(notice) == render_notice_pdf(notice)
