"""큰 이미지 줄여 읽기 단위 테스트 (B10 #148). Pillow로 만든 진짜 이미지를 쓴다. 모델·AWS 호출 없음.

Bedrock Converse 이미지 블록 한도는 3.75MB·가로세로 8000px이다(문서 PDF는 4.5MB). 휴대폰 사진은 대부분 이보다 크다.
"""

import io
import os

import pytest
from PIL import Image

from agent import document_agent
from agent.document_agent import MAX_BYTES, MAX_IMAGE_BYTES, run_job
from tools import extract
from tools.extract import IMAGE_LIMIT_BYTES, IMAGE_LIMIT_SIDE, ReadError, content_blocks, shrink_image
from tools.models import Classification, RawDocument


def noise_jpeg(w: int = 4000, h: int = 3000, *, orientation: int | None = None) -> bytes:
    """잡음이라 거의 압축되지 않는 JPEG. 4000×3000이면 10MB 안팎(휴대폰 사진 크기)."""
    img = Image.frombytes("RGB", (w, h), os.urandom(w * h * 3))
    buf = io.BytesIO()
    if orientation is None:
        img.save(buf, "JPEG", quality=90)
    else:
        exif = Image.Exif()
        exif[0x0112] = orientation  # Orientation. 6 = 90도 돌려 보아야 바로 선 사진
        img.save(buf, "JPEG", quality=90, exif=exif.tobytes())
    return buf.getvalue()


def image_of(block: dict) -> Image.Image:
    return Image.open(io.BytesIO(block["image"]["source"]["bytes"]))


@pytest.fixture(scope="module")
def photo() -> bytes:
    data = noise_jpeg()
    assert 8_000_000 < len(data) < 14_000_000  # 10MB 안팎
    return data


def test_big_phone_photo_fits_bedrock_image_limits(photo):
    [block] = content_blocks("uploads/s1/photo.jpg", photo)
    data = block["image"]["source"]["bytes"]
    assert block["image"]["format"] == "jpeg"
    assert len(data) <= IMAGE_LIMIT_BYTES == 3_750_000
    assert max(image_of(block).size) <= 2400 <= IMAGE_LIMIT_SIDE  # 글자가 읽힐 해상도부터 시작한다


def test_shrink_result_is_reused_for_the_same_bytes(photo):
    """분류·읽기·다시 확인이 같은 파일을 쓰므로 한 번만 줄인다."""
    first, again = shrink_image("photo.jpg", photo), shrink_image("photo.jpg", photo)
    assert first is again and first.before == len(photo) and first.side == 2400


def test_exif_rotation_is_applied_before_shrinking():
    [block] = content_blocks("photo.jpg", noise_jpeg(orientation=6))
    assert image_of(block).size == (1800, 2400)  # 가로 사진이 세로로 바로 선다


def test_big_png_with_alpha_becomes_jpeg():
    w, h = 2200, 2200
    img = Image.frombytes("RGBA", (w, h), os.urandom(w * h * 4))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    assert len(buf.getvalue()) > IMAGE_LIMIT_BYTES
    [block] = content_blocks("scan.png", buf.getvalue())
    assert block["image"]["format"] == "jpeg" and image_of(block).mode == "RGB"
    assert len(block["image"]["source"]["bytes"]) <= IMAGE_LIMIT_BYTES


def test_small_image_is_sent_as_is():
    buf = io.BytesIO()
    Image.new("RGB", (800, 600), "white").save(buf, "PNG")
    [block] = content_blocks("small.png", buf.getvalue())
    assert block["image"] == {"format": "png", "source": {"bytes": buf.getvalue()}}
    assert shrink_image("small.png", buf.getvalue()) is None


def test_too_many_pixels_is_shrunk_even_if_bytes_are_small():
    buf = io.BytesIO()
    Image.new("RGB", (9000, 300), "white").save(buf, "PNG")
    assert len(buf.getvalue()) < IMAGE_LIMIT_BYTES
    [block] = content_blocks("long.png", buf.getvalue())
    assert max(image_of(block).size) <= IMAGE_LIMIT_SIDE


def test_unreadable_image_is_sent_as_is_when_small_and_refused_when_big():
    assert content_blocks("bl.jpg", b"x")[0]["image"]["source"]["bytes"] == b"x"  # 작으면 지금처럼 그대로 (모델이 판단)
    with pytest.raises(ReadError, match="이미지를 열지 못해"):
        content_blocks("broken.jpg", b"x" * (IMAGE_LIMIT_BYTES + 1))


def test_pdf_is_not_touched():
    data = b"%PDF-1.4 " + b"x" * 100
    assert content_blocks("doc.pdf", data)[0]["document"]["source"]["bytes"] == data
    assert shrink_image("doc.pdf", data) is None


# ---------------------------------------------------------------------------
# 처리 흐름 (run_job): 이미지 한도 20MB, PDF는 4.5MB 그대로, 줄인 크기를 단계 기록에
# ---------------------------------------------------------------------------
def fake_models(seen: list):
    def classifier(blocks, prompt):
        seen.append(blocks[0])
        return Classification(doc_type="commercial_invoice", reason="제목 COMMERCIAL INVOICE")

    def reader(blocks, prompt):
        seen.append(blocks[0])
        return RawDocument.model_validate({"doc_no": {"raw": "INV-1"}, "total_gross_kg": {"raw": "6,250 KGS"}})

    return classifier, reader


def test_run_job_reads_big_photo_and_records_shrink(photo):
    seen: list = []
    classifier, reader = fake_models(seen)
    job = run_job("job-1", [{"key": "uploads/s1/photo.jpg", "doc_type": None}], lambda key: photo,
                  reader=reader, classifier=classifier)
    [shrunk] = [s for s in job.steps if s.tool == "shrink_image"]
    after = shrink_image("photo.jpg", photo)
    assert shrunk.ok and shrunk.summary == f"photo.jpg {len(photo) / 1e6:.1f}MB → {len(after.data) / 1e6:.1f}MB(2400px)로 줄여 읽음"
    assert [s.tool for s in job.steps].index("shrink_image") < [s.tool for s in job.steps].index("classify_document")
    assert len(seen) == 2 and all(b["image"]["format"] == "jpeg" and len(b["image"]["source"]["bytes"]) <= IMAGE_LIMIT_BYTES for b in seen)
    assert any(s.tool == "read_document" and s.ok for s in job.steps)


def test_run_job_size_limits_by_kind():
    assert (MAX_BYTES, MAX_IMAGE_BYTES) == (4_500_000, 20_000_000)  # 화면 G13(#149)과 같은 값
    seen: list = []
    classifier, reader = fake_models(seen)
    files = [{"key": "uploads/s1/big.pdf", "doc_type": None}, {"key": "uploads/s1/huge.jpg", "doc_type": None}]
    sizes = {"uploads/s1/big.pdf": MAX_BYTES + 1, "uploads/s1/huge.jpg": MAX_IMAGE_BYTES + 1}
    job = run_job("job-1", files, lambda key: b"x" * sizes[key], reader=reader, classifier=classifier)
    fails = [s.summary for s in job.steps if s.tool == "classify_document" and not s.ok]
    assert fails == [
        f"big.pdf 분류 실패: 파일이 너무 큽니다 ({MAX_BYTES + 1:,}바이트, 최대 {MAX_BYTES:,})",
        f"huge.jpg 분류 실패: 파일이 너무 큽니다 ({MAX_IMAGE_BYTES + 1:,}바이트, 최대 {MAX_IMAGE_BYTES:,})",
    ]
    assert seen == []  # 모델을 부르지 않았다


def test_extract_constants_are_bedrock_limits():
    assert (extract.IMAGE_LIMIT_BYTES, extract.IMAGE_LIMIT_SIDE) == (3_750_000, 8000)
    assert document_agent.MAX_BYTES == 4_500_000  # Bedrock 문서(PDF) 블록 한도
