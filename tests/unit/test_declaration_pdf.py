"""C6 신고서 PDF 단위 테스트. AWS와 Bedrock을 부르지 않는다. 담당: 검증."""
import io
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from pypdf import PdfReader

from tools.declaration import (
    BLANK_MARK,
    DECLARATION_FIELDS,
    FONT_DIR,
    PDF_NOTICE,
    PDF_TITLE,
    draft_declaration,
    render_declaration_pdf,
)
from tools.models import Cell, DeclarationDraft, DeclarationField, ExtractedDocument, ExtractedItem, HSResult

NOW = datetime(2026, 11, 21, 9, 5, tzinfo=ZoneInfo("Asia/Seoul"))


def _docs(lines=1, name="Bicycle Tyre"):
    inv_items = [
        ExtractedItem(
            line=i,
            name=Cell(raw=f"{name} {i}", value=f"{name} {i}".lower()),
            qty=Cell(raw=f"{2650 + i} PCS", value=2650 + i, unit="PCS"),
        )
        for i in range(1, lines + 1)
    ]
    return [
        ExtractedDocument(doc_type="commercial_invoice", file="a", items=inv_items),
        ExtractedDocument(
            doc_type="packing_list", file="b", total_gross_kg=Cell(raw="6,250.5 KGS", value=6250.5, unit="KG")
        ),
        ExtractedDocument(doc_type="bill_of_lading", file="c", doc_no=Cell(raw="EXSHTAO26027846", value="exshtao26027846")),
    ]


def _hs(lines=1):
    return [HSResult(line=i, status="자동 확정", by="history", hs_code=f"40115000{i:02d}", candidates=[]) for i in range(1, lines + 1)]


def _pdf(lines=1, **kwargs):
    draft = draft_declaration(_docs(lines), [], _hs(lines))
    return draft, render_declaration_pdf(draft, now=NOW, **kwargs)


def _text(pdf: bytes) -> str:
    return "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf)).pages)


def test_PDF가_만들어진다():
    _, pdf = _pdf()
    assert pdf.startswith(b"%PDF-")
    assert len(PdfReader(io.BytesIO(pdf)).pages) == 1


def test_한글_글꼴이_PDF_안에_들어간다():
    _, pdf = _pdf()
    assert b"/FontFile2" in pdf  # TrueType 글꼴을 PDF에 넣었다 (뷰어에 글꼴이 없어도 한글이 깨지지 않는다)
    fonts = {f["/BaseFont"].split("+")[-1] for page in PdfReader(io.BytesIO(pdf)).pages for f in _page_fonts(page)}
    assert "NanumGothic" in fonts


def _page_fonts(page):
    resources = page["/Resources"]
    return [font.get_object() for font in resources["/Font"].get_object().values()]


def test_글꼴_파일과_라이선스가_저장소에_있다():
    for name in ("NanumGothic-Regular.ttf", "NanumGothic-Bold.ttf", "OFL.txt"):
        assert (FONT_DIR / name).stat().st_size > 1000
    assert "SIL Open Font License" in (FONT_DIR / "OFL.txt").read_text(encoding="utf-8")


def test_제목과_사람_검토_전_초안_표시가_있다():
    _, pdf = _pdf()
    text = _text(pdf)
    assert PDF_TITLE in text
    assert PDF_NOTICE in text
    assert "사람 검토 전 초안" in text


def test_채운_칸은_값과_출처를_보인다():
    draft, pdf = _pdf()
    text = _text(pdf)
    assert "EXSHTAO26027846" in text and "bill_of_lading.bl_no" in text
    assert "6,250.5" in text  # 숫자는 천 단위 쉼표
    assert "commercial_invoice.items[0].qty" in text
    assert "4011500001" in text and "hs[0].hs_code" in text
    assert len(draft.fields) > 3


def test_비운_칸은_비움으로_보인다():
    draft, pdf = _pdf()
    text = _text(pdf)
    assert text.count(BLANK_MARK) >= len(draft.blank_fields) - 1  # 범례 문장 속 표시를 빼고 칸마다 하나씩
    assert f"비운 칸은 {len(draft.blank_fields)}개" in text


def test_모든_칸_이름이_나온다():
    _, pdf = _pdf()
    text = _text(pdf)
    for label, _ in DECLARATION_FIELDS:
        assert label in text


def test_만든_시각은_한국_시간이다():
    utc = datetime(2026, 11, 20, 23, 5, tzinfo=ZoneInfo("UTC"))  # Lambda 시계(UTC). 한국은 다음 날 08시
    draft = draft_declaration(_docs(), [], _hs())
    assert "2026-11-21 08:05" in _text(render_declaration_pdf(draft, now=utc))


def test_작업_ID를_적는다():
    _, pdf = _pdf(job_id="J-20261121-001")
    assert "J-20261121-001" in _text(pdf)


def test_품목이_여러_줄이면_줄마다_표를_만든다():
    _, pdf = _pdf(lines=3)
    text = _text(pdf)
    for n in (1, 2, 3):
        assert f"품목 {n}행" in text
        assert f"Bicycle Tyre {n}" in text
    assert "4011500003" in text


def test_품목이_많으면_여러_쪽이_된다():
    _, pdf = _pdf(lines=12)
    pages = PdfReader(io.BytesIO(pdf)).pages
    assert len(pages) > 1
    assert "2쪽" in pages[1].extract_text()
    assert "품목 12행" in _text(pdf)


def test_HS_칸의_줄_번호는_HS_결과의_줄을_따른다():
    """HS 결과가 3행부터 있으면 hs[0]은 3행 HS다. hs를 넘기면 그 줄에 놓는다."""
    docs = _docs(lines=3)
    hs = [HSResult(line=3, status="자동 확정", by="history", hs_code="4011500003", candidates=[])]
    draft = draft_declaration(docs, [], hs)
    text = _text(render_declaration_pdf(draft, hs=hs, now=NOW))
    row3 = text.split("품목 3행")[1]
    assert "4011500003" in row3
    assert "4011500003" not in text.split("품목 3행")[0]


def test_서류_글자의_표시_문자는_해석하지_않는다():
    """서류에 적힌 <b>, <img src=...>, & 같은 글자는 데이터로만 찍는다 (표시로 해석하거나 파일·주소를 불러오지 않는다)."""
    evil = 'WIDGET <b>BOLD</b> <img src="http://example.invalid/x.png"/> <a href="http://example.invalid">link</a> & CO'
    draft = DeclarationDraft(
        fields=[DeclarationField(name="품명", value=evil, source="commercial_invoice.items[0].name")], blank_fields=[]
    )
    pdf = render_declaration_pdf(draft, job_id="<i>J1</i> & x", now=NOW)
    text = " ".join(_text(pdf).split())  # 긴 글이 칸 너비에서 줄바꿈되므로 공백을 하나로 맞춘 뒤 본다
    assert "<b>BOLD</b>" in text  # 굵게 표시가 되지 않고 글자 그대로 찍힌다
    assert '<img src="http://example.invalid/x.png"/>' in text
    assert '<a href="http://example.invalid">link</a> & CO' in text
    assert "<i>J1</i> & x" in text  # 작업 ID가 이중으로 이스케이프되지 않는다
    assert "&amp;" not in text and "&lt;" not in text
    assert b"/URI" not in pdf and b"/Annots" not in pdf  # 링크로 해석되지 않았다
    assert b"example.invalid" not in pdf or b"/URI" not in pdf


def test_서류에_없는_긴_글자는_잘라서_찍는다():
    long_text = "A" * 5000
    draft = DeclarationDraft(
        fields=[DeclarationField(name="품명", value=long_text, source="commercial_invoice.items[0].name")], blank_fields=[]
    )
    text = _text(render_declaration_pdf(draft, now=NOW))
    assert text.count("A") == 300  # 칸 너비에서 줄이 바뀌어도 찍힌 글자는 정확히 300자
    assert "…" in text


def test_제어_문자와_줄바꿈은_한_줄로_정리한다():
    draft = DeclarationDraft(
        fields=[DeclarationField(name="품명", value="LINE1\nLINE2\x00\x07 END", source="commercial_invoice.items[0].name")],
        blank_fields=[],
    )
    text = _text(render_declaration_pdf(draft, now=NOW))
    assert "LINE1 LINE2 END" in text.replace("\n", " ")


def test_빈_초안도_PDF가_된다():
    pdf = render_declaration_pdf(DeclarationDraft(fields=[], blank_fields=[]), now=NOW)
    text = _text(pdf)
    assert PDF_NOTICE in text and "품목 칸이 없습니다" in text
    assert text.count(BLANK_MARK) >= len(DECLARATION_FIELDS[:13])  # 서류 전체 칸 13개는 모두 비움


def test_같은_입력이면_같은_PDF가_나온다():
    draft = draft_declaration(_docs(2), [], _hs(2))
    assert render_declaration_pdf(draft, now=NOW) == render_declaration_pdf(draft, now=NOW)


def test_만들기_전에_도구_호출을_남긴다(capsys):
    draft = draft_declaration(_docs(), [], _hs())
    capsys.readouterr()
    render_declaration_pdf(draft, now=NOW)
    assert "[tool] render_declaration_pdf" in capsys.readouterr().out


@pytest.mark.parametrize("value", [0, 0.0, 6250, 1234567.891, "한글 품명 テスト", "ABC"])
def test_여러_값_모양을_그린다(value):
    draft = DeclarationDraft(
        fields=[DeclarationField(name="결제금액", value=value, source="commercial_invoice.total_amount")], blank_fields=[]
    )
    assert render_declaration_pdf(draft, now=NOW).startswith(b"%PDF-")
