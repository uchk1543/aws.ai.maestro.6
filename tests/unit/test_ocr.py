"""tools/ocr.py 단위 테스트 (F10 #188). Textract는 가짜로 바꾼다. PDF 쪽 그림은 실제 pypdfium2로 그린다."""

import io

import pytest
from pypdf import PdfWriter

from tools import ocr
from tools.models import OcrLine, OcrResult, ReadField


@pytest.fixture(autouse=True)
def no_pacing(monkeypatch):
    """Textract 호출 간격(초당 1건)은 간격 테스트에서만 본다."""
    monkeypatch.setattr(ocr, "TEXTRACT_MIN_INTERVAL", 0.0)


def line(text, left=0.1, top=0.1, width=0.4, height=0.02):
    return {"BlockType": "LINE", "Text": text, "Geometry": {"BoundingBox": {"Left": left, "Top": top, "Width": width, "Height": height}}}


class FakeTextract:
    def __init__(self, pages):
        self.pages = list(pages)  # 부를 때마다 앞에서 하나씩 돌려준다
        self.sent = []

    def detect_document_text(self, **kwargs):
        self.sent.append(kwargs["Document"]["Bytes"])
        return {"Blocks": [{"BlockType": "PAGE"}, *self.pages.pop(0), {"BlockType": "WORD", "Text": "X"}]}


def pdf_bytes(pages: int) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)  # A4 (pt)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def test_image_is_sent_once_and_lines_keep_page_and_bbox():
    client = FakeTextract([[line("COMMERCIAL INVOICE", 0.25, 0.05, 0.5, 0.04)]])

    res = ocr.ocr_document("uploads/a/scan.jpg", b"jpeg", client=client)

    assert client.sent == [b"jpeg"]
    assert res.file == "uploads/a/scan.jpg"
    assert res.lines == [OcrLine(page=1, text="COMMERCIAL INVOICE", bbox=(0.25, 0.05, 0.5, 0.04))]


def test_pdf_pages_are_rendered_to_jpeg_up_to_max_pages(monkeypatch):
    monkeypatch.setattr(ocr, "MAX_PAGES", 2)

    pages = ocr.render_pages(pdf_bytes(3))

    assert len(pages) == 2
    assert all(p.data[:3] == b"\xff\xd8\xff" for p in pages)  # JPEG
    # 150dpi: A4(595×842pt) → 약 1240×1754px
    assert pages[0].width == pytest.approx(595 * 150 / 72, abs=1) and pages[0].height == pytest.approx(842 * 150 / 72, abs=1)


def test_pdf_is_ocred_page_by_page_from_rendered_images(monkeypatch):
    monkeypatch.setattr(ocr, "MAX_PAGES", 2)
    client = FakeTextract([[line("PACKING LIST")], [line("TOTAL 6,520.00 KGS")]])

    res = ocr.ocr_document("uploads/a/pl.PDF", pdf_bytes(3), client=client)

    assert len(client.sent) == 2 and all(b[:3] == b"\xff\xd8\xff" for b in client.sent)
    assert [(x.page, x.text) for x in res.lines] == [(1, "PACKING LIST"), (2, "TOTAL 6,520.00 KGS")]


def test_given_pages_are_used_as_is():
    client = FakeTextract([[line("A")], [line("B")]])
    ocr.ocr_document("uploads/a/x.pdf", b"%PDF", client=client, pages=[b"p1", b"p2"])
    assert client.sent == [b"p1", b"p2"]


def test_textract_error_is_raised_to_the_caller():
    class Broken:
        def detect_document_text(self, **kwargs):
            raise RuntimeError("UnsupportedDocumentException")

    with pytest.raises(RuntimeError):
        ocr.ocr_document("uploads/a/x.png", b"png", client=Broken())


def field(path, raw):
    return ReadField(field=path, label=f"{path} 이름", raw=raw)


OCR = OcrResult(file="uploads/a/inv.png", lines=[
    OcrLine(page=1, text="COMMERCIAL INVOICE", bbox=(0.25, 0.05, 0.5, 0.04)),
    OcrLine(page=1, text="Invoice No. INV-2026-0214", bbox=(0.1, 0.15, 0.5, 0.02)),
    OcrLine(page=1, text="Description Qty Unit Price Amount G.W.", bbox=(0.1, 0.3, 0.8, 0.02)),
    OcrLine(page=1, text="6,250.00 KGS", bbox=(0.8, 0.34, 0.12, 0.02)),
    OcrLine(page=1, text="TOTAL 2,650 PCS 6,250.00 KGS", bbox=(0.1, 0.6, 0.8, 0.02)),
    OcrLine(page=1, text="1,100 PCS", bbox=(0.4, 0.7, 0.1, 0.02)),
])


def test_locate_marks_finds_value_lines_and_narrows_inside_labeled_line():
    marks = ocr.locate_marks([field("doc_no", "INV-2026-0214"), field("items[0].gross_kg", "6,250.00 KGS")], OCR)

    by = {m.field: m for m in marks}
    assert all(m.kind == "field" for m in marks) and by["doc_no"].label == "doc_no 이름"
    # 값만 있는 줄은 그 줄 그대로
    assert by["items[0].gross_kg"].bbox == pytest.approx([0.8, 0.34, 0.12, 0.02])
    # 이름표와 같은 줄이면 글자 위치 비율로 좁힌다 ("InvoiceNo.INV-2026-0214" 에서 뒤쪽 13자)
    left, top, width, _ = by["doc_no"].bbox
    assert left == pytest.approx(0.1 + 0.5 * 10 / 23) and width == pytest.approx(0.5 * 13 / 23) and top == 0.15


def test_locate_marks_uses_unused_line_for_repeated_value():
    """행 총중량과 합계 총중량이 같은 값이면 서로 다른 줄을 짚는다."""
    marks = ocr.locate_marks([field("items[0].gross_kg", "6,250.00 KGS"), field("total_gross_kg", "6,250.00 KGS")], OCR)
    assert [m.bbox[1] for m in marks] == [0.34, 0.6]


def test_locate_marks_skips_missing_unread_and_number_inside_longer_number():
    marks = ocr.locate_marks(
        [field("total_qty", "100 PCS"), field("items[0].qty", None), field("origin", "VIETNAM"), field("x", "1")], OCR,
    )
    assert marks == []  # '100 PCS' 는 '1,100 PCS' 안에서 찾지 않는다


@pytest.mark.parametrize(("reason", "title", "features"), [
    ("제목 COMMERCIAL INVOICE, Unit Price·Amount 칸", "COMMERCIAL INVOICE", ["Unit Price", "Amount"]),
    ("제목 PACKING LIST (N.W./G.W.) 칸", "PACKING LIST", ["N.W.", "G.W."]),
    ("제목 BILL OF LADING, Shipper·Consignee·Notify Party 칸", "BILL OF LADING", ["Shipper", "Consignee", "Notify Party"]),
    ("제목이 가려져 있고 칸만으로 종류를 정할 수 없음", None, []),
])
def test_reason_parts(reason, title, features):
    assert ocr.reason_parts(reason) == (title, features)


def test_locate_marks_adds_title_and_feature_from_reason():
    marks = ocr.locate_marks([field("doc_no", "INV-2026-0214")], OCR, "제목 COMMERCIAL INVOICE, Unit Price·Amount 칸")

    assert [(m.kind, m.label, m.text) for m in marks] == [
        ("title", "제목", "COMMERCIAL INVOICE"),
        ("feature", "특징 칸", "Unit Price"),
        ("feature", "특징 칸", "Amount"),
        ("field", "doc_no 이름", "INV-2026-0214"),
    ]
    assert marks[0].bbox == pytest.approx([0.25, 0.05, 0.5, 0.04])


def test_page_scale_keeps_dpi_but_caps_long_side():
    """A4 는 RENDER_DPI 그대로, 포스터 크기 PDF 는 긴 변이 MAX_SIDE_PX 가 되게 줄인다 (#194 리뷰)."""
    assert ocr.page_scale(595, 842) == ocr.RENDER_DPI / 72
    huge = ocr.page_scale(14400, 7200)  # 200in × 100in
    assert round(14400 * huge) == ocr.MAX_SIDE_PX


def test_huge_pdf_page_is_rendered_within_max_side():
    writer = PdfWriter()
    writer.add_blank_page(width=14400, height=7200)
    out = io.BytesIO()
    writer.write(out)
    [page] = ocr.render_pages(out.getvalue())
    assert max(page.width, page.height) <= ocr.MAX_SIDE_PX


def jpeg(size, orientation=None) -> bytes:
    from PIL import Image

    img = Image.new("RGB", size, "white")
    out = io.BytesIO()
    if orientation:
        exif = Image.Exif()
        exif[0x0112] = orientation
        img.save(out, format="JPEG", exif=exif)
    else:
        img.save(out, format="JPEG")
    return out.getvalue()


def test_upright_image_turns_rotated_photo_and_skips_others():
    """EXIF 회전(6: 시계 방향 90도)이 있는 사진은 세운 그림을 준다. 회전이 없거나 그림이 아니면 None."""
    turned = ocr.upright_image(jpeg((40, 20), orientation=6))
    assert (turned.width, turned.height) == (20, 40)
    assert ocr.upright_image(jpeg((40, 20))) is None
    assert ocr.upright_image(jpeg((40, 20), orientation=1)) is None
    assert ocr.upright_image(b"not an image") is None


# ---------------------------------------------------------------------------
# OCR 원본 저장과 캐시 (B4-L0): 자르지 않은 OcrResult 를 S3 cache/ocr/ 에 두고, 같은 파일이면 Textract 를 다시 부르지 않는다
# ---------------------------------------------------------------------------
class MemoryOcrCache:
    def __init__(self):
        self.items: dict[str, str] = {}

    def get(self, key):
        return self.items.get(key)

    def put(self, key, value):
        self.items[key] = value


def counting_ocr(calls):
    def run(file, data, *, client=None, pages=None):
        calls.append(file)
        return OcrResult(file=file, lines=[OcrLine(page=1, text=f"line {i}", bbox=(0.1, 0.1, 0.4, 0.02)) for i in range(700)])

    return run


def test_same_file_bytes_use_saved_ocr_without_textract():
    cache, calls = MemoryOcrCache(), []

    first = ocr.ocr_cached("uploads/a/scan.jpg", b"jpeg", cache=cache, run=counting_ocr(calls))
    again = ocr.ocr_cached("uploads/b/scan.jpg", b"jpeg", cache=cache, run=counting_ocr(calls))

    assert calls == ["uploads/a/scan.jpg"]
    assert again.file == "uploads/b/scan.jpg"  # 저장분이어도 지금 올린 파일의 키로 돌려준다
    assert again.lines == first.lines


def test_saved_ocr_keeps_every_line():
    cache = MemoryOcrCache()

    ocr.ocr_cached("uploads/a/scan.jpg", b"jpeg", cache=cache, run=counting_ocr([]))

    [saved] = cache.items.values()
    assert len(OcrResult.model_validate_json(saved).lines) == 700  # 작업 줄(ocr 칸)처럼 600줄에서 자르지 않는다


def test_different_bytes_get_different_cache_keys():
    assert ocr.ocr_cache_key(b"a") != ocr.ocr_cache_key(b"b")
    assert ocr.ocr_cache_key(b"a") == ocr.ocr_cache_key(b"a")


def test_no_cache_always_calls_textract():
    calls = []

    ocr.ocr_cached("uploads/a/scan.jpg", b"jpeg", cache=None, run=counting_ocr(calls))
    ocr.ocr_cached("uploads/a/scan.jpg", b"jpeg", cache=None, run=counting_ocr(calls))

    assert len(calls) == 2


def test_broken_cache_falls_back_to_textract():
    class Broken:
        def get(self, key):
            raise RuntimeError("AccessDenied")

        def put(self, key, value):
            raise RuntimeError("AccessDenied")

    calls = []

    res = ocr.ocr_cached("uploads/a/scan.jpg", b"jpeg", cache=Broken(), run=counting_ocr(calls))

    assert calls == ["uploads/a/scan.jpg"] and len(res.lines) == 700


def test_unreadable_saved_value_is_ignored():
    cache, calls = MemoryOcrCache(), []
    cache.items[ocr.ocr_cache_key(b"jpeg")] = "{not json"

    ocr.ocr_cached("uploads/a/scan.jpg", b"jpeg", cache=cache, run=counting_ocr(calls))

    assert calls == ["uploads/a/scan.jpg"]


def test_default_cache_is_off_with_no_cache_or_without_bucket(monkeypatch):
    monkeypatch.setenv("DOCS_BUCKET", "team06-docs-test")
    monkeypatch.setenv("NO_CACHE", "1")
    assert ocr.default_ocr_cache() is None
    monkeypatch.delenv("NO_CACHE")
    assert isinstance(ocr.default_ocr_cache(), ocr.S3OcrCache)
    monkeypatch.delenv("DOCS_BUCKET")
    assert ocr.default_ocr_cache() is None


def test_s3_cache_reads_and_writes_under_cache_ocr_prefix():
    class FakeS3:
        def __init__(self):
            self.objects = {}

        def put_object(self, *, Bucket, Key, Body, ContentType):
            self.objects[(Bucket, Key)] = Body

        def get_object(self, *, Bucket, Key):
            if (Bucket, Key) not in self.objects:
                raise type("NoSuchKey", (Exception,), {"response": {"Error": {"Code": "NoSuchKey"}}})()
            return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}

    s3 = FakeS3()
    store = ocr.S3OcrCache("bkt", client=s3)

    assert store.get("abc") is None
    store.put("abc", '{"file": "x"}')

    assert list(s3.objects) == [("bkt", "cache/ocr/abc.json")]
    assert store.get("abc") == '{"file": "x"}'


def test_empty_ocr_is_not_saved_so_next_upload_retries_textract():
    cache, calls = MemoryOcrCache(), []

    def empty(file, data, *, client=None, pages=None):
        calls.append(file)
        return OcrResult(file=file, lines=[])

    ocr.ocr_cached("uploads/a/scan.jpg", b"jpeg", cache=cache, run=empty)
    ocr.ocr_cached("uploads/a/scan.jpg", b"jpeg", cache=cache, run=empty)

    assert cache.items == {} and len(calls) == 2


def test_saved_empty_ocr_is_not_served():
    cache, calls = MemoryOcrCache(), []
    cache.items[ocr.ocr_cache_key(b"jpeg")] = OcrResult(file="x", lines=[]).model_dump_json()

    ocr.ocr_cached("uploads/a/scan.jpg", b"jpeg", cache=cache, run=counting_ocr(calls))

    assert calls == ["uploads/a/scan.jpg"]


@pytest.mark.parametrize("name, value", [("MAX_SIDE_PX", 2000), ("JPEG_QUALITY", 70), ("MAX_PAGES", 3), ("RENDER_DPI", 200)])
def test_cache_key_changes_with_page_image_settings(monkeypatch, name, value):
    before = ocr.ocr_cache_key(b"a")
    monkeypatch.setattr(ocr, name, value)

    assert ocr.ocr_cache_key(b"a") != before  # 쪽 그림이 달라지면 박스 위치도 달라진다 (리뷰 #3)


def test_s3_cache_shares_one_client_built_once_across_threads(monkeypatch):
    import sys
    import threading
    import time
    import types

    made = []

    def slow_client(service, **kwargs):
        time.sleep(0.02)  # 여러 스레드가 동시에 들어오게
        made.append(service)
        return object()

    monkeypatch.setitem(sys.modules, "boto3", types.SimpleNamespace(client=slow_client))
    ocr._s3_client.cache_clear()
    caches = [ocr.S3OcrCache("bkt") for _ in range(4)]
    got = []
    threads = [threading.Thread(target=lambda c=c: got.append(c._s3())) for c in caches]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    ocr._s3_client.cache_clear()

    assert made == ["s3"] and len({id(c) for c in got}) == 1  # 리뷰 #1: 스레드마다 기본 세션으로 클라이언트를 만들지 않는다


def test_s3_cache_treats_access_denied_on_missing_key_as_quiet_miss(capsys):
    """GetObject 권한만 있고 ListBucket 이 없으면 없는 키에 S3 가 403 을 준다. 처음 올린 파일마다 경고가 찍히지 않게 (리뷰 #2).
    진짜 권한 문제는 put 실패 경고로 드러난다."""

    class Denied:
        def get_object(self, **kwargs):
            raise type("ClientError", (Exception,), {"response": {"Error": {"Code": "AccessDenied"}}})()

    assert ocr.S3OcrCache("bkt", client=Denied()).get("abc") is None
    assert "[warn]" not in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Textract 글자로 서류 종류 고르기 (비용: 서류마다 Bedrock 분류 호출 하나를 줄인다)
# ---------------------------------------------------------------------------
def ocr_of(*lines):
    """(글자, top, height) 줄들로 OcrResult. left 는 0.3 고정."""
    return OcrResult(file="x", lines=[OcrLine(page=1, text=t, bbox=(0.3, top, 0.4, h)) for t, top, h in lines])


@pytest.mark.parametrize("title, expected", [
    ("COMMERCIAL INVOICE", "commercial_invoice"),
    ("Commercial Invoice", "commercial_invoice"),
    ("PACKING LIST", "packing_list"),
    ("BILL OF LADING", "bill_of_lading"),
    ("CERTIFICATE OF ORIGIN", "certificate_of_origin"),
    ("CERTIFICATE OF ORIGIN (Combined Declaration and Certificate)", "certificate_of_origin"),
])
def test_classify_from_ocr_uses_the_title_line(title, expected):
    got = ocr.classify_from_ocr(ocr_of((title, 0.1, 0.03), ("Invoice No. INV-1", 0.2, 0.012)))

    assert got is not None and got.doc_type == expected
    assert title in got.reason and "Textract" in got.reason


def test_classify_from_ocr_ignores_titles_inside_body_text():
    # B/L 약관 문장 속 'Bill of Lading', 상업송장 안의 'Packing List' 언급은 제목이 아니다
    got = ocr.classify_from_ocr(ocr_of(
        ("COMMERCIAL INVOICE", 0.15, 0.025),
        ("One original Bill of Lading must be surrendered duly endorsed", 0.4, 0.01),
        ("Packing List attached", 0.6, 0.01),
    ))

    assert got.doc_type == "commercial_invoice"


def test_classify_from_ocr_returns_none_when_no_title_so_model_decides():
    assert ocr.classify_from_ocr(ocr_of(("Shipper", 0.1, 0.012), ("QINGDAO SAMPLE TYRE CO., LTD.", 0.12, 0.012))) is None
    assert ocr.classify_from_ocr(None) is None


def test_classify_from_ocr_returns_none_when_two_titles_look_alike():
    got = ocr.classify_from_ocr(ocr_of(("COMMERCIAL INVOICE", 0.1, 0.025), ("PACKING LIST", 0.12, 0.025)))

    assert got is None  # 송장·포장명세서를 한 장에 합친 서류 등: 모델이 고른다


def test_classify_from_ocr_returns_none_when_title_is_low_on_the_page():
    assert ocr.classify_from_ocr(ocr_of(("Shipper", 0.1, 0.012), ("COMMERCIAL INVOICE", 0.7, 0.03))) is None


def test_textract_calls_are_paced_to_the_account_tps_limit(monkeypatch):
    """서울 리전 DetectDocumentText 한도가 초당 1건이다. 서류마다 스레드로 OCR 해도 호출 사이를 띄운다."""
    import threading
    import time

    monkeypatch.setattr(ocr, "TEXTRACT_MIN_INTERVAL", 0.05)
    monkeypatch.setattr(ocr, "_last_call", 0.0)
    stamps = []

    class Stamping(FakeTextract):
        def detect_document_text(self, **kwargs):
            stamps.append(time.monotonic())
            return {"Blocks": [line("X")]}

    threads = [threading.Thread(target=lambda: ocr.ocr_document("a.jpg", b"j", client=Stamping([]))) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    gaps = [b - a for a, b in zip(sorted(stamps), sorted(stamps)[1:])]
    assert len(stamps) == 4 and min(gaps) >= 0.045
