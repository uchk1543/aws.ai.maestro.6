"""api/worker.py 단위 테스트. DynamoDB는 가짜, run_job은 테스트마다 가짜로 바꾼다.

실제 run_job(가짜 모델)까지 이어 돌리는 흐름은 test_handler.py의 POST → process → GET 테스트가 본다.
"""

import json
from pathlib import Path

import pytest

import agent.document_agent as document_agent
import api.handler as handler
import api.worker as worker
import tools.hs as hs
import tools.report as report
import tools.wms as wms
from tests.unit.fakes import MemoryHSHistory, MemoryWms
from tests.unit.test_report_shipment import TODAY, MemoryWriter
from tools.models import Cell, ExtractedDocument, Job, JobResult, OcrLine, OcrResult, Shipment, Step
from tools.ocr import PageImage

JOB = "job-0000f003"
FILES = [{"key": "uploads/s1/invoice.pdf", "doc_type": "commercial_invoice"}]
OCR_TOTALS: dict[str, str] = {}

@pytest.fixture(autouse=True)
def ocr(monkeypatch):
    """Textract·PDF 그리기·S3 쓰기 대신 (F10 #188). PDF는 한 쪽 그림(가짜)을 만들고, OCR 은 서류마다 줄을 돌려준다.

    반환: 부른 기록 {"ocr": [키], "stored": {S3 키: 형식}}.
    """
    seen = {"ocr": [], "stored": {}}

    def fake_render(data, *, max_pages=None):
        return [PageImage(data=b"jpeg-page-1", width=1240, height=1754)]

    def fake_ocr(key, data, *, client=None, pages=None):
        seen["ocr"].append(key)
        name = key.rsplit("/", 1)[-1]
        lines = [
            OcrLine(page=1, text="COMMERCIAL INVOICE", bbox=(0.25, 0.05, 0.5, 0.04)),
            OcrLine(page=1, text="Invoice No. INV-2026-001", bbox=(0.1, 0.15, 0.5, 0.02)),
        ]
        if name in OCR_TOTALS:
            lines.append(OcrLine(page=1, text=OCR_TOTALS[name], bbox=(0.8, 0.34, 0.12, 0.02)))
        return OcrResult(file=key, lines=lines)

    monkeypatch.setattr(worker, "render_pages", fake_render)
    monkeypatch.setattr(worker, "ocr_document", fake_ocr)
    monkeypatch.setattr(handler, "store_object", lambda key, data, content_type: seen["stored"].__setitem__(key, content_type))
    return seen



@pytest.fixture(autouse=True)
def shipments(monkeypatch):
    """화물 기록(team06-shipments) 대신 메모리판 (E3). 오늘(처리한 날)은 고정."""
    store = MemoryWriter()
    monkeypatch.setattr(worker, "dynamo_shipments", lambda: store)
    monkeypatch.setattr(handler, "dynamo_shipments", lambda: store)
    monkeypatch.setattr(report, "_today", lambda: TODAY)
    return store


class RecordingTable:
    """team06-jobs 대신. 저장할 때마다 Job을 puts에 남겨 상태가 바뀐 순서를 본다."""

    def __init__(self):
        self.items = {}
        self.puts: list[Job] = []

    def put_item(self, Item):
        self.items[Item["job_id"]] = Item
        self.puts.append(Job.model_validate_json(Item["data"]))

    def get_item(self, Key):
        item = self.items.get(Key["job_id"])
        return {"Item": item} if item else {}


@pytest.fixture
def table(monkeypatch):
    t = RecordingTable()
    monkeypatch.setattr(handler, "_table", lambda: t)
    monkeypatch.setattr(handler, "fetch_object", lambda key: key.encode())
    return t


def put_job(table, status="queued", **extra):
    handler.save_job(Job(job_id=JOB, status=status, **extra))
    table.puts.clear()


def statuses(table) -> list[str]:
    return [j.status for j in table.puts]


def saved(table) -> Job:
    return Job.model_validate_json(table.items[JOB]["data"])


def test_queued_job_runs_and_saves_progress(table, monkeypatch):
    """queued → running(단계가 늘 때마다 저장) → 최종 상태. 진행 화면은 중간 저장에서 단계를 본다."""
    put_job(table)
    seen = {}

    def fake_run_job(job_id, files, fetch, *, on_step=None, **_):
        seen.update(job_id=job_id, files=files, data=fetch(files[0]["key"]))
        steps = [Step(tool="read_document", summary="invoice.pdf → 상업송장, 1행", ok=True)]
        on_step(Job(job_id=job_id, status="running", steps=steps))
        steps = [*steps, Step(tool="cross_check", summary="문제 없음", ok=True)]
        on_step(Job(job_id=job_id, status="running", steps=steps))
        return Job(job_id=job_id, status="done", steps=steps, result=JobResult())

    monkeypatch.setattr(document_agent, "run_job", fake_run_job)

    assert worker.lambda_handler({"job_id": JOB, "files": FILES}, None) == {"job_id": JOB, "status": "done"}

    assert seen == {"job_id": JOB, "files": FILES, "data": FILES[0]["key"].encode()}
    assert statuses(table) == ["running", "running", "running", "done"]
    assert [len(j.steps) for j in table.puts] == [0, 1, 2, 3]  # 마지막 저장에 OCR 단계 한 줄 (F10)
    assert saved(table).steps[-1].tool == "ocr_document" and saved(table).steps[-1].ok
    assert saved(table).result == JobResult()


def test_run_job_crash_is_failed_and_keeps_steps(table, monkeypatch):
    """예상 못 한 오류는 failed와 이유로 남기고, 그때까지의 단계 기록은 지우지 않는다. 예외를 밖으로 내지 않는다."""
    put_job(table)

    def crash(job_id, files, fetch, *, on_step=None, **_):
        on_step(Job(job_id=job_id, status="running", steps=[Step(tool="read_document", summary="읽음", ok=True)]))
        raise RuntimeError("터짐")

    monkeypatch.setattr(document_agent, "run_job", crash)

    assert worker.lambda_handler({"job_id": JOB, "files": FILES}, None) == {"job_id": JOB, "status": "failed"}
    job = saved(table)
    assert (job.status, job.error) == ("failed", "RuntimeError: 터짐")
    assert [s.tool for s in job.steps] == ["read_document", "ocr_document"]


@pytest.mark.parametrize("status", ["waiting_approval", "done", "failed"])
def test_finished_job_is_not_processed_again(table, monkeypatch, status):
    """같은 이벤트가 다시 와도(재시도·중복 전달) 끝난 작업은 그대로 둔다. 모델을 다시 부르지 않는다."""
    put_job(table, status=status)
    monkeypatch.setattr(document_agent, "run_job", lambda *a, **k: pytest.fail("run_job을 다시 부름"))

    assert worker.lambda_handler({"job_id": JOB, "files": FILES}, None) == {"job_id": JOB, "status": status}
    assert table.puts == []


def test_running_job_on_retry_is_failed_not_rerun(table, monkeypatch):
    """running인데 이벤트가 다시 왔다 = 앞선 실행이 시간 초과 등으로 멈췄다. 다시 돌리지 않고 failed로 끝낸다."""
    steps = [Step(tool="read_document", summary="읽음", ok=True)]
    put_job(table, status="running", steps=steps)
    monkeypatch.setattr(document_agent, "run_job", lambda *a, **k: pytest.fail("run_job을 다시 부름"))

    assert worker.lambda_handler({"job_id": JOB, "files": FILES}, None) == {"job_id": JOB, "status": "failed"}
    job = saved(table)
    assert (job.status, job.error, job.steps) == ("failed", worker.INTERRUPTED, steps)


@pytest.mark.parametrize(
    "event", [{}, None, "job-0000f003", {"job_id": "nope"}, {"job_id": 7}, {"job_id": "job-0000000x/../a"}]
)
def test_bad_event_does_nothing(table, event):
    assert worker.lambda_handler(event, None) == {"job_id": None, "status": None}
    assert table.puts == []


def test_unknown_job_does_nothing(table):
    assert worker.lambda_handler({"job_id": "job-00000000", "files": FILES}, None) == {"job_id": "job-00000000", "status": None}
    assert table.puts == []


@pytest.mark.parametrize(
    "files", [None, [], [{"key": "secret/x.pdf", "doc_type": "packing_list"}], [{"key": "uploads/x.pdf"}]]
)
def test_bad_files_fail_the_job(table, monkeypatch, files):
    """API가 검사한 값이지만, 틀린 이벤트로 queued인 채 남지 않게 failed로 끝낸다."""
    put_job(table)
    monkeypatch.setattr(document_agent, "run_job", lambda *a, **k: pytest.fail("run_job을 부름"))

    assert worker.lambda_handler({"job_id": JOB, "files": files}, None) == {"job_id": JOB, "status": "failed"}
    assert saved(table).error.startswith("요청한 서류 목록이 잘못됐습니다")


# ---------------------------------------------------------------------------
# #122 읽은 서류·수입자 저장과 HS 연결
# ---------------------------------------------------------------------------
EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "examples"
IMPORTER = "ACME KOREA CO., LTD."
BL = "BL-2026-0001"


class _Invoice(ExtractedDocument):
    """#110(B2 P1)이 약속 1에 consignee_name을 더하기 전까지 그 칸이 있는 상업송장을 흉내 낸다."""

    consignee_name: Cell | None = None


def example(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def read_docs(*, consignee: str | None = IMPORTER) -> list[ExtractedDocument]:
    pl = ExtractedDocument.model_validate(example("extract_packing_list.json"))
    ci = _Invoice.model_validate(
        {**pl.model_dump(), "doc_type": "commercial_invoice", "file": "uploads/s1/invoice.pdf",
         "consignee_name": {"raw": f"  {consignee} "} if consignee else None}
    )
    bl = ExtractedDocument(doc_type="bill_of_lading", file="uploads/s1/bl.pdf", doc_no=Cell(raw=BL, value=BL))
    return [pl, ci, bl]


def fake_run_job_with(docs: list[ExtractedDocument], seen: dict):
    """on_docs로 서류를 넘기고 승인 대기(문제는 '확인 필요'만) Job을 돌려주는 가짜 run_job."""

    def fake(job_id, files, fetch, *, on_step=None, on_docs=None, hs_recommender=None, **_):
        seen["hs_recommender"] = hs_recommender
        on_docs(docs)
        job = Job.model_validate({**example("job_waiting_approval.json"), "job_id": job_id})
        job.result.issues[0].grade = "확인 필요"
        return job

    return fake


@pytest.fixture
def api_fakes(table, monkeypatch):
    history, memory = MemoryHSHistory(), MemoryWms()
    monkeypatch.setattr(handler, "_hs_history", lambda: history)
    monkeypatch.setattr(wms, "dynamo_wms", lambda: memory)
    return table, history, memory


def call(method, path, body):
    res = handler.lambda_handler({"requestContext": {"http": {"method": method}}, "rawPath": path, "body": json.dumps(body)}, None)
    return res["statusCode"], json.loads(res["body"])


def test_docs_and_importer_are_saved_then_hs_and_approve_are_200(api_fakes, monkeypatch, shipments):
    """끝난 기준: 처리 Lambda가 저장한 docs·importer로 /hs·/approve가 409 대신 200을 낸다.
    화물 기록은 처리 끝에 '입항'으로 쓰고, 승인으로 WMS에 등록되면 '수입신고'로 고친다 (E3)."""
    table, history, memory = api_fakes
    put_job(table)
    seen = {}
    docs = read_docs()
    monkeypatch.setattr(document_agent, "run_job", fake_run_job_with(docs, seen))

    assert worker.lambda_handler({"job_id": JOB, "files": FILES}, None)["status"] == "waiting_approval"

    row = table.items[JOB]
    assert row["importer"] == IMPORTER  # 앞뒤 공백만 뗀 raw
    assert [d.file for d in handler._DOCS.validate_json(row["docs"])] == [d.file for d in docs]
    assert seen["hs_recommender"] is worker.recommend_line
    row = shipments.rows[BL]
    assert (row.customs_status, row.arrived_at, row.job_id, row.consignee) == ("입항", TODAY, JOB, IMPORTER)

    status, body = call("POST", f"/api/jobs/{JOB}/hs", {"choices": [{"line": 1, "hs": "8507600000"}]})
    assert status == 200 and "declaration_draft" in body
    assert [k[0] for k in history.rows] == [IMPORTER]

    status, body = call("POST", f"/api/jobs/{JOB}/approve", {"approver": "김담당"})
    assert (status, body) == (200, {"wms": {"status": "등록됨", "wms_id": "wms-0001"}})
    [(_, record)] = memory.records.values()
    assert (record.bl_no, record.consignee, record.by) == (BL, IMPORTER, "human")
    assert saved(table).status == "done"
    assert (shipments.rows[BL].customs_status, shipments.rows[BL].arrived_at) == ("수입신고", TODAY)
    assert [s.tool for s in saved(table).steps][-2:] == ["push_to_wms", "mark_registered"]


# ---------------------------------------------------------------------------
# E3 화물 기록 쓰기 (#31)
# ---------------------------------------------------------------------------
def run_with(table, monkeypatch, docs, status="waiting_approval"):
    """on_docs로 docs를 넘기고 status로 끝나는 가짜 run_job으로 처리한다."""
    put_job(table)

    def fake(job_id, files, fetch, *, on_docs=None, **_):
        on_docs(docs)
        steps = [Step(tool="cross_check", summary="문제 없음", ok=True)]
        return Job(job_id=job_id, status=status, steps=steps, result=JobResult())

    monkeypatch.setattr(document_agent, "run_job", fake)
    return worker.lambda_handler({"job_id": JOB, "files": FILES}, None)


@pytest.mark.parametrize("status", ["waiting_approval", "done"])
def test_finished_job_writes_shipment_row_as_last_step(table, monkeypatch, shipments, status):
    """입항일 = 처리한 날(한국 시간), 상태 '입항'. 단계 기록 끝에 record_shipment 한 줄이 마지막 저장에 들어간다."""
    assert run_with(table, monkeypatch, read_docs(), status)["status"] == status

    [row] = shipments.rows.values()
    assert (row.bl_no, row.customs_status, row.arrived_at, row.last_event_at, row.job_id) == (BL, "입항", TODAY, TODAY, JOB)
    job = saved(table)
    assert job.status == status
    assert job.steps[-1] == Step(tool="record_shipment", summary=f"화물 기록 B/L {BL}: 입항, 입항일 {TODAY.isoformat()}", ok=True)


def test_failed_job_writes_no_shipment(table, monkeypatch, shipments):
    """실패한 작업은 서류를 읽었어도 화물 기록을 쓰지 않는다."""
    assert run_with(table, monkeypatch, read_docs(), "failed")["status"] == "failed"
    assert shipments.rows == {}
    assert "record_shipment" not in [s.tool for s in saved(table).steps]


def test_no_bl_writes_no_shipment(table, monkeypatch, shipments):
    """B/L 번호가 없으면 쓰지 않는다. 이유는 단계 기록에 남고 작업은 그대로 끝난다."""
    assert run_with(table, monkeypatch, read_docs()[:2])["status"] == "waiting_approval"
    assert shipments.rows == {}
    last = saved(table).steps[-1]
    assert (last.tool, last.ok) == ("record_shipment", True) and "B/L 번호가 없어" in last.summary


def test_seed_shipment_is_not_overwritten(table, monkeypatch, shipments):
    """같은 B/L의 미리 넣은 가상 기록(job_id 없음)은 덮어쓰지 않는다."""
    seed = Shipment(bl_no=BL, consignee="샘플", item="운동화", arrived_at=TODAY.replace(day=1),
                    customs_status="반출", last_event_at=TODAY.replace(day=2))
    shipments.rows[BL] = seed

    assert run_with(table, monkeypatch, read_docs())["status"] == "waiting_approval"
    assert shipments.rows[BL] == seed and shipments.puts == 0
    assert "덮어쓰지 않음" in saved(table).steps[-1].summary


def test_shipments_store_failure_does_not_stop_the_job(table, monkeypatch):
    """화물 기록 저장소를 못 만들어도(SHIPMENTS_TABLE 없음 등) 작업은 끝난 상태로 저장된다. running으로 남지 않는다."""

    def broken():
        raise KeyError("SHIPMENTS_TABLE")

    monkeypatch.setattr(worker, "dynamo_shipments", broken)

    assert run_with(table, monkeypatch, read_docs())["status"] == "waiting_approval"
    job = saved(table)
    assert job.status == "waiting_approval" and table.items[JOB]["docs"]
    assert job.steps[-1] == Step(tool="record_shipment", summary="화물 기록을 쓰지 못함: KeyError", ok=False)


def test_without_consignee_docs_saved_but_no_importer(api_fakes, monkeypatch):
    """#110 전: docs만 저장하고 importer 칸은 쓰지 않는다. /hs는 '수입자' 409."""
    table, history, _ = api_fakes
    put_job(table)
    monkeypatch.setattr(document_agent, "run_job", fake_run_job_with(read_docs(consignee=None), {}))

    worker.lambda_handler({"job_id": JOB, "files": FILES}, None)

    assert table.items[JOB]["docs"] and "importer" not in table.items[JOB]
    status, body = call("POST", f"/api/jobs/{JOB}/hs", {"choices": [{"line": 1, "hs": "8507600000"}]})
    assert status == 409 and "수입자" in body["error"]
    assert history.rows == {}


def test_docs_are_saved_even_when_run_job_crashes(table, monkeypatch):
    """run_job은 실패해도 그때까지 읽은 서류를 on_docs로 넘긴다. failed 줄에도 남긴다."""
    put_job(table)
    docs = read_docs()

    def crash(job_id, files, fetch, *, on_docs=None, **_):
        on_docs(docs[:2])
        raise RuntimeError("터짐")

    monkeypatch.setattr(document_agent, "run_job", crash)
    assert worker.lambda_handler({"job_id": JOB, "files": FILES}, None)["status"] == "failed"
    assert len(handler._DOCS.validate_json(table.items[JOB]["docs"])) == 2
    assert table.items[JOB]["importer"] == IMPORTER


def test_no_docs_writes_no_columns(table, monkeypatch):
    put_job(table)
    monkeypatch.setattr(
        document_agent, "run_job", lambda job_id, files, fetch, **_: Job(job_id=job_id, status="done", result=JobResult())
    )
    worker.lambda_handler({"job_id": JOB, "files": FILES}, None)
    assert "docs" not in table.items[JOB] and "importer" not in table.items[JOB]


def test_recommend_line_uses_importer_history_or_empty_history(monkeypatch):
    """수입자를 알면 그 수입자 이력으로 자동 확정, 모르면 이력을 찾지 않는다 (빈 키·다른 수입자와 섞임 방지)."""
    history = MemoryHSHistory()
    monkeypatch.setattr(handler, "_hs_history", lambda: history)
    docs = read_docs()
    key = hs.item_key(docs[1], 1)
    history.put(IMPORTER, key, "8507602000", "job-old")  # HS부호 표에 있는 코드여야 이력을 믿는다
    history.put("", key, "9999999999", "job-x")

    got = worker.recommend_line(docs, 1)
    assert (got.status, got.by, got.hs_code) == ("자동 확정", "history", "8507602000")

    got = worker.recommend_line(read_docs(consignee=None), 1)
    assert got.by != "history" and got.hs_code != "9999999999"


def test_other_columns_of_the_row_are_kept(table, monkeypatch):
    """team06-jobs 한 줄의 다른 칸(예: C3가 읽는 docs·importer)은 처리 중 저장에서도 지우지 않는다."""
    put_job(table)
    table.items[JOB] |= {"docs": json.dumps([]), "importer": "ACME"}
    monkeypatch.setattr(
        document_agent, "run_job", lambda job_id, files, fetch, **_: Job(job_id=job_id, status="done", result=JobResult())
    )

    worker.lambda_handler({"job_id": JOB, "files": FILES}, None)

    assert (table.items[JOB]["docs"], table.items[JOB]["importer"]) == ("[]", "ACME")
    assert saved(table).status == "done"


# ---------------------------------------------------------------------------
# Textract OCR 매번 호출, PDF 쪽 그림 (F10 #188)
# ---------------------------------------------------------------------------
def done_run_job(job_id, files, fetch, **_):
    return Job(job_id=job_id, status="done", result=JobResult())


def test_every_file_is_ocred_and_pdf_pages_are_stored(table, monkeypatch, ocr):
    put_job(table)
    files = [*FILES, {"key": "uploads/s1/scan.jpg", "doc_type": None}]
    monkeypatch.setattr(document_agent, "run_job", done_run_job)

    worker.lambda_handler({"job_id": JOB, "files": files}, None)

    assert sorted(ocr["ocr"]) == sorted(f["key"] for f in files)
    item = table.items[JOB]
    saved_ocr = json.loads(item["ocr"])
    assert set(saved_ocr) == {f["key"] for f in files}
    assert OcrResult.model_validate(saved_ocr["uploads/s1/scan.jpg"]).lines[0].text == "COMMERCIAL INVOICE"
    # PDF만 쪽 그림을 그려 원본 옆에 둔다. 이미지는 원본을 그대로 쓴다
    assert ocr["stored"] == {"uploads/s1/invoice.pdf.p1.jpg": "image/jpeg"}
    assert json.loads(item["pages"]) == {"uploads/s1/invoice.pdf": [{"key": "uploads/s1/invoice.pdf.p1.jpg", "width": 1240, "height": 1754}]}


def test_ocr_failure_skips_only_that_file(table, monkeypatch):
    put_job(table)

    def flaky(key, data, *, client=None, pages=None):
        if key.endswith("scan.jpg"):
            raise TimeoutError("Textract 5초")
        return OcrResult(file=key, lines=[])

    monkeypatch.setattr(worker, "ocr_document", flaky)
    monkeypatch.setattr(document_agent, "run_job", done_run_job)

    files = [*FILES, {"key": "uploads/s1/scan.jpg", "doc_type": None}]
    assert worker.lambda_handler({"job_id": JOB, "files": files}, None)["status"] == "done"
    assert set(json.loads(table.items[JOB]["ocr"])) == {FILES[0]["key"]}
    step = saved(table).steps[-1]
    assert (step.tool, step.ok) == ("ocr_document", False) and "1/2장" in step.summary


def test_broken_pdf_render_skips_ocr_for_that_file(table, monkeypatch):
    put_job(table)

    def broken(data, *, max_pages=None):
        raise ValueError("깨진 PDF")

    monkeypatch.setattr(worker, "render_pages", broken)
    monkeypatch.setattr(document_agent, "run_job", done_run_job)

    assert worker.lambda_handler({"job_id": JOB, "files": FILES}, None)["status"] == "done"
    assert "ocr" not in table.items[JOB] and "pages" not in table.items[JOB]


def test_rereader_gets_that_files_ocr(table, monkeypatch):
    """다시 확인은 그 서류의 OCR 결과를 두 번째 근거로 받는다 (agent-design.md 4번)."""
    put_job(table)
    got = {}

    def fake_reread(doc, field, data, *, ocr=None, **_):
        got.update(file=doc.file, ocr=ocr)

    monkeypatch.setattr(worker, "reread_field", fake_reread)

    def fake_run_job(job_id, files, fetch, *, rereader=None, **_):
        rereader(ExtractedDocument(doc_type="commercial_invoice", file=files[0]["key"]), "total_gross_kg", b"pdf")
        return Job(job_id=job_id, status="done", result=JobResult())

    monkeypatch.setattr(document_agent, "run_job", fake_run_job)
    worker.lambda_handler({"job_id": JOB, "files": FILES}, None)

    assert got["file"] == FILES[0]["key"] and got["ocr"].lines[0].text == "COMMERCIAL INVOICE"
