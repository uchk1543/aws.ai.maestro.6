"""10회 반복 측정(H4) 단위 테스트. run_job은 가짜로 바꿔 모델·AWS를 부르지 않는다."""

from agent import document_agent
from eval import repeat
from tools.models import HSResult, Issue, IssueCell, Job, JobResult, Step


def job(status="waiting_approval", grade="불일치", reason="제목 COMMERCIAL INVOICE"):
    issue = Issue(rule_id="X-WT-01", grade=grade, cells=[IssueCell(doc="packing_list", field="total_gross_kg", raw="1"),
                                                         IssueCell(doc="commercial_invoice", field="total_gross_kg", raw="2")],
                  evidence="근거 문장은 비교하지 않는다")
    hs = HSResult(line=1, status="사람 확인 필요", candidates=[])
    return Job(job_id="job-x", status=status, steps=[Step(tool="classify_document", summary=f"doc_a.pdf → 상업송장 ({reason})", ok=True)],
               result=JobResult(issues=[issue], hs=[hs]))


def test_verdict_ignores_evidence_reason_and_cell_order():
    a = repeat.verdict(job(reason="이유 A"), {"doc_a.pdf": "상업송장"})
    b = repeat.verdict(job(reason="이유 B"), {"doc_a.pdf": "상업송장"})
    assert a == b
    assert a["issues"] == [["X-WT-01", "불일치", ["commercial_invoice:total_gross_kg", "packing_list:total_gross_kg"]]]


def test_summary_counts_same_and_different_verdicts():
    same = {"seconds": 1.0, "verdict": repeat.verdict(job(), {})}
    other = {"seconds": 2.0, "verdict": repeat.verdict(job(grade="확인 필요"), {})}
    [line, diff] = repeat.summarize({"D003": [same, same, other]})
    assert line.startswith("- D003: 3번 중 2번 같은 판정, 판정 2가지")
    assert diff.startswith("    다른 판정 1번:")


def test_each_run_uses_new_empty_history_and_parses_doc_types(monkeypatch):
    histories = []

    def fake_run_job(job_id, files, fetch, *, hs_recommender=None, **kw):
        assert all(f["doc_type"] is None for f in files)  # 화면처럼 분류부터
        histories.append(hs_recommender)
        return job()

    monkeypatch.setattr(document_agent, "run_job", fake_run_job)
    spec = repeat.load_sets(["D003"])["D003"]
    first = repeat.run_once("D003", spec, 1)
    repeat.run_once("D003", spec, 2)
    assert first["verdict"]["doc_types"] == {"doc_a.pdf": "상업송장"}
    assert histories[0] is not histories[1]
    assert spec["consignee"] and [t for _, t in spec["files"]] == ["commercial_invoice", "packing_list"]


def test_empty_history_starts_empty():
    h = repeat.EmptyHistory()
    assert h.get("수입자", "품목") is None
    h.put("수입자", "품목", "9401619000", "job-1")
    assert h.get("수입자", "품목") == "9401619000" and repeat.EmptyHistory().get("수입자", "품목") is None
