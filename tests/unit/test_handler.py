"""api/handler.py 단위 테스트. DynamoDB·S3·Bedrock은 가짜로 바꾼다."""

import json
from pathlib import Path

import pytest

import api.handler as handler
import tools.declaration as declaration
import tools.extract as extract
import tools.hs as hs
from tests.unit.fakes import MemoryHSHistory
from tools.models import DeclarationDraft, DeclarationField, ExtractedDocument, Job, RawDocument

EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "examples"

TOTALS = {"invoice.pdf": "6,250.00 KGS", "packing_list.pdf": "6,520.00 KGS", "pl_ok.pdf": "6,250 KG"}


class FakeTable:
    def __init__(self):
        self.items = {}

    def put_item(self, Item):
        self.items[Item["job_id"]] = Item

    def get_item(self, Key):
        item = self.items.get(Key["job_id"])
        return {"Item": item} if item else {}


@pytest.fixture
def fakes(monkeypatch):
    table = FakeTable()
    monkeypatch.setattr(handler, "_table", lambda: table)
    # S3 대신 키 이름을 바이트로 돌려준다
    monkeypatch.setattr(handler, "fetch_object", lambda key: key.encode())

    def fake_reader(blocks, prompt):
        key = blocks[0]["document"]["source"]["bytes"].decode()
        name = key.rsplit("/", 1)[-1]
        if name == "broken.pdf":
            raise RuntimeError("모델 오류")
        # 총중량만 서류마다 다르고, 송장 번호와 총수량은 같게 둔다 (빈 칸은 '확인 필요'가 되므로 채워야 한다)
        return RawDocument.model_validate(
            {
                "doc_no": {"raw": "INV-2026-001"},
                "total_qty": {"raw": "100 PCS"},
                "total_gross_kg": {"raw": TOTALS[name]},
            }
        )

    monkeypatch.setattr(extract, "_strands_reader", fake_reader)
    return table


def call(method, path, body=None):
    event = {"requestContext": {"http": {"method": method}}, "rawPath": path}
    if body is not None:
        event["body"] = json.dumps(body)
    res = handler.lambda_handler(event, None)
    return res["statusCode"], json.loads(res["body"])


def files(*names):
    types = {"invoice.pdf": "commercial_invoice"}
    return {"files": [{"key": f"uploads/s1/{n}", "doc_type": types.get(n, "packing_list")} for n in names]}


def test_health():
    assert call("GET", "/") == (200, {"ok": True})


def test_post_then_get_shows_mismatch(fakes):
    status, body = call("POST", "/jobs", files("invoice.pdf", "packing_list.pdf"))
    assert status == 200
    status, job = call("GET", f"/jobs/{body['job_id']}")
    assert status == 200
    Job.model_validate(job)  # 약속 2 형식
    assert job["status"] == "waiting_approval"
    assert [s["tool"] for s in job["steps"]] == ["read_document", "read_document", "cross_check"]
    [issue] = job["result"]["issues"]
    assert issue["grade"] == "불일치" and issue["rule_id"] == "X-WT-01"


def test_matching_docs_are_done(fakes):
    _, body = call("POST", "/jobs", files("invoice.pdf", "pl_ok.pdf"))
    _, job = call("GET", f"/jobs/{body['job_id']}")
    assert job["status"] == "done" and job["result"]["issues"] == []


def test_read_failure_is_check_needed(fakes):
    _, body = call("POST", "/jobs", files("invoice.pdf", "broken.pdf"))
    _, job = call("GET", f"/jobs/{body['job_id']}")
    assert job["status"] == "waiting_approval"
    assert job["result"]["issues"][0]["rule_id"] == "READ-FAIL"
    assert job["steps"][1]["ok"] is False


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"files": []},
        {"files": [{"key": "secret/x.pdf", "doc_type": "packing_list"}]},
        {"files": [{"key": "uploads/../x.pdf", "doc_type": "packing_list"}]},
        {"files": [{"key": "uploads/x.pdf", "doc_type": None}]},
        {"files": [{"key": "uploads/x.pdf", "doc_type": "bill_of_lading"}]},
    ],
)
def test_bad_requests_are_400(fakes, body):
    assert call("POST", "/jobs", body)[0] == 400


def test_unknown_job_and_path_are_404(fakes):
    assert call("GET", "/jobs/job-00000000")[0] == 404
    assert call("GET", "/jobs/../../etc")[0] == 404
    assert call("GET", "/nothing")[0] == 404


@pytest.mark.parametrize("path", ["/uploads", "/jobs/job-00000000/approve", "/chat"])
def test_planned_routes_are_501(fakes, path):
    """약속 2의 경로가 모두 자리를 갖고 있다. 만들면 이 목록에서 뺀다."""
    assert call("POST", path, {})[0] == 501


# ---------------------------------------------------------------------------
# POST /jobs/{id}/hs (C3). 2번의 item_key·confirm_by_human·draft_declaration은 가짜로 바꾼다.
# ---------------------------------------------------------------------------
HS_JOB = "job-00000c03"
IMPORTER = "ACME KOREA CO., LTD."


def example(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def example_docs() -> list[ExtractedDocument]:
    """예시 포장명세서와, 같은 품목을 다른 품목 코드로 적은 상업송장 (키가 어느 서류에서 왔는지 보려고)."""
    pl = ExtractedDocument.model_validate(example("extract_packing_list.json"))
    ci = pl.model_copy(deep=True, update={"doc_type": "commercial_invoice", "file": "uploads/sample-001/invoice.pdf"})
    ci.items[0].item_code.value = "CI-BP-200"
    return [pl, ci]


def put_hs_job(table, *, status="waiting_approval", with_docs=True):
    job = Job.model_validate({**example("job_waiting_approval.json"), "job_id": HS_JOB, "status": status})
    if status == "running":
        job.result = None
    item = {"job_id": HS_JOB, "data": job.model_dump_json(by_alias=True), "updated_at": 0}
    if with_docs:
        docs = [d.model_dump(mode="json") for d in example_docs()]
        item |= {"docs": json.dumps(docs, ensure_ascii=False), "importer": IMPORTER}
    table.put_item(Item=item)


@pytest.fixture
def hs_fakes(fakes, monkeypatch):
    """C2·C5가 아직 없어서 같은 모양의 가짜를 끼운다. 부른 인자를 calls에 남긴다."""
    history = MemoryHSHistory()
    calls = {"item_key": [], "confirm": [], "draft": []}

    def fake_item_key(doc, line):
        calls["item_key"].append((doc.doc_type, line))
        return next(i for i in doc.items if i.line == line).item_code.value

    def fake_confirm(result, code, importer, key, job_id, *, history):
        calls["confirm"].append((result.line, code, importer, key, job_id))
        history.put(importer, key, code, job_id)
        return result.model_copy(update={"status": "사람 확정", "by": "human", "hs_code": code})

    def fake_draft(docs, issues, hs_results):
        calls["draft"].append(([d.doc_type for d in docs], len(issues), [r.hs_code for r in hs_results]))
        fields = [DeclarationField(name="세번부호", value=r.hs_code, source="hs") for r in hs_results if r.hs_code]
        return DeclarationDraft(fields=fields, blank_fields=["items[0].gross_kg"])

    monkeypatch.setattr(handler, "_hs_history", lambda: history)
    monkeypatch.setattr(hs, "item_key", fake_item_key)
    monkeypatch.setattr(hs, "confirm_by_human", fake_confirm)
    monkeypatch.setattr(declaration, "draft_declaration", fake_draft)
    return fakes, history, calls


def test_hs_choice_fills_draft_and_saves_history(hs_fakes):
    table, history, calls = hs_fakes
    put_hs_job(table)

    status, body = call("POST", f"/jobs/{HS_JOB}/hs", {"choices": [{"line": 1, "hs": "8507600000"}]})

    assert status == 200
    draft = DeclarationDraft.model_validate(body["declaration_draft"])
    assert [(f.name, f.value) for f in draft.fields] == [("세번부호", "8507600000")]
    # 이력 키는 상업송장의 품목 코드, 수입자는 저장해 둔 값
    assert calls["item_key"] == [("commercial_invoice", 1)]
    assert calls["confirm"] == [(1, "8507600000", IMPORTER, "CI-BP-200", HS_JOB)]
    assert history.rows == {(IMPORTER, "CI-BP-200"): ("8507600000", HS_JOB)}
    # 초안은 확정한 HS와 남은 문제로 다시 채운다
    assert calls["draft"] == [(["packing_list", "commercial_invoice"], 1, ["8507600000"])]

    _, job = call("GET", f"/jobs/{HS_JOB}")
    [line1] = job["result"]["hs"]
    assert (line1["status"], line1["by"], line1["hs_code"]) == ("사람 확정", "human", "8507600000")
    assert job["result"]["declaration_draft"] == body["declaration_draft"]
    assert [s["tool"] for s in job["steps"][-2:]] == ["confirm_by_human", "draft_declaration"]
    # 다음 요청을 위해 서류 기록은 그대로 남는다
    assert table.items[HS_JOB]["importer"] == IMPORTER and table.items[HS_JOB]["docs"]


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"choices": []},
        {"choices": [{"line": 2, "hs": "8507600000"}]},  # 이 작업에 없는 행
        {"choices": [{"line": "1", "hs": "8507600000"}]},
        {"choices": [{"line": True, "hs": "8507600000"}]},
        {"choices": [{"line": 1, "hs": "8507.60"}]},
        {"choices": [{"line": 1, "hs": "850760"}]},  # 6자리
        {"choices": [{"line": 1, "hs": 8507600000}]},
        {"choices": [{"line": 1, "hs": "8507600000"}, {"line": 1, "hs": "8507600000"}]},
    ],
)
def test_hs_bad_choices_are_400_and_write_nothing(hs_fakes, body):
    table, history, calls = hs_fakes
    put_hs_job(table)
    assert call("POST", f"/jobs/{HS_JOB}/hs", body)[0] == 400
    assert history.rows == {} and calls["confirm"] == [] and calls["draft"] == []


def test_hs_unknown_job_is_404(hs_fakes):
    assert call("POST", "/jobs/job-00000000/hs", {"choices": [{"line": 1, "hs": "8507600000"}]})[0] == 404
    assert call("POST", "/jobs/nope/hs", {"choices": [{"line": 1, "hs": "8507600000"}]})[0] == 404


@pytest.mark.parametrize("kwargs", [{"status": "running"}, {"with_docs": False}])
def test_hs_job_not_ready_is_409(hs_fakes, kwargs):
    """처리 중인 작업, 서류 기록이 없는 작업은 고를 수 없다. 이력도 쓰지 않는다."""
    table, history, calls = hs_fakes
    put_hs_job(table, **kwargs)
    assert call("POST", f"/jobs/{HS_JOB}/hs", {"choices": [{"line": 1, "hs": "8507600000"}]})[0] == 409
    assert history.rows == {} and calls["confirm"] == []


def test_dynamo_hs_history_round_trip():
    class FakeHistoryTable:
        def __init__(self):
            self.items = {}

        def put_item(self, Item):
            self.items[(Item["importer"], Item["item_key"])] = Item

        def get_item(self, Key):
            item = self.items.get((Key["importer"], Key["item_key"]))
            return {"Item": item} if item else {}

    store = handler.DynamoHSHistory(FakeHistoryTable())
    assert store.get(IMPORTER, "BP-200") is None
    store.put(IMPORTER, "BP-200", "8507600000", HS_JOB)
    assert store.get(IMPORTER, "BP-200") == "8507600000"
