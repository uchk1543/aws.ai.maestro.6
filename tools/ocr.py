"""ocr_document, PDF 쪽 그림, 칸 위치 찾기. 담당: 서버. 규칙: .kiro/steering/agent-design.md 4번, 형식: docs/schema.md

OCR 자체는 Amazon Textract(DetectDocumentText, 동기)가 한다. 여기서는 호출하고 결과를 OcrResult로 바꾸기만 한다 (B4, F10 #188).
처리 Lambda(api/worker.py)가 서류마다 매번 부른다. 결과는 두 곳에 쓴다.
  1. 다시 확인(reread_field)의 두 번째 근거 (스캔본·사진, checked_by: textract)
  2. 서류 보기(GET /api/jobs/{id}/files)의 칸 위치 marks (locate_marks)
PDF는 쪽마다 그림(JPEG)으로 그려(pypdfium2) 그 그림을 OCR 한다. 같은 그림을 화면이 쪽 그림(pages)으로 띄우므로
박스 위치(0~1 비율)가 그림과 정확히 맞는다. 권한은 infra/policy-textract.json (team06-worker-role에만, F4).
"""

import io
import os
import re
from dataclasses import dataclass
from functools import cache
from pathlib import PurePath
from typing import Protocol

from tools.models import DocMark, OcrLine, OcrResult, ReadField

MAX_PAGES = 5  # PDF는 앞 5쪽만 그리고 OCR 한다 (쪽당 과금, 처리 Lambda 시간)
MAX_BYTES = 10_000_000  # Textract 동기 API 한 번에 보낼 수 있는 크기
TIMEOUT_SECONDS = 5  # team.md: 외부 API 타임아웃 5초, 재시도 1회
RENDER_DPI = 150  # PDF 쪽 그림 해상도. A4 가 약 1240×1754 px
JPEG_QUALITY = 85


class TextractClient(Protocol):
    """boto3 textract 클라이언트에서 쓰는 부분만. 테스트에서는 가짜로 바꾼다."""

    def detect_document_text(self, **kwargs) -> dict: ...

    def analyze_document(self, **kwargs) -> dict: ...  # 표·양식(Forms)이 필요해지면 쓴다 (약속: tests/unit/test_contracts.py)


@dataclass(frozen=True)
class PageImage:
    """PDF 한 쪽을 그린 그림."""

    data: bytes  # JPEG
    width: int
    height: int


@cache
def _client() -> TextractClient:
    import boto3
    from botocore.config import Config

    config = Config(
        connect_timeout=TIMEOUT_SECONDS,
        read_timeout=TIMEOUT_SECONDS,
        retries={"total_max_attempts": 2, "mode": "standard"},  # 처음 한 번 + 재시도 1회
    )
    return boto3.client("textract", region_name=os.environ.get("AWS_REGION", "ap-northeast-2"), config=config)


def is_pdf(file: str) -> bool:
    return PurePath(file).suffix.lower() == ".pdf"


def render_pages(data: bytes, *, max_pages: int | None = None) -> list[PageImage]:
    """PDF를 쪽마다 JPEG 그림으로 그린다 (pypdfium2, 모델 호출 없음).

    언제: 처리 Lambda가 PDF 서류마다. 그림은 OCR 에 보내고, S3 에 두어 화면이 쪽 그림으로 띄운다.
    받는 것: PDF 바이트. 반환: 앞 max_pages(기본 MAX_PAGES)쪽의 그림. 깨진 PDF면 예외를 올린다.
    """
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(data)
    try:
        pages = []
        for i in range(min(len(pdf), max_pages or MAX_PAGES)):
            image = pdf[i].render(scale=RENDER_DPI / 72).to_pil().convert("RGB")
            out = io.BytesIO()
            image.save(out, format="JPEG", quality=JPEG_QUALITY)
            pages.append(PageImage(data=out.getvalue(), width=image.width, height=image.height))
        return pages
    finally:
        pdf.close()


def ocr_document(
    file: str, data: bytes, *, client: TextractClient | None = None, pages: list[bytes] | None = None
) -> OcrResult:
    """서류 한 장을 Textract로 OCR한다.

    언제: 처리 Lambda가 서류마다 매번(F10 #188). 결과는 다시 확인의 두 번째 근거와 칸 위치(marks)에 쓴다.
    받는 것: file(S3 키), data(파일 바이트), client(테스트용 가짜 Textract),
             pages(PDF를 미리 그린 쪽 그림. 주면 그 그림을 OCR 하고, 없으면 PDF는 여기서 그린다).
    반환: OcrResult. 글자 줄(LINE)마다 쪽 번호와 위치(left, top, width, height, 쪽에 대한 0~1 비율). 표는 담지 않는다.
    타임아웃 5초, 재시도 1회. 실패하면 예외를 그대로 올린다 (부른 쪽이 그 서류만 OCR 없이 진행한다).
    """
    print(f"[tool] ocr_document file={file} bytes={len(data)}")
    client = client or _client()
    if pages is None:
        pages = [p.data for p in render_pages(data)] if is_pdf(file) else [data]
    lines: list[OcrLine] = []
    for number, page in enumerate(pages, start=1):
        if len(page) > MAX_BYTES:
            raise ValueError(f"Textract 동기 한도를 넘습니다 ({len(page):,}바이트, 최대 {MAX_BYTES:,})")
        response = client.detect_document_text(Document={"Bytes": page})
        for block in response.get("Blocks", []):
            if block.get("BlockType") != "LINE" or not block.get("Text"):
                continue
            box = block["Geometry"]["BoundingBox"]
            lines.append(OcrLine(page=number, text=block["Text"], bbox=(box["Left"], box["Top"], box["Width"], box["Height"])))
    print(f"[tool] ocr_document file={file} 쪽 {len(pages)}, 줄 {len(lines)}개")
    return OcrResult(file=file, lines=lines)


# ---------------------------------------------------------------------------
# 칸 위치 찾기 (모델 호출 없음)
# ---------------------------------------------------------------------------
def _squash(text: str) -> str:
    """비교용: 대문자로, 공백을 뺀다. 쉼표·마침표는 남긴다 (숫자 자리를 지키려고)."""
    return "".join(ch for ch in text.upper() if not ch.isspace())


def _at(hay: str, needle: str) -> int:
    """hay 안에서 needle의 위치. 숫자로 끝나거나 시작하는 값은 더 긴 숫자의 일부로 찾지 않는다 (예: '100' 을 '1,100' 에서 찾지 않음)."""
    start = hay.find(needle)
    while start >= 0:
        end = start + len(needle)
        before = hay[start - 1] if start > 0 else ""
        after = hay[end] if end < len(hay) else ""
        # 빈 글자("")는 ",." 안에 있다고 나오므로 글자가 있을 때만 본다
        digit_edge = (needle[0].isdigit() and before != "" and (before.isdigit() or before in ",.")) or (
            needle[-1].isdigit() and after != "" and (after.isdigit() or (after in ",." and hay[end + 1:end + 2].isdigit()))
        )
        if not digit_edge:
            return start
        start = hay.find(needle, start + 1)
    return -1


class _Finder:
    """OCR 글자 줄에서 글자를 찾아 위치를 준다. 같은 값이 여러 줄에 있으면 아직 쓰지 않은 줄을 먼저 쓴다."""

    def __init__(self, ocr: OcrResult):
        self.lines = ocr.lines
        self.squashed = [_squash(line.text) for line in ocr.lines]
        self.used: set[int] = set()

    def find(self, text: str) -> tuple[OcrLine, list[float]] | None:
        needle = _squash(text)
        if len(needle) < 2:
            return None
        hits = [(i, at) for i, hay in enumerate(self.squashed) if (at := _at(hay, needle)) >= 0]
        if not hits:
            return None
        # 쓰지 않은 줄 → 값만 있는(짧은) 줄 → 위쪽 줄 순서
        i, at = min(hits, key=lambda h: (h[0] in self.used, len(self.squashed[h[0]]), h[0]))
        self.used.add(i)
        line, hay = self.lines[i], self.squashed[i]
        left, top, width, height = line.bbox
        start, span = at / len(hay), len(needle) / len(hay)
        # 이름표와 같은 줄이면 글자 위치 비율로 좁힌다 (근사)
        return line, [left + width * start, top, width * span, height]


_TITLE = re.compile(r"제목\s+([^,·(]+?)\s*(?=,|\(|$)")
_FEATURES = re.compile(r"([^,]+?)\s*칸")


def reason_parts(reason: str) -> tuple[str | None, list[str]]:
    """분류 근거 한 줄에서 제목과 특징 칸 이름을 뽑는다. 예: '제목 PACKING LIST, N.W.·G.W. 칸' → ('PACKING LIST', ['N.W.', 'G.W.']).

    근거는 분류 프롬프트(tools/extract.py classify_prompt)가 정한 모양이다: 제목 그대로와 특징 칸 이름 두세 개.
    """
    title = _TITLE.search(reason)
    if not title:  # 제목을 못 찾은 근거(unknown·분류 실패)는 칸 이름도 뽑지 않는다
        return None, []
    title_text, rest = title.group(1).strip(), reason[title.end():]
    features: list[str] = []
    for part in _FEATURES.findall(rest):
        features += [x.strip(" ()") for x in re.split(r"[·/]", part) if x.strip(" ()")]
    return title_text, features


def locate_marks(fields: list[ReadField], ocr: OcrResult, reason: str = "") -> list[DocMark]:
    """서류 위 표시를 OCR 글자에서 찾아 위치를 준다 (F10 #188). 모델 호출 없음.

    언제: GET /jobs/{id}/files 가 marks 를 채울 때.
    받는 것: 서류 한 장의 읽은 칸(ReadField), 그 서류의 OcrResult, 분류 근거 한 줄.
    반환: 찾은 것만 DocMark 로. 분류 근거의 제목(kind=title)·특징 칸(feature), 읽은 칸의 raw(field). 못 찾으면 뺀다.
    """
    finder = _Finder(ocr)
    marks: list[DocMark] = []
    title, features = reason_parts(reason)
    if title and (hit := finder.find(title)):
        marks.append(DocMark(kind="title", label="제목", text=hit[0].text, page=hit[0].page, bbox=hit[1]))
    for name in features:
        if hit := finder.find(name):
            marks.append(DocMark(kind="feature", label="특징 칸", text=name, page=hit[0].page, bbox=hit[1]))
    for field in fields:
        if field.raw and (hit := finder.find(field.raw)):
            marks.append(DocMark(kind="field", label=field.label, text=field.raw, field=field.field, page=hit[0].page, bbox=hit[1]))
    return marks
