"""tools/wms.py 자동 등록 조건(D2) 단위 테스트. 가상 WMS는 메모리판(MemoryWms)으로 바꾼다 (AWS 호출 없음)."""

import pytest

from tests.unit.fakes import MemoryWms
from tools import wms
from tools.models import Cell, ExtractedDocument, ExtractedItem, HSResult, Issue, IssueCell, JobResult, WmsRecord, WmsState

JOB = "job-0000d002"
BL = "BL-2026-0002"
IMPORTER = "샘플무역"
WAITING = WmsState(status="승인 대기")


def docs(*lines: int, bl: str | None = BL) -> list[ExtractedDocument]:
    """품목 lines가 있는 상업송장과 B/L No.가 bl인 선하증권. bl이 None이면 선하증권이 없다."""
    ci = ExtractedDocument(
        doc_type="commercial_invoice",
        file="uploads/s2/invoice.pdf",
        items=[ExtractedItem(line=n, name=Cell(raw=f"ITEM {n}", value=f"item {n}")) for n in lines],
    )
    if bl is None:
        return [ci]
    return [ci, ExtractedDocument(doc_type="bill_of_lading", file="uploads/s2/bl.pdf", doc_no=Cell(raw=bl, value=bl))]


def auto(line: int) -> HSResult:
    return HSResult(line=line, status="자동 확정", by="history", hs_code=f"85076000{line:02d}")


def human(line: int) -> HSResult:
    return HSResult(line=line, status="사람 확정", by="human", hs_code=f"85076000{line:02d}")


def pending(line: int) -> HSResult:
    return HSResult(line=line, status="사람 확인 필요")


def issue(grade: str) -> Issue:
    return Issue(
        rule_id="X-WT-01",
        grade=grade,
        cells=[IssueCell(doc="packing_list", field="total_gross_kg", raw="6,520.00 KGS")],
        evidence="상업송장 총중량 6,250kg과 포장명세서 6,520kg이 다릅니다.",
    )


class BrokenWms:
    """register를 부르면 저장소 오류를 낸다. 부른 횟수를 센다."""

    def __init__(self):
        self.calls = 0

    def register(self, record: WmsRecord) -> str:
        self.calls += 1
        raise RuntimeError("가짜 저장소 오류")


# ---------------------------------------------------------------------------
# can_auto_register
# ---------------------------------------------------------------------------
def test_no_problem_and_all_hs_confirmed_can_register():
    assert wms.can_auto_register(JobResult(hs=[auto(1), human(2)])) is True


def test_reference_issue_does_not_block():
    assert wms.can_auto_register(JobResult(issues=[issue("참고")], hs=[auto(1)])) is True


@pytest.mark.parametrize("grade", ["불일치", "확인 필요"])
def test_mismatch_or_check_needed_blocks(grade):
    assert wms.can_auto_register(JobResult(issues=[issue("참고"), issue(grade)], hs=[auto(1)])) is False


def test_hs_waiting_for_human_blocks():
    assert wms.can_auto_register(JobResult(hs=[auto(1), pending(2)])) is False


def test_no_hs_result_blocks():
    """HS를 아직 안 돌렸으면 확정됐다고 볼 수 없다."""
    assert wms.can_auto_register(JobResult()) is False


def test_confirmed_without_code_blocks():
    assert wms.can_auto_register(JobResult(hs=[HSResult(line=1, status="자동 확정", by="history")])) is False


# ---------------------------------------------------------------------------
# register_if_ready → (WMS 상태, 못 한 이유)
# ---------------------------------------------------------------------------
def test_ready_job_is_registered_by_auto():
    memory = MemoryWms()
    state, reason = wms.register_if_ready(JOB, docs(1, 2), JobResult(hs=[auto(1), human(2)]), IMPORTER, adapter=memory)
    assert (state, reason) == (WmsState(status="등록됨", by="auto", wms_id="wms-0001"), None)
    [(wms_id, record)] = memory.records.values()
    assert wms_id == state.wms_id
    assert (record.idempotency_key, record.by, record.consignee) == (f"{BL}#{JOB}", "auto", IMPORTER)
    assert [(row["line"], row["hs_code"]) for row in record.items] == [(1, "8507600001"), (2, "8507600002")]


@pytest.mark.parametrize(
    "result",
    [
        JobResult(issues=[issue("불일치")], hs=[auto(1)]),
        JobResult(issues=[issue("확인 필요")], hs=[auto(1)]),
        JobResult(hs=[pending(1)]),
        JobResult(),
    ],
    ids=["mismatch", "check-needed", "hs-pending", "no-hs"],
)
def test_not_ready_job_waits_without_reason(result):
    """조건 미달은 정상 흐름이라 이유를 붙이지 않는다 (단계 기록에 실패로 남기지 않는다)."""
    memory = MemoryWms()
    assert wms.register_if_ready(JOB, docs(1), result, IMPORTER, adapter=memory) == (WAITING, None)
    assert memory.records == {}


def test_line_without_hs_result_waits_with_reason(capsys):
    """서류에는 2행이 있는데 HS 결과는 1행뿐이면 모든 품목이 확정된 것이 아니다. 어느 행인지 알린다."""
    memory = MemoryWms()
    state, reason = wms.register_if_ready(JOB, docs(1, 2), JobResult(hs=[auto(1)]), IMPORTER, adapter=memory)
    assert (state, reason) == (WAITING, "2행은 HS 결과가 없습니다")
    assert memory.records == {}
    assert "자동 등록 안 함" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("documents", "consignee", "words"),
    [(docs(1, bl=None), IMPORTER, "B/L"), (docs(1), "  ", "수하인")],
    ids=["no-bl", "no-consignee"],
)
def test_record_not_ready_waits_with_reason(documents, consignee, words, capsys):
    memory = MemoryWms()
    state, reason = wms.register_if_ready(JOB, documents, JobResult(hs=[auto(1)]), consignee, adapter=memory)
    assert state == WAITING and words in reason
    assert memory.records == {}
    assert "자동 등록 안 함" in capsys.readouterr().out


def test_storage_error_waits_with_reason_without_raising(capsys):
    """등록 실패가 HS 선택 저장 같은 앞 단계를 막지 않는다. 사람이 승인하면 그때 다시 등록한다."""
    broken = BrokenWms()
    state, reason = wms.register_if_ready(JOB, docs(1), JobResult(hs=[auto(1)]), IMPORTER, adapter=broken)
    assert (state, reason) == (WAITING, "가상 WMS 오류(RuntimeError). 승인하면 다시 등록합니다")
    assert broken.calls == 1
    assert "WMS 자동 등록 실패" in capsys.readouterr().out


def test_wms_setting_error_waits_with_reason(monkeypatch):
    """설정 오류(WMS_TABLE 없음 등)로 가상 WMS를 못 열어도 예외로 올리지 않고 이유에 남긴다."""

    def no_table():
        raise KeyError("WMS_TABLE")

    monkeypatch.setattr(wms, "dynamo_wms", no_table)
    state, reason = wms.register_if_ready(JOB, docs(1), JobResult(hs=[auto(1)]), IMPORTER)
    assert (state, reason) == (WAITING, "가상 WMS 오류(KeyError). 승인하면 다시 등록합니다")


def test_already_registered_is_kept_without_calling_wms():
    registered = WmsState(status="등록됨", by="human", wms_id="wms-9999")
    broken = BrokenWms()
    result = JobResult(hs=[auto(1)], wms=registered)
    assert wms.register_if_ready(JOB, docs(1), result, IMPORTER, adapter=broken) == (registered, None)
    assert broken.calls == 0


def test_default_adapter_is_dynamo_wms(monkeypatch):
    memory = MemoryWms()
    monkeypatch.setattr(wms, "dynamo_wms", lambda: memory)
    state, _ = wms.register_if_ready(JOB, docs(1), JobResult(hs=[auto(1)]), IMPORTER)
    assert state.status == "등록됨" and list(memory.records) == [f"{BL}#{JOB}"]


def test_not_ready_job_does_not_open_wms(monkeypatch):
    """조건을 못 채우면 가상 WMS 연결(dynamo_wms)을 만들지 않는다."""
    opened = []
    monkeypatch.setattr(wms, "dynamo_wms", lambda: opened.append(True) or MemoryWms())
    assert wms.register_if_ready(JOB, docs(1), JobResult(hs=[pending(1)]), IMPORTER) == (WAITING, None)
    assert opened == []
