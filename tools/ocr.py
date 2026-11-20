"""ocr_document, PDF 쪽 그림, 칸 위치 찾기. 담당: 서버. 규칙: .kiro/steering/agent-design.md 4번, 형식: docs/schema.md

OCR 자체는 Amazon Textract(DetectDocumentText, 동기)가 한다. 여기서는 호출하고 결과를 OcrResult로 바꾸기만 한다 (B4, F10 #188).
처리 Lambda(api/worker.py)가 서류마다 매번 부른다. 결과는 두 곳에 쓴다.
  1. 다시 확인(reread_field)의 두 번째 근거 (스캔본·사진, checked_by: textract)
  2. 서류 보기(GET /api/jobs/{id}/files)의 칸 위치 marks (locate_marks)
PDF는 쪽마다 그림(JPEG)으로 그려(pypdfium2) 그 그림을 OCR 한다. 같은 그림을 화면이 쪽 그림(pages)으로 띄우므로
박스 위치(0~1 비율)가 그림과 정확히 맞는다. 권한은 infra/policy-textract.json (team06-worker-role에만, F4).
"""

import io
import hashlib
import os
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from pathlib import PurePath
from typing import Protocol

from tools.models import Classification, DocMark, OcrLine, OcrResult, ReadField

MAX_PAGES = 5  # PDF는 앞 5쪽만 그리고 OCR 한다 (쪽당 과금, 처리 Lambda 시간)
MAX_BYTES = 10_000_000  # Textract 동기 API 한 번에 보낼 수 있는 크기
TIMEOUT_SECONDS = 5  # team.md: 외부 API 타임아웃 5초, 재시도 1회
RENDER_DPI = 150  # PDF 쪽 그림 해상도. A4 가 약 1240×1754 px
MAX_SIDE_PX = 3000  # 쪽 그림 긴 변 상한 (큰 용지 PDF 로 메모리가 바닥나지 않게, #194 리뷰)
JPEG_QUALITY = 85
# Textract 동기 API 계정 한도: 서울 리전 DetectDocumentText·AnalyzeDocument 초당 1건 (service-quotas, 2026-11-20 확인).
# 처리 Lambda 는 서류마다 스레드로 OCR 하므로, 한 컨테이너 안에서 호출 사이를 이만큼 띄운다. 한도를 올리면 TEXTRACT_TPS 로 바꾼다
TEXTRACT_MIN_INTERVAL = 1.0 / float(os.environ.get("TEXTRACT_TPS", "1"))
_PACE_LOCK = threading.Lock()
_last_call = 0.0


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


# boto3 기본 세션은 스레드에 안전하지 않다. 처리 Lambda 는 서류마다 스레드로 OCR 하므로 클라이언트는 이 잠금 안에서 한 번만 만든다
_CLIENT_LOCK = threading.Lock()


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


def _pace() -> None:
    """Textract 호출 사이를 TEXTRACT_MIN_INTERVAL 이상 띄운다 (한 프로세스 안, 스레드끼리). 한도 초과(Throttling)로 OCR 이 빠지지 않게."""
    global _last_call
    with _PACE_LOCK:
        wait = _last_call + TEXTRACT_MIN_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()


def is_pdf(file: str) -> bool:
    return PurePath(file).suffix.lower() == ".pdf"


def page_scale(width_pt: float, height_pt: float) -> float:
    """PDF 쪽(포인트 단위)을 그릴 배율. RENDER_DPI 로 그리되 긴 변이 MAX_SIDE_PX 를 넘지 않게 줄인다.

    용지가 아주 큰 PDF(포스터 크기)를 150dpi 로 그리면 픽셀이 수억 개가 되어 Lambda 메모리가 바닥난다 (#194 리뷰).
    """
    scale = RENDER_DPI / 72
    longest = max(width_pt, height_pt, 1.0)
    return min(scale, MAX_SIDE_PX / longest)


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
            page = pdf[i]
            image = page.render(scale=page_scale(*page.get_size())).to_pil().convert("RGB")
            out = io.BytesIO()
            image.save(out, format="JPEG", quality=JPEG_QUALITY)
            pages.append(PageImage(data=out.getvalue(), width=image.width, height=image.height))
        return pages
    finally:
        pdf.close()


def upright_image(data: bytes) -> PageImage | None:
    """휴대폰 사진처럼 EXIF 회전 표시가 있는 그림을 똑바로 세운 JPEG 를 돌려준다. 회전이 없으면 None.

    브라우저는 EXIF 회전대로 그림을 돌려 그리는데, 칸 위치(bbox)는 OCR 한 그림 기준이다 (#194 리뷰).
    회전이 있으면 이 그림을 OCR 하고 화면도 이 그림을 띄워 박스와 그림의 방향을 맞춘다. 못 읽는 그림이면 None.
    """
    from PIL import Image, ImageOps

    try:
        with Image.open(io.BytesIO(data)) as img:
            if img.getexif().get(0x0112, 1) in (1, 0):
                return None
            image = ImageOps.exif_transpose(img).convert("RGB")
    except Exception as exc:  # 그림이 아니거나 깨짐: 원본을 그대로 OCR 한다
        print(f"[warn] upright_image {type(exc).__name__}: {exc}")
        return None
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=JPEG_QUALITY)
    return PageImage(data=out.getvalue(), width=image.width, height=image.height)


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
    if client is None:
        with _CLIENT_LOCK:
            client = _client()
    if pages is None:
        pages = [p.data for p in render_pages(data)] if is_pdf(file) else [data]
    lines: list[OcrLine] = []
    for number, page in enumerate(pages, start=1):
        if len(page) > MAX_BYTES:
            raise ValueError(f"Textract 동기 한도를 넘습니다 ({len(page):,}바이트, 최대 {MAX_BYTES:,})")
        _pace()
        response = client.detect_document_text(Document={"Bytes": page})
        for block in response.get("Blocks", []):
            if block.get("BlockType") != "LINE" or not block.get("Text"):
                continue
            box = block["Geometry"]["BoundingBox"]
            lines.append(OcrLine(page=number, text=block["Text"], bbox=(box["Left"], box["Top"], box["Width"], box["Height"])))
    print(f"[tool] ocr_document file={file} 쪽 {len(pages)}, 줄 {len(lines)}개")
    return OcrResult(file=file, lines=lines)


# ---------------------------------------------------------------------------
# OCR 원본 저장과 캐시 (B4-L0, l0: 서류 전체 글자)
# 작업 줄(team06-jobs의 ocr 칸)은 DynamoDB 400KB 한도 때문에 600줄에서 자른다. 자르지 않은 결과는 S3 cache/ocr/ 에 둔다.
# 키는 파일 바이트 해시라서 같은 파일을 다시 올리면 Textract 를 다시 부르지 않는다 (데모 재현·평가 반복).

OCR_CACHE_PREFIX = "cache/ocr/"
# Textract API(DetectDocumentText)나 쪽 그림을 만드는 방식(render_pages·upright_image)이 바뀌면 올린다. 옛 저장분을 쓰지 않게 된다.
# 쪽 그림 설정 상수(MAX_PAGES·RENDER_DPI·MAX_SIDE_PX·JPEG_QUALITY)는 키에 들어가므로 바꿔도 올리지 않아도 된다
OCR_VERSION = "detect-v1"


class OcrCache(Protocol):
    """OCR 저장소. 값은 OcrResult JSON 문자열. 테스트에서는 메모리판으로 바꾼다."""

    def get(self, key: str) -> str | None: ...

    def put(self, key: str, value: str) -> None: ...


class S3OcrCache:
    """S3 판 OCR 저장소. DOCS_BUCKET 의 cache/ocr/<ocr_cache_key>.json. 권한: infra/policy-textract.json (worker 만)."""

    def __init__(self, bucket: str, client=None):
        self.bucket = bucket
        self._client = client

    def _s3(self):
        if self._client is None:
            with _CLIENT_LOCK:
                self._client = _s3_client()
        return self._client

    def get(self, key: str) -> str | None:
        try:
            return self._s3().get_object(Bucket=self.bucket, Key=f"{OCR_CACHE_PREFIX}{key}.json")["Body"].read().decode("utf-8")
        except Exception as exc:  # 없는 키는 그냥 없음. 다른 오류도 캐시 없이 OCR 하게 한다
            code = getattr(exc, "response", {}).get("Error", {}).get("Code")
            # ListBucket 권한이 없으면 없는 키도 403(AccessDenied)이다. 진짜 권한 문제는 put 실패 경고로 드러난다
            if code not in ("NoSuchKey", "404", "AccessDenied", "403"):
                print(f"[warn] ocr_cache get 실패: {type(exc).__name__}: {exc}")
            return None

    def put(self, key: str, value: str) -> None:
        self._s3().put_object(
            Bucket=self.bucket, Key=f"{OCR_CACHE_PREFIX}{key}.json", Body=value.encode("utf-8"), ContentType="application/json"
        )


@cache
def _s3_client():
    """OCR 저장소가 쓰는 S3 클라이언트. 모든 S3OcrCache 가 하나를 같이 쓴다 (부르는 쪽이 _CLIENT_LOCK 을 잡는다)."""
    import boto3
    from botocore.config import Config

    config = Config(connect_timeout=TIMEOUT_SECONDS, read_timeout=TIMEOUT_SECONDS, retries={"total_max_attempts": 2, "mode": "standard"})
    return boto3.client("s3", config=config)


def default_ocr_cache() -> OcrCache | None:
    """환경 변수로 정한 OCR 저장소. NO_CACHE=1 이거나 DOCS_BUCKET 이 없으면 None(저장·재사용 안 함)."""
    if os.environ.get("NO_CACHE") == "1":
        return None
    bucket = os.environ.get("DOCS_BUCKET")
    return S3OcrCache(bucket) if bucket else None


def ocr_cache_key(data: bytes) -> str:
    """OCR 캐시 키. 파일 바이트·OCR_VERSION·쪽 그림 설정(쪽 수 상한·해상도·긴 변 상한·JPEG 품질) 중 하나라도 다르면 다른 키다."""
    parts = [hashlib.sha256(data).hexdigest(), OCR_VERSION, str(MAX_PAGES), str(RENDER_DPI), str(MAX_SIDE_PX), str(JPEG_QUALITY)]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def ocr_cached(
    file: str,
    data: bytes,
    *,
    pages: list[bytes] | None = None,
    cache: OcrCache | None = None,
    run: Callable[..., OcrResult] = ocr_document,
) -> OcrResult:
    """같은 파일이면 저장해 둔 OCR 을 쓰고, 없으면 OCR 해서 자르지 않고 저장한다.

    언제: 처리 Lambda 가 서류마다 (api/worker.py 의 ocr_one).
    받는 것: file(S3 키), data(파일 바이트), pages(ocr_document 에 넘길 쪽 그림), cache(저장소, None 이면 저장·재사용 안 함),
             run(실제 OCR 함수. 기본 ocr_document, 테스트·부른 쪽이 바꿀 수 있다).
    반환: OcrResult. 저장분이면 file 만 지금 키로 바꾼다. 저장소 오류는 OCR 을 막지 않는다.
    글자 줄이 하나도 없는 결과는 저장하지도 쓰지도 않는다 (잠깐의 오류가 그 파일에 영원히 남지 않게).
    """
    key = ocr_cache_key(data) if cache is not None else None
    if key is not None:
        try:
            hit = cache.get(key)
        except Exception as exc:
            print(f"[warn] ocr_cache get 실패: {type(exc).__name__}: {exc}")
            hit = None
        if hit is not None:
            try:
                res = OcrResult.model_validate_json(hit)
            except ValueError as exc:
                print(f"[warn] ocr_cache 값이 형식에 안 맞아 새로 OCR: {type(exc).__name__}")
            else:
                if res.lines:
                    print(f"[tool] ocr_document file={file} 저장분 사용 key={key[:12]} 줄 {len(res.lines)}개")
                    return res.model_copy(update={"file": file})
    res = run(file, data, pages=pages)
    if key is not None and res.lines:
        try:
            cache.put(key, res.model_dump_json())
        except Exception as exc:
            print(f"[warn] ocr_cache put 실패: {type(exc).__name__}: {exc}")
    return res


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


# ---------------------------------------------------------------------------
# Textract 글자로 서류 종류 고르기 (비용 줄이기: 서류마다 Bedrock 분류 호출 하나를 줄인다)
# 근거: 개발용 24세트 92장(pdf·png·스캔본, 스타일 1·2, 원산지증명서 KCFTA·AK·VK)에서 92/92. 실험은 B4-L0 이슈에 적었다.
# 확신이 없으면 None 을 돌려주고 부른 쪽이 모델로 분류한다 (제목이 없음, 위쪽에 없음, 두 종류 제목이 비슷함).

_TITLES: dict[str, str] = {
    "commercial_invoice": r"^\s*COMMERCIAL\s+INVOICE\s*$",
    "packing_list": r"^\s*PACKING\s+LIST\s*$",
    "bill_of_lading": r"^\s*(OCEAN\s+|COMBINED\s+TRANSPORT\s+)?BILL\s+OF\s+LADING\s*$",
    "certificate_of_origin": r"^\s*CERTIFICATE\s+OF\s+ORIGIN\b",
}
TITLE_MAX_TOP = 0.3  # 제목은 첫 쪽 위쪽 30% 안에 있다
TITLE_MARGIN = 1.3  # 1등 제목 글자 높이가 2등의 1.3배는 되어야 확신한다


def classify_from_ocr(ocr: OcrResult | None) -> Classification | None:
    """Textract 글자에서 서류 제목 줄을 찾아 서류 종류를 고른다. 모델 호출 없음.

    언제: 처리 Lambda 가 분류할 때 모델보다 먼저 (CLASSIFY_BY_OCR=1, api/worker.py).
    받는 것: 그 서류의 OcrResult (없으면 None).
    반환: Classification(종류, 근거 '제목 ... (Textract)'), 확신이 없으면 None (부른 쪽이 모델로 분류한다).
    """
    if ocr is None:
        return None
    best: dict[str, OcrLine] = {}
    for line in ocr.lines:
        if line.page != 1 or line.bbox[1] > TITLE_MAX_TOP:
            continue
        for doc_type, pattern in _TITLES.items():
            if re.search(pattern, line.text, re.I) and (doc_type not in best or line.bbox[3] > best[doc_type].bbox[3]):
                best[doc_type] = line
    if not best:
        return None
    ranked = sorted(best.items(), key=lambda kv: kv[1].bbox[3], reverse=True)
    if len(ranked) > 1 and ranked[0][1].bbox[3] < ranked[1][1].bbox[3] * TITLE_MARGIN:
        return None
    doc_type, line = ranked[0]
    return Classification(doc_type=doc_type, reason=f"제목 '{line.text.strip()}' (Textract 글자, 모델 호출 없음)")
