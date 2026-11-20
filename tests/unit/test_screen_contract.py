"""화면 약속 시험 (FB14 #171). 담당: PM.
API → 처리 Lambda → 실제 run_job(가짜 모델)을 끝까지 돌려, 화면이 쓰는 칸이 채워지는지 본다.
test_examples.py는 예시 JSON이 모델 모양에 맞는지만 보고, 화면 시험은 그 예시로 돌아서 통과한다.
그래서 실제 출력에서 칸이 비어도(FB01 wms가 null, #154 신고서 초안이 null) 모든 시험이 통과했다.
AWS·Bedrock 호출 없음. 모델 응답과 HS 추천은 가짜다.
"""
import json
from pathlib import Path

import pytest

import api.handler as handler
import tests.unit.test_handler as test_handler
import tools.extract as extract
import tools.hs as hs
import tools.wms as wms
from tests.unit.fakes import MemoryWms
from tests.unit.test_handler import FakeLambda, FakeTable, call, lambda_client, ocr, process, shipments  # noqa: F401 (픽스처)
from tools.models import DeclarationDraft, HSCandidate, HSResult, Job, RawDocument, WmsState

EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "examples"
IMPORTER = "ACME KOREA CO., LTD."
ITEM = "LITHIUM-ION BATTERY PACK"
# 가짜 OCR(test_handler.TOTALS)이 아는 파일 이름. 다시 확인(B8)이 이 값으로 불일치를 확인한다
TOTALS = {"invoice.pdf": "6,250.00 KGS", "packing_list.pdf": "6,520.00 KGS", "pl_ok.pdf": "6,250 KG"}
MISMATCH, MATCH = "packing_list.pdf", "pl_ok.pdf"  # 포장명세서 파일: 총중량이 송장과 다르다 / 같다


def files_of(packing: str) -> list[dict]:
    return [
        {"key": "uploads/s1/invoice.pdf", "doc_type": "commercial_invoice"},
        {"key": f"uploads/s1/{packing}", "doc_type": "packing_list"},
        {"key": "uploads/s1/bl.pdf", "doc_type": "bill_of_lading"},
    ]


def raw(*, weight: str, bl: bool = False) -> dict:
    """서류 한 장. 송장 번호·총수량은 같게 두고 총중량만 정한다. 수하인·품명이 있어 수입자와 품목 행이 생긴다."""
    base = {
        "doc_no": {"raw": "BL-2026-0001" if bl else "INV-2026-001"},
        "consignee_name": {"raw": IMPORTER},
        "total_gross_kg": {"raw": weight},
    }
    if not bl:
        base |= {"total_qty": {"raw": "100 PCS"}, "items": [{"line": 1, "name": {"raw": ITEM}}]}
    return base


@pytest.fixture
def flow(monkeypatch, lambda_client, shipments, ocr):
    """API·처리 Lambda를 실제로 돌리는 환경. 반환: 총중량·HS 결과를 정해 올리고 처리하는 함수(job_id를 돌려줌)."""
    table, memory = FakeTable(), MemoryWms()
    monkeypatch.setattr(handler, "_table", lambda: table)
    monkeypatch.setattr(handler, "fetch_object", lambda key: key.encode())
    monkeypatch.setattr(wms, "dynamo_wms", lambda: memory)
    monkeypatch.setattr(handler, "_hs_history", lambda: None)
    monkeypatch.setitem(test_handler.OCR_TOTALS, "bl.pdf", TOTALS["invoice.pdf"])  # 선하증권도 Textract가 같은 값을 읽는다
    state = {"weights": {}, "hs_status": "자동 확정"}

    def fake_reader(blocks, prompt):
        name = blocks[0]["document"]["source"]["bytes"].decode().rsplit("/", 1)[-1]
        return RawDocument.model_validate(raw(weight=state["weights"][name], bl=name == "bl.pdf"))

    def fake_recommend(docs, line, importer, **_):
        if state["hs_status"] == "자동 확정":
            return HSResult(line=line, status="자동 확정", by="history", hs_code="8507600000", item_name=ITEM)
        return HSResult(
            line=line, status="사람 확인 필요", item_name=ITEM,
            candidates=[HSCandidate(hs="8507600000", name="(HS 표의 품목명)", reason="품명과 용도 칸 근거")],
        )

    monkeypatch.setattr(extract, "_strands_reader", fake_reader)
    monkeypatch.setattr(hs, "recommend_hs", fake_recommend)

    def run(*, packing: str, hs_status: str) -> dict:
        state["weights"] = {"invoice.pdf": TOTALS["invoice.pdf"], packing: TOTALS[packing], "bl.pdf": TOTALS["invoice.pdf"]}
        state["hs_status"] = hs_status
        status, body = call("POST", "/api/jobs", {"files": files_of(packing)})
        assert status == 200
        process(lambda_client)
        status, job = call("GET", f"/api/jobs/{body['job_id']}")
        assert status == 200
        Job.model_validate(job)  # 약속 2 형식
        return job

    return run


def non_null(d: dict) -> set[str]:
    return {k for k, v in d.items() if v is not None}


def test_waiting_approval_job_has_what_the_screen_draws(flow):
    """승인 대기: 화면이 승인 입력(WmsPanel)과 신고서 초안(DeclarationPanel)을 그릴 칸이 실제로 채워진다. FB01·#154가 여기서 걸렸다."""
    job = flow(packing=MISMATCH, hs_status="사람 확인 필요")
    assert job["status"] == "waiting_approval"
    result = job["result"]
    assert [i["grade"] for i in result["issues"]] == ["불일치"], result["issues"]
    assert result["wms"] == {"status": "승인 대기", "by": None, "wms_id": None, "approver": None, "approved_at": None, "override_reason": None}  # null이면 화면이 승인 버튼을 못 그린다 (FB01)
    draft = DeclarationDraft.model_validate(result["declaration_draft"])  # null이면 초안 칸이 비어 보인다 (#154)
    assert draft.fields and "total_gross_kg" in draft.blank_fields
    assert [h["status"] for h in result["hs"]] == ["사람 확인 필요"]
    assert result["hs"][0]["item_name"] == ITEM and result["hs"][0]["candidates"]


def test_done_job_is_registered_for_the_screen(flow):
    """정상 세트: 문제 없고 HS가 자동 확정이면 처리 직후 등록되어 done이다. 화면은 '등록됨'과 WMS 번호를 보인다."""
    job = flow(packing=MATCH, hs_status="자동 확정")
    assert job["status"] == "done", job["result"]["issues"]
    result = job["result"]
    assert result["issues"] == []
    wms_state = WmsState.model_validate(result["wms"])
    assert (wms_state.status, wms_state.by) == ("등록됨", "auto") and wms_state.wms_id
    assert result["declaration_draft"]["fields"]
    assert [h["status"] for h in result["hs"]] == ["자동 확정"]


def test_example_job_has_the_same_filled_fields_as_real_output(flow):
    """docs/examples/job_waiting_approval.json 에서 값이 있는 칸은 실제 승인 대기 출력에도 값이 있어야 한다.
    예시에만 있는 칸을 화면이 믿고 만들면 실제 응답에서 막힌다 (FB14)."""
    example = json.loads((EXAMPLES / "job_waiting_approval.json").read_text(encoding="utf-8"))
    job = flow(packing=MISMATCH, hs_status="사람 확인 필요")
    assert non_null(example["result"]) <= non_null(job["result"])
    for part in ("wms", "declaration_draft"):
        assert non_null(example["result"][part]) <= non_null(job["result"][part]), part
    assert set(example["result"]["hs"][0]) <= set(job["result"]["hs"][0])
    assert set(example["result"]["issues"][0]) <= set(job["result"]["issues"][0])
    assert set(example["steps"][0]) == set(job["steps"][0])
