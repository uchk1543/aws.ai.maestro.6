"""api/worker.py 단위 테스트. DynamoDB는 가짜, run_job은 테스트마다 가짜로 바꾼다.

실제 run_job(가짜 모델)까지 이어 돌리는 흐름은 test_handler.py의 POST → process → GET 테스트가 본다.
"""

import json

import pytest

import agent.document_agent as document_agent
import api.handler as handler
import api.worker as worker
from tools.models import Job, JobResult, Step

JOB = "job-0000f003"
FILES = [{"key": "uploads/s1/invoice.pdf", "doc_type": "commercial_invoice"}]


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
    assert [len(j.steps) for j in table.puts] == [0, 1, 2, 2]
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
    assert [s.tool for s in job.steps] == ["read_document"]


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
