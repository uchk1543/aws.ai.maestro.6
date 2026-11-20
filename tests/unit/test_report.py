"""finish_report 단위 테스트. 상태(JobState)만 보고 조건을 검사한다 (모델·AWS 호출 없음)."""

from tools.models import (
    ExtractedDocument,
    ExtractedItem,
    HSResult,
    Issue,
    IssueCell,
    JobState,
    RereadResult,
)
from tools.report import finish_report, hs_lines

CI, PL = "uploads/s1/invoice.pdf", "uploads/s1/packing.pdf"


def doc(doc_type: str, key: str, lines=(1,)) -> ExtractedDocument:
    return ExtractedDocument(doc_type=doc_type, file=key, items=[ExtractedItem(line=n) for n in lines])


def read_state(**kw) -> JobState:
    """두 서류를 분류·읽고 마지막 읽기 뒤에 대조까지 한 상태."""
    base = dict(
        job_id="job-1",
        files=[CI, PL],
        doc_types={CI: "commercial_invoice", PL: "packing_list"},
        docs={CI: doc("commercial_invoice", CI, (1, 2)), PL: doc("packing_list", PL, (1, 2))},
        read_seq=2,
        check_seq=2,
    )
    return JobState(**{**base, **kw})


MISMATCH = Issue(
    rule_id="X-WT-01",
    grade="불일치",
    cells=[
        IssueCell(doc="commercial_invoice", field="total_gross_kg", raw="6,250 KGS"),
        IssueCell(doc="packing_list", field="total_gross_kg", raw="6,520 KGS"),
    ],
    evidence="상업송장 총중량 6,250kg과 포장명세서 6,520kg이 다릅니다.",
)


def reread(doc_type: str, field: str = "total_gross_kg") -> RereadResult:
    return RereadResult(doc=doc_type, field=field, first_raw="x", second_raw="x", checked_by="pdf_text", same=True)


def hs(line: int) -> HSResult:
    return HSResult(line=line, status="사람 확인 필요")


def test_nothing_done_lists_every_file():
    check = finish_report(JobState(job_id="job-1", files=[CI, PL]))
    assert not check.ok
    assert check.missing == [f"{CI} 아직 분류 안 함 (classify_document)", f"{PL} 아직 분류 안 함 (classify_document)"]


def test_classified_but_not_read():
    state = JobState(job_id="job-1", files=[CI, PL], doc_types={CI: "commercial_invoice", PL: "packing_list"})
    assert finish_report(state, skip={"reread_field", "recommend_hs"}).missing == [
        f"{CI} 아직 안 읽음 (read_document)",
        f"{PL} 아직 안 읽음 (read_document)",
    ]


def test_unknown_is_not_read_and_handed_over_is_skipped():
    """unknown은 읽지 않고 사람에게 묻고, 분류·읽기에 실패해 넘긴 파일은 조건에서 뺀다."""
    other = "uploads/s1/memo.png"
    state = read_state(
        files=[CI, PL, other],
        doc_types={CI: "commercial_invoice", PL: "unknown"},
        docs={CI: doc("commercial_invoice", CI)},
        read_seq=1,
        check_seq=1,
    )
    assert finish_report(state, handed_over={other}, skip={"reread_field", "recommend_hs"}).ok


def test_cross_check_must_follow_last_read():
    check = finish_report(read_state(check_seq=1), skip={"reread_field", "recommend_hs"})
    assert check.missing == ["마지막 읽기 뒤에 대조 안 함 (cross_check)"]


def test_mismatch_cells_need_reread():
    state = read_state(issues=[MISMATCH], hs=[hs(1), hs(2)])
    assert finish_report(state).missing == [
        f"{CI} total_gross_kg 다시 확인 안 함 (reread_field)",
        f"{PL} total_gross_kg 다시 확인 안 함 (reread_field)",
    ]
    state.rereads = [reread("commercial_invoice"), reread("packing_list")]
    assert finish_report(state).ok


def test_only_mismatch_needs_reread():
    checking = MISMATCH.model_copy(update={"grade": "확인 필요"})
    state = read_state(issues=[checking], hs=[hs(1), hs(2)])
    assert finish_report(state).ok


def test_every_item_line_needs_hs():
    state = read_state(hs=[hs(2)])
    assert finish_report(state).missing == ["1행 HS 안 돌림 (recommend_hs)"]


def test_skip_tools_not_ready_yet():
    """P0: B8·C1·C2가 들어오기 전에는 다시 확인·HS 조건을 뺀다."""
    state = read_state(issues=[MISMATCH])
    assert not finish_report(state).ok
    assert finish_report(state, skip={"reread_field", "recommend_hs"}).ok


def test_hs_lines_prefer_invoice():
    state = read_state(docs={CI: doc("commercial_invoice", CI, (1, 2)), PL: doc("packing_list", PL, (1, 2, 3))})
    assert hs_lines(state) == [1, 2]
    state.docs.pop(CI)
    assert hs_lines(state) == [1, 2, 3]
