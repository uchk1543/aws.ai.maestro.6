"""samples/measure_e2e.py(끝까지 측정, FB15 #172) 단위 테스트. 모델·AWS 호출 없음."""

import asyncio
from collections import Counter

from samples.measure_e2e import (
    LocalReadCache, cost_usd, count_model_usage, dev_sets, files_of, pick_sets, set_kind, summarize,
)


def test_pick_sets_is_ten_per_invoice_format_and_mixed():
    picked = pick_sets()
    sets, kinds = dev_sets(), set_kind()
    assert len(picked) == len(set(picked)) == 30 and picked == pick_sets()  # 늘 같은 30세트
    assert Counter(sets[s]["commercial_invoice"] for s in picked) == {"pdf": 10, "png": 10, "scan": 10}
    for fmt in ("pdf", "png", "scan"):  # 형식마다 심은 P0 오류·정상·헷갈리는 정상이 모두 들어 있다
        got = Counter(kinds[s] for s in picked if sets[s]["commercial_invoice"] == fmt)
        assert got["P0"] >= 4 and got["정상"] == 2 and got["변형"] == 2
    assert all(s.startswith("D") for s in picked)  # 개발용만 (발표용은 열지 않는다)


def test_files_of_lists_every_document_of_the_set():
    files = files_of("D003")
    assert [t for _, t in files] == ["commercial_invoice", "packing_list", "certificate_of_origin", "bill_of_lading"]
    assert files[0][0] == "samples/dev/D003/doc_a.pdf" and files[3][0].endswith("doc_d.pdf")


def test_local_read_cache_round_trip(tmp_path):
    cache = LocalReadCache(tmp_path / "read")
    assert cache.get("k1") is None
    cache.put("k1", '{"model": "RawDocument", "raw": {}}')
    assert cache.get("k1") == '{"model": "RawDocument", "raw": {}}'


def test_summarize_counts_by_format_without_model():
    """측정 줄 → 표. 탐지·읽기는 eval/score.py 함수로 센다 (D003 상업송장 총중량에 심은 오류를 짚은 줄 하나)."""
    row = {
        "set_id": "D003", "formats": dev_sets()["D003"], "status": "waiting_approval", "error": None,
        "seconds": 11.4, "model_calls": 10,
        "classified": [["doc_a.pdf", "commercial_invoice", True], ["doc_d.pdf", "bill_of_lading", False]],
        "docs": [{"doc_type": "commercial_invoice", "file": "samples/dev/D003/doc_a.pdf",
                  "total_gross_kg": {"raw": "21,683.10 KGS", "value": 21683.1, "unit": "KG"}}],
        "issues": [{"rule_id": "X-WT-01", "grade": "불일치", "evidence": "총중량이 다릅니다",
                    "cells": [{"doc": "commercial_invoice", "field": "total_gross_kg", "raw": "21,683.10 KGS"},
                              {"doc": "packing_list", "field": "total_gross_kg", "raw": "12,683.10 KGS"}]}],
        "hs": [{"line": 1, "status": "사람 확인 필요"}], "steps": [],
    }
    s = summarize([row, {**row, "set_id": "D005", "formats": dev_sets()["D005"], "issues": [], "docs": [],
                         "tokens_in": 30_000, "tokens_out": 4_000}])  # 토큰 칸이 있는 줄과 없는 예전 줄
    assert s["tokens"]["tokens_in"] == 30_000 and s["tokens"]["per_set_in"] == 15_000
    assert s["cost_usd"]["total"] == cost_usd(30_000, 4_000) == 0.1 and s["cost_usd"]["per_set"] == 0.05
    s = summarize([row])
    assert s["sets"] == 1 and s["model_calls"] == 10 and s["hs"] == {"사람 확인 필요": 1}
    assert s["classify_by_format"] == {"pdf": {"분류": 1, "분류 맞음": 1}, "scan": {"분류": 1, "분류 맞음": 0}}
    assert (s["detection"]["planted"], s["detection"]["detected"]) == (1, 1)
    assert s["seconds"] == {"mean": 11.4, "max": 11.4}


def test_score_hs_rows_against_sets_answer():
    """D003 1행 정답 9401699000, 2행 9403609090 (eval/sets.csv). 사람 확인 후보 3개 안·틀린 자동 확정을 센다."""
    from samples.measure_e2e import score_hs_rows, warnings_of

    row = {"set_id": "D003", "hs": [
        {"line": 1, "status": "사람 확인 필요", "candidates": [{"hs": "9401800000"}, {"hs": "9401699000"}]},
        {"line": 2, "status": "자동 확정", "hs_code": "9403200000", "candidates": []},
    ]}
    s = score_hs_rows([row])
    assert (s["rows"], s["human"], s["human_in_top3"], s["auto"], s["wrong_auto"]) == (2, 1, 1, 1, 1)
    assert s["wrong_auto_rows"] == ["D003 2행 9403200000 (정답 9403609090)"]
    assert warnings_of("[tool] a\n[warn] ocr key=k Throttling\n[error] x\n") == ["[warn] ocr key=k Throttling", "[error] x"]


def test_count_model_usage_reads_bedrock_usage_metadata(monkeypatch):
    """BedrockModel.stream 응답 끝의 metadata.usage에서 토큰을 모은다 (실제 Bedrock 호출 없음)."""
    from strands.models import bedrock

    async def fake_stream(self, *args, **kwargs):
        yield {"messageStart": {"role": "assistant"}}
        yield {"metadata": {"usage": {"inputTokens": 3500, "outputTokens": 130, "totalTokens": 3630}}}

    monkeypatch.setattr(bedrock.BedrockModel, "stream", fake_stream)  # 끝나면 진짜 stream으로 되돌린다
    usage = count_model_usage()

    async def call_twice():
        for _ in range(2):
            async for _event in bedrock.BedrockModel.stream(None):
                pass

    asyncio.run(call_twice())
    assert usage == {"model": 2, "tokens_in": 7000, "tokens_out": 260, "cache_read": 0, "cache_write": 0}
    assert cost_usd(7000, 260) == round((7000 * 2 + 260 * 10) / 1_000_000, 4)


# ---------------------------------------------------------------------------
# 처리 Lambda와 같은 조건 (like_worker): OCR·HS 모델. 배포본 저장소는 건드리지 않는다
# ---------------------------------------------------------------------------
import pytest  # noqa: E402

from samples.measure_e2e import ROOT, like_worker, run_set  # noqa: E402
from tools.models import (  # noqa: E402
    Classification, HSPick, HSSearchTerms, OcrLine, OcrResult, RawDocument,
)


@pytest.fixture
def no_aws(monkeypatch, tmp_path):
    """S3·DynamoDB·Textract·Bedrock을 부르면 실패하게 막고(끝나면 되돌림), like_worker를 건다."""
    from api import handler, worker

    monkeypatch.setattr(handler, "fetch_object", lambda key: pytest.fail("S3에서 읽으면 안 된다"))
    monkeypatch.setattr(handler, "store_object", lambda *a, **k: pytest.fail("S3에 쓰면 안 된다"))
    monkeypatch.setattr(handler, "_hs_history", lambda: pytest.fail("DynamoDB를 읽으면 안 된다"))
    monkeypatch.setattr(worker, "ocr_cache", lambda: None)
    texts = {"doc_a": "TOTAL G.W. 120 KGS", "doc_b": "TOTAL G.W. 100 KGS", "doc_c": "GROSS WEIGHT 100 KGS"}

    def fake_ocr(file, data, *, client=None, pages=None):
        slot = file.rsplit("/", 1)[-1].split(".")[0]
        return OcrResult(file=file, lines=[OcrLine(page=1, text=texts.get(slot, ""), bbox=(0.1, 0.1, 0.5, 0.05))])

    monkeypatch.setattr(worker, "ocr_document", fake_ocr)
    usage = {"model": 0, "tokens_in": 0, "tokens_out": 0, "cache_read": 0, "cache_write": 0}
    like_worker(usage, tmp_path / "ocr")
    return usage


def test_like_worker_reads_local_files_and_writes_nothing(no_aws):
    from api import handler, worker

    assert handler.fetch_object("samples/dev/D003/doc_a.pdf")[:4] == b"%PDF"  # 로컬 파일
    assert handler.store_object("uploads/x.p1.jpg", b"", "image/jpeg") is None  # S3에 쓰지 않는다
    assert handler._hs_history().get("수입자", "품목") is None  # 빈 확정 이력
    worker.ocr_document("k.pdf", b"x", pages=[b"1", b"2"])
    worker.ocr_document("k.png", b"x")
    assert no_aws["textract_pages"] == 3  # PDF는 쪽마다, 이미지는 1
    assert worker.ocr_cache() is not None  # 로컬 OCR 캐시


def test_run_set_like_worker_uses_ocr_for_reread_and_hs_model(no_aws, monkeypatch):
    """실제 개발용 PDF(D005, 3장)로 처리 Lambda와 같은 부품을 돈다. 모델·Textract는 가짜."""
    from tools import extract, hs

    files = {(ROOT / key).read_bytes(): doc_type for key, doc_type in files_of("D005")}
    asked: list[str] = []

    def classifier(blocks, prompt):
        return Classification(doc_type=files[blocks[0]["document"]["source"]["bytes"]], reason="제목 (가짜)")

    def reader(blocks, prompt):  # 포장명세서만 총중량 120 → 송장·B/L 100과 불일치
        doc_type = files[blocks[0]["document"]["source"]["bytes"]]
        weight = "120 KGS" if doc_type == "packing_list" else "100 KGS"
        return RawDocument.model_validate({"doc_no": {"raw": "INV-9"}, "total_gross_kg": {"raw": weight},
                                           "items": [{"line": 1, "name": {"raw": "WOODEN CHAIR"}}]})

    monkeypatch.setattr(extract, "_strands_classifier", classifier)
    monkeypatch.setattr(extract, "_strands_reader", reader)
    monkeypatch.setattr(hs, "bedrock_terms_reader", lambda name: asked.append("terms") or HSSearchTerms(terms=["chair"]))
    monkeypatch.setattr(hs, "bedrock_picker", lambda name, cands: asked.append("pick") or HSPick(picks=[]))

    row = run_set("D005", no_aws)
    tools_used = [s["tool"] for s in row["steps"]]
    assert row["status"] == "waiting_approval" and row["error"] is None
    assert [ok for _, _, ok in row["classified"]] == [True, True, True]
    assert row["textract_pages"] >= 3  # 서류마다 OCR (PDF는 쪽마다)
    assert "ocr_document" in tools_used and "hs_model" in tools_used  # 처리 Lambda가 run_job 뒤에 남기는 단계
    [weight] = [i for i in row["issues"] if i["rule_id"] == "X-WT-01"]
    assert weight["checked_by"] == "textract"  # 다시 확인의 두 번째 근거가 OCR이다 (OCR 없으면 model_reread)
    assert "terms" in asked  # HS 모델 검색어 뽑기를 불렀다
