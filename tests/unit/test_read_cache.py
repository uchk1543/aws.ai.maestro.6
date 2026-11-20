"""판독 캐시(B3) 단위 테스트. 모델은 가짜, 저장소는 dict와 가짜 S3 클라이언트 (AWS·Bedrock 호출 없음)."""

import io

import pytest

from tools import extract
from tools.extract import S3ReadCache, cache_key, read_document
from tools.models import RawDocument

RAW = {"doc_no": {"raw": "INV-1"}, "items": [{"line": 1, "gross_kg": {"raw": "6,520.00 KGS"}}],
       "total_gross_kg": {"raw": "6,520.00 KGS"}}
PDF = b"%PDF-1.7 same file"


class DictCache:
    def __init__(self):
        self.data: dict[str, str] = {}

    def get(self, key):
        return self.data.get(key)

    def put(self, key, value):
        self.data[key] = value


def counting_reader(raw=RAW):
    def reader(blocks, prompt):
        reader.calls += 1
        return RawDocument.model_validate(raw)

    reader.calls = 0
    return reader


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for name in ("READ_CACHE_BUCKET", "NO_CACHE", "READ_MODE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MODEL_ID", "model-a")


def test_same_key_does_not_call_model_and_keeps_new_file_name():
    cache, reader = DictCache(), counting_reader()
    first = read_document("uploads/a/1-inv.pdf", PDF, "commercial_invoice", reader=reader, cache=cache)
    again = read_document("uploads/b/1-inv.pdf", PDF, "commercial_invoice", reader=reader, cache=cache)
    assert reader.calls == 1 and len(cache.data) == 1
    assert again.file == "uploads/b/1-inv.pdf"  # file은 캐시에 없고 이번 키로 붙는다
    assert again.model_dump(exclude={"file"}) == first.model_dump(exclude={"file"})
    assert again.total_gross_kg.value == 6520.0  # value는 코드가 다시 채운다


def test_key_changes_with_file_model_prompt_version_and_doc_type(monkeypatch):
    base = cache_key(PDF, "commercial_invoice")
    assert cache_key(PDF + b"x", "commercial_invoice") != base
    assert cache_key(PDF, "packing_list") != base
    assert cache_key(PDF, "commercial_invoice", model_id="model-b") != base
    monkeypatch.setattr(extract, "PROMPT_VERSION", "read-v99")
    assert cache_key(PDF, "commercial_invoice") != base
    monkeypatch.undo()
    monkeypatch.setenv("MODEL_ID", "model-a")
    monkeypatch.setenv("READ_MODE", "json")
    assert cache_key(PDF, "commercial_invoice") != base


def test_no_cache_always_calls_model_and_writes_nothing(monkeypatch):
    cache, reader = DictCache(), counting_reader()
    for _ in range(2):
        read_document("uploads/a/1-inv.pdf", PDF, "commercial_invoice", reader=reader, cache=cache, no_cache=True)
    assert reader.calls == 2 and cache.data == {}

    monkeypatch.setenv("READ_CACHE_BUCKET", "team06-docs-test")
    monkeypatch.setenv("NO_CACHE", "1")
    assert extract._default_cache() is None


def test_without_bucket_env_there_is_no_cache():
    assert extract._default_cache() is None


def test_broken_cache_value_is_read_again():
    cache, reader = DictCache(), counting_reader()
    cache.data[cache_key(PDF, "commercial_invoice")] = '{"items": "깨진 값"}'
    doc = read_document("uploads/a/1-inv.pdf", PDF, "commercial_invoice", reader=reader, cache=cache)
    assert reader.calls == 1 and doc.doc_no.raw == "INV-1"


def test_cache_errors_do_not_stop_reading():
    class Broken:
        def get(self, key):
            return None

        def put(self, key, value):
            raise RuntimeError("AccessDenied")

    reader = counting_reader()
    doc = read_document("uploads/a/1-inv.pdf", PDF, "commercial_invoice", reader=reader, cache=Broken())
    assert reader.calls == 1 and doc.doc_no.raw == "INV-1"


def test_read_failure_is_not_cached():
    cache = DictCache()

    def failing(blocks, prompt):
        raise RuntimeError("Bedrock 오류")

    with pytest.raises(extract.ReadError):
        read_document("uploads/a/1-inv.pdf", PDF, "commercial_invoice", reader=failing, cache=cache)
    assert cache.data == {}


class FakeS3:
    class NoSuchKey(Exception):
        response = {"Error": {"Code": "NoSuchKey"}}

    def __init__(self):
        self.objects: dict[tuple[str, str], bytes] = {}

    def get_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise self.NoSuchKey()
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}

    def put_object(self, Bucket, Key, Body, ContentType):
        self.objects[(Bucket, Key)] = Body


def test_s3_cache_uses_cache_prefix_in_bucket():
    s3 = FakeS3()
    store, reader = S3ReadCache("team06-docs-test", client=s3), counting_reader()
    for _ in range(2):
        read_document("uploads/a/1-inv.pdf", PDF, "commercial_invoice", reader=reader, cache=store)
    assert reader.calls == 1
    [(bucket, key)] = s3.objects
    assert bucket == "team06-docs-test" and key == f"cache/read/{cache_key(PDF, 'commercial_invoice')}.json"
