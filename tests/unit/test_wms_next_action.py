"""작업 화면 맨 위 '다음 할 일' (FB22 #178, tools/wms.next_action). 모델 호출 없음."""

import pytest

from tests.unit.test_wms import issue
from tools import wms
from tools.models import HSResult, Job, JobResult, WmsState

PENDING = HSResult(line=1, status="사람 확인 필요")
CONFIRMED = HSResult(line=2, status="자동 확정", by="history", hs_code="8507609000")


def job(status="waiting_approval", **result) -> Job:
    return Job(job_id="job-0000abcd", status=status, result=JobResult(**result) if result or status != "running" else None)


@pytest.mark.parametrize(
    ("given", "kind", "message", "count"),
    [
        # 불일치가 남으면 HS 가 남아 있어도 서류부터 (승인해도 409)
        (job(issues=[issue("X-WT-01", "불일치"), issue("X-QTY-01", "확인 필요")], hs=[PENDING]),
         "fix_docs", "불일치 1건: 서류를 고쳐 다시 올려야 등록할 수 있습니다", 1),
        (job(issues=[issue("X-WT-01", "불일치"), issue("CNT-ISO", "불일치")]),
         "fix_docs", "불일치 2건: 서류를 고쳐 다시 올려야 등록할 수 있습니다", 2),
        # 불일치가 없고 고를 HS 가 있으면 HS
        (job(issues=[issue("X-QTY-01", "확인 필요")], hs=[PENDING, PENDING.model_copy(update={"line": 3}), CONFIRMED]),
         "choose_hs", "HS 2개를 고르세요", 2),
        # 확인 필요만 남으면 확인 뒤 승인
        (job(issues=[issue("X-QTY-01", "확인 필요"), issue("REF", "참고")], hs=[CONFIRMED]),
         "approve", "확인 필요 1건을 확인한 뒤 승인하세요", 1),
        # 문제 없이 승인만 남음 (자동 등록을 못 한 경우)
        (job(issues=[issue("REF", "참고")], hs=[CONFIRMED], wms=WmsState(status="승인 대기")),
         "approve", "확인한 뒤 승인하세요", None),
        (job("done", hs=[CONFIRMED], wms=WmsState(status="등록됨", by="auto", wms_id="WMS-1")),
         "none", "WMS에 등록됐습니다. 더 할 일이 없습니다", None),
        (job("failed"), "reupload", "처리하지 못했습니다. 서류를 다시 올려 주세요", None),
        (Job(job_id="job-0000abcd", status="running"), "wait", "처리 중입니다. 끝나면 할 일을 알려 드립니다", None),
    ],
)
def test_next_action(given, kind, message, count):
    got = wms.next_action(given)
    assert (got.kind, got.message, got.count) == (kind, message, count)


def test_fix_docs_matches_approve_refusal():
    """화면이 '서류를 고쳐야 한다'고 미리 말하는 건과 승인이 409 로 막히는 건이 같다 (같은 규칙: 불일치가 남음)."""
    for issues in ([issue("X-WT-01", "불일치")], [issue("X-QTY-01", "확인 필요")], []):
        result = JobResult(issues=issues, hs=[CONFIRMED])
        refused = False
        try:
            wms.approve(result)
        except wms.ApprovalRefused:
            refused = True
        assert (wms.next_action(Job(job_id="job-0000abcd", status="waiting_approval", result=result)).kind == "fix_docs") == refused
