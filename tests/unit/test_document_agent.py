"""문서 처리 Agent(run_job) 단위 테스트. 분류·읽기 모델과 에이전트 모델은 가짜로 대신한다 (Bedrock·AWS 호출 없음).

아직 없는 도구(B8 reread_field·apply_rereads, C1·C2 recommend_hs)도 가짜로 넣어 P1 순서를 미리 본다.
"""

import copy
import json

import pytest
from strands.models import Model

from agent import document_agent
from agent.document_agent import MAX_REASON, MAX_TURNS, run_job
from tools.models import Classification, HSResult, Job, RawDocument, RereadResult

INV, PL, MEMO, BL = "uploads/s1/invoice.pdf", "uploads/s1/packing.pdf", "uploads/s1/memo.png", "uploads/s1/bl.pdf"

CLASSES = {
    "invoice.pdf": ("commercial_invoice", "제목 COMMERCIAL INVOICE, 단가·금액 칸"),
    "packing.pdf": ("packing_list", "제목 PACKING LIST, N.W./G.W. 칸, 단가 칸 없음"),
    "memo.png": ("unknown", "제목 없음, 칸만으로 종류를 정할 수 없음"),
    "bl.pdf": ("bill_of_lading", "제목 BILL OF LADING, Vessel/Voyage·Freight 칸"),
    "co.pdf": ("certificate_of_origin", "제목 CERTIFICATE OF ORIGIN, Origin criterion 칸"),
}
CO = "uploads/s1/co.pdf"
# 송장 번호·총수량은 같고 총중량만 다르다 → cross_check(B7)는 X-WT-01 불일치 하나
RAWS = {
    "invoice.pdf": {
        "doc_no": {"raw": "INV-1"}, "items": [{"line": 1}, {"line": 2}],
        "total_qty": {"raw": "1,000 PCS"}, "total_gross_kg": {"raw": "6,250 KGS"},
    },
    "packing.pdf": {
        "doc_no": {"raw": "INV-1"}, "items": [{"line": 1}, {"line": 2}],
        "total_qty": {"raw": "1,000 PCS"}, "total_gross_kg": {"raw": "6,520 KGS"},
    },
}


def key_of(blocks) -> str:
    """fetch가 키를 바이트로 돌려주므로 블록에서 키를 꺼낸다."""
    block = blocks[0].get("document") or blocks[0].get("image")
    return block["source"]["bytes"].decode()


def name_of(blocks) -> str:
    return key_of(blocks).rsplit("/", 1)[-1]


class Models:
    """분류·읽기 가짜 모델. 부른 파일 이름을 적어 둔다."""

    def __init__(self, classes=CLASSES, raws=RAWS):
        self.classes, self.raws = classes, raws
        self.classified: list[str] = []
        self.read: list[str] = []

    def classifier(self, blocks, prompt):
        self.classified.append(name_of(blocks))
        doc_type, reason = self.classes[name_of(blocks)]
        return Classification(doc_type=doc_type, reason=reason)

    def reader(self, blocks, prompt):
        if "칸 하나만" not in prompt:  # 다시 확인(B8)의 칸 하나 묻기는 읽기로 세지 않는다
            self.read.append(name_of(blocks))
        return RawDocument.model_validate(self.raws[name_of(blocks)])


def fetch(key: str) -> bytes:
    return key.encode()


def files(*keys, typed=()):
    """typed에 든 파일만 사용자가 종류를 정해 올린다. 나머지는 doc_type null."""
    return [{"key": k, "doc_type": CLASSES[k.rsplit("/", 1)[-1]][0] if k in typed else None} for k in keys]


def tools_of(job: Job) -> list[str]:
    return [s.tool for s in job.steps]


# ---------------------------------------------------------------------------
# 고정 순서 (P0 첫 배포)
# ---------------------------------------------------------------------------
def test_null_doc_type_is_classified_then_read():
    m = Models()
    job = run_job("job-1", files(INV, PL), fetch, reader=m.reader, classifier=m.classifier)
    assert tools_of(job) == [
        "classify_document", "classify_document", "read_document", "read_document", "cross_check",
        "reread_field", "reread_field",  # 불일치 칸은 다시 확인 (B8, 텍스트가 아닌 가짜 PDF라 모델 다시 읽기)
    ]
    assert job.steps[0].summary == "invoice.pdf → 상업송장 (제목 COMMERCIAL INVOICE, 단가·금액 칸)"
    assert job.steps[1].summary == "packing.pdf → 포장명세서 (제목 PACKING LIST, N.W./G.W. 칸, 단가 칸 없음)"
    assert job.steps[2].summary == "invoice.pdf → 상업송장, 2행"
    assert all(s.ok for s in job.steps)
    [issue] = job.result.issues
    assert (issue.rule_id, issue.grade, issue.checked_by) == ("X-WT-01", "불일치", "model_reread")
    assert job.status == "waiting_approval"


def test_user_doc_type_is_not_classified_again():
    m = Models()
    job = run_job("job-1", files(INV, PL, typed=(INV,)), fetch, reader=m.reader, classifier=m.classifier)
    assert m.classified == ["packing.pdf"]
    assert tools_of(job).count("classify_document") == 1


def test_unknown_is_not_read_and_asks_human():
    m = Models()
    job = run_job("job-1", files(INV, MEMO), fetch, reader=m.reader, classifier=m.classifier)
    assert m.read == ["invoice.pdf"]
    assert job.steps[1].summary == "memo.png → 알 수 없는 서류 (제목 없음, 칸만으로 종류를 정할 수 없음)"
    assert job.steps[1].ok
    first = job.result.issues[0]
    assert (first.rule_id, first.grade) == ("DOC-UNKNOWN", "확인 필요")
    assert (first.cells[0].doc, first.cells[0].field) == ("unknown", "doc_type")
    assert "memo.png" in first.evidence and "종류를 골라" in first.evidence
    assert job.status == "waiting_approval"


def test_user_unknown_also_asks_human():
    m = Models()
    job = run_job("job-1", [{"key": MEMO, "doc_type": "unknown"}], fetch, reader=m.reader, classifier=m.classifier)
    assert m.classified == [] and m.read == [] and job.steps == []
    assert job.result.issues[0].rule_id == "DOC-UNKNOWN" and job.status == "waiting_approval"


def test_bill_of_lading_and_origin_are_read():
    """선하증권은 읽어서 대조(X-WT-01 3자)에 넣고, 원산지증명서도 읽는다 (B2 P1 #11). 4종을 모두 읽으면 '참고'(DOC-LATER)는 없다."""
    bl = {"doc_no": {"raw": "BL-1"}, "total_gross_kg": {"raw": "6,250 KGS"}, "consignee_name": {"raw": "EXAMPLE CO., LTD."}}
    co = {"doc_no": {"raw": "INV-1"}, "items": [{"line": 1}, {"line": 2}]}
    m = Models(raws={**RAWS, "packing.pdf": RAWS["invoice.pdf"], "bl.pdf": bl, "co.pdf": co})
    job = run_job("job-1", files(INV, PL, BL, CO), fetch, reader=m.reader, classifier=m.classifier)
    assert job.steps[2].summary == "bl.pdf → 선하증권 (제목 BILL OF LADING, Vessel/Voyage·Freight 칸)"
    assert sorted(m.read) == ["bl.pdf", "co.pdf", "invoice.pdf", "packing.pdf"]
    assert job.result.issues == []
    assert job.status == "done"


def test_bill_of_lading_weight_joins_the_majority_check():
    """총중량이 셋이면 다수결로 다른 쪽을 짚는다 (agent-design.md 3번): 송장·B/L 6,250, 포장명세서 6,520 → 포장명세서."""
    bl = {"doc_no": {"raw": "BL-1"}, "total_gross_kg": {"raw": "6,250 KGS"}}
    m = Models(raws={**RAWS, "bl.pdf": bl})
    job = run_job("job-1", files(INV, PL, BL), fetch, reader=m.reader, classifier=m.classifier)
    [issue] = [i for i in job.result.issues if i.rule_id == "X-WT-01"]
    assert issue.grade == "불일치" and issue.suspect == "packing_list"


def test_classify_failure_is_not_ok_and_not_read():
    m = Models()

    def classifier(blocks, prompt):
        if name_of(blocks) == "packing.pdf":
            raise RuntimeError("모델 오류")
        return m.classifier(blocks, prompt)

    job = run_job("job-1", files(INV, PL), fetch, reader=m.reader, classifier=classifier)
    fail = job.steps[1]
    assert fail.tool == "classify_document" and not fail.ok
    assert fail.summary.startswith("packing.pdf 분류 실패: 모델 호출 실패: RuntimeError")
    assert m.read == ["invoice.pdf"]
    assert job.result.issues[0].rule_id == "CLASSIFY-FAIL"
    assert all(i.rule_id != "REPORT-INCOMPLETE" for i in job.result.issues)  # 넘긴 파일은 조건에서 뺀다
    assert job.status == "waiting_approval"


def test_long_reason_is_cut_for_screen():
    long = "제목 COMMERCIAL INVOICE, " + "단가 칸 " * 30
    m = Models(classes={**CLASSES, "invoice.pdf": ("commercial_invoice", long)})
    job = run_job("job-1", files(INV), fetch, reader=m.reader, classifier=m.classifier)
    reason = job.steps[0].summary.split(" (", 1)[1][:-1]
    assert len(reason) == MAX_REASON and reason.endswith("…")


def test_each_file_is_fetched_once():
    calls = []

    def counting_fetch(key):
        calls.append(key)
        return key.encode()

    m = Models()
    run_job("job-1", files(INV, PL), counting_fetch, reader=m.reader, classifier=m.classifier)
    assert sorted(calls) == sorted([INV, PL])


def test_on_step_gets_running_job_after_each_step():
    seen: list[Job] = []
    m = Models()
    job = run_job("job-1", files(INV, PL), fetch, reader=m.reader, classifier=m.classifier, on_step=seen.append)
    assert [j.status for j in seen] == ["running"] * len(job.steps)
    assert [len(j.steps) for j in seen] == list(range(1, len(job.steps) + 1))
    assert seen[-1].steps == job.steps and all(j.result is None for j in seen)


def test_on_step_failure_does_not_stop_job():
    def broken(job):
        raise RuntimeError("DynamoDB 오류")

    m = Models()
    job = run_job("job-1", files(INV, PL), fetch, reader=m.reader, classifier=m.classifier, on_step=broken)
    assert job.status == "waiting_approval" and len(job.steps) == 7


def test_on_docs_gets_read_docs_in_files_order_once():  # #122
    got: list[list] = []
    m = Models()
    job = run_job("job-1", files(PL, MEMO, INV), fetch, reader=m.reader, classifier=m.classifier, on_docs=got.append)
    [docs] = got
    assert [d.doc_type for d in docs] == ["packing_list", "commercial_invoice"]  # 못 읽은 memo는 빠지고 files 순서
    assert [d.file for d in docs] == [PL, INV]
    assert job.status == "waiting_approval"


def test_on_docs_not_called_without_read_docs():
    got: list = []
    m = Models()
    run_job("job-1", files(MEMO), fetch, reader=m.reader, classifier=m.classifier, on_docs=got.append)
    assert got == []


def test_on_docs_on_crash_and_its_failure_does_not_change_job(monkeypatch):
    got: list[list] = []

    def crash(run):
        run.read(INV)
        raise RuntimeError("예상 못 한 오류")

    monkeypatch.setattr(document_agent, "_run_fixed", crash)
    m = Models()
    with pytest.raises(RuntimeError):
        run_job("job-1", files(INV, PL, typed=(INV, PL)), fetch, reader=m.reader, on_docs=got.append)
    assert [d.file for d in got[0]] == [INV]  # 멈추기 전까지 읽은 서류는 넘긴다
    monkeypatch.undo()

    def broken(docs):
        raise RuntimeError("DynamoDB 오류")

    job = run_job("job-1", files(INV, PL, typed=(INV, PL)), fetch, reader=Models().reader, on_docs=broken)
    assert job.status == "waiting_approval" and len(job.steps) == 5


def test_p0_finishes_without_later_tools():
    """B8·C1·C2가 없으면 다시 확인·HS를 부르지 않고 finish_report 조건에서도 뺀다."""
    m = Models(raws={**RAWS, "packing.pdf": RAWS["invoice.pdf"]})
    job = run_job("job-1", files(INV, PL, typed=(INV, PL)), fetch, reader=m.reader)
    assert tools_of(job) == ["read_document", "read_document", "cross_check"]
    assert job.status == "done" and job.result.issues == [] and job.result.hs == []


def test_cross_check_crash_is_report_incomplete(monkeypatch):
    def crash(docs):
        raise ValueError("규칙 표 오류")

    monkeypatch.setattr(document_agent, "cross_check", crash)
    m = Models()
    job = run_job("job-1", files(INV, PL, typed=(INV, PL)), fetch, reader=m.reader)
    assert tools_of(job) == ["read_document", "read_document", "cross_check", "finish_report"]
    assert [s.ok for s in job.steps] == [True, True, False, False]
    last = job.result.issues[-1]
    assert (last.rule_id, last.grade) == ("REPORT-INCOMPLETE", "확인 필요") and "cross_check" in last.evidence
    assert job.status == "waiting_approval"


# 아직 없는 도구 (가짜) ------------------------------------------------------
def fake_rereader(calls: list):
    """B8 reread_field 대신: 첫 판독 raw를 그대로 다시 찾았다고 돌려준다."""

    def rereader(doc, field, data):
        calls.append((doc.doc_type, field))
        raw = getattr(doc, field).raw
        return RereadResult(doc=doc.doc_type, field=field, first_raw=raw, second_raw=raw, checked_by="pdf_text", same=True)

    return rereader


def fake_apply(issues, rereads):
    """B8 apply_rereads 대신: 두 근거가 같으면 불일치는 그대로 두고 checked_by만 채운다."""
    return [i.model_copy(update={"checked_by": "pdf_text"}) if i.grade == "불일치" else i for i in issues]


def fake_hs(calls: list):
    """C1·C2 recommend_hs 대신: 모든 행을 사람 확인 필요로 돌려준다."""

    def recommend(docs, line):
        calls.append(line)
        return HSResult(line=line, status="사람 확인 필요")

    return recommend


def test_later_tools_run_in_order(monkeypatch):
    monkeypatch.setattr(document_agent, "apply_rereads", fake_apply)
    rereads, lines = [], []
    m = Models()
    job = run_job(
        "job-1", files(INV, PL), fetch, reader=m.reader, classifier=m.classifier,
        rereader=fake_rereader(rereads), hs_recommender=fake_hs(lines),
    )
    assert tools_of(job) == [
        "classify_document", "classify_document", "read_document", "read_document", "cross_check",
        "reread_field", "reread_field", "recommend_hs", "recommend_hs",
    ]
    assert rereads == [("commercial_invoice", "total_gross_kg"), ("packing_list", "total_gross_kg")]
    assert job.steps[5].summary == "상업송장 total_gross_kg: PDF 글자에서 6,250 KGS (첫 판독과 같음)"
    assert job.steps[7].summary == "1행 → 사람 확인 필요 (후보 0개)"
    assert lines == [1, 2] and [h.line for h in job.result.hs] == [1, 2]
    [issue] = job.result.issues
    assert issue.checked_by == "pdf_text"
    assert job.status == "waiting_approval"


# ---------------------------------------------------------------------------
# 에이전트 루프 (가짜 Strands 모델)
# ---------------------------------------------------------------------------
class ScriptedModel(Model):
    """정해 둔 차례대로 도구를 부르는 가짜 Strands 모델. 차례가 끝나면 글로 답하고 멈춘다."""

    def __init__(self, turns):
        self.turns = [list(t) for t in turns]
        self.calls = 0
        self.seen: list = []  # 차례마다 받은 메시지
        self.tool_names: set[str] = set()

    def update_config(self, **model_config):
        pass

    def get_config(self):
        return {}

    async def structured_output(self, output_model, prompt, system_prompt=None, **kwargs):
        raise NotImplementedError
        yield  # pragma: no cover

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        self.calls += 1
        self.seen.append(copy.deepcopy(messages))
        self.tool_names = {spec["name"] for spec in tool_specs or []}
        turn = self.turns.pop(0) if self.turns else []
        yield {"messageStart": {"role": "assistant"}}
        if not turn:
            yield {"contentBlockStart": {"start": {}}}
            yield {"contentBlockDelta": {"delta": {"text": "끝"}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}
            return
        for i, (name, args) in enumerate(turn):
            yield {"contentBlockStart": {"start": {"toolUse": {"toolUseId": f"t{self.calls}-{i}", "name": name}}}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(args, ensure_ascii=False)}}}}
            yield {"contentBlockStop": {}}
        yield {"messageStop": {"stopReason": "tool_use"}}


def text(messages) -> str:
    return json.dumps(messages, ensure_ascii=False, default=str)


def test_agent_picks_tools_and_finish_report_ends_loop():
    m = Models()
    model = ScriptedModel([
        [("classify_document", {"key": INV}), ("classify_document", {"key": PL})],
        [("read_document", {"key": INV}), ("read_document", {"key": PL})],
        [("cross_check", {})],
        [("reread_field", {"key": INV, "field": "total_gross_kg"}), ("reread_field", {"key": PL, "field": "total_gross_kg"})],
        [("finish_report", {})],
        [("cross_check", {})],  # finish_report가 통과하면 이 차례는 오지 않는다
    ])
    job = run_job("job-1", files(INV, PL), fetch, reader=m.reader, classifier=m.classifier, agent_model=model)
    assert model.calls == 5
    # HS(C1·C2)는 처리 Lambda가 넘기지 않았으니 도구로 주지 않는다
    assert model.tool_names == {"classify_document", "read_document", "cross_check", "reread_field", "finish_report"}
    assert f"{INV}: 종류 미정" in text(model.seen[0])
    assert tools_of(job) == ["classify_document"] * 2 + ["read_document"] * 2 + ["cross_check"] + ["reread_field"] * 2 + ["finish_report"]
    assert (job.steps[-1].summary, job.steps[-1].ok) == ("조건을 모두 채움", True)
    assert job.result.issues[0].rule_id == "X-WT-01" and job.status == "waiting_approval"


def test_finish_report_sends_agent_back_for_missing():
    m = Models()
    model = ScriptedModel([
        [("classify_document", {"key": INV}), ("classify_document", {"key": PL})],
        [("read_document", {"key": INV})],
        [("cross_check", {})],
        [("finish_report", {})],
        [("read_document", {"key": PL})],
        [("cross_check", {})],
        [("reread_field", {"key": INV, "field": "total_gross_kg"}), ("reread_field", {"key": PL, "field": "total_gross_kg"})],
        [("finish_report", {})],
    ])
    job = run_job("job-1", files(INV, PL), fetch, reader=m.reader, classifier=m.classifier, agent_model=model)
    reports = [s for s in job.steps if s.tool == "finish_report"]
    assert [r.ok for r in reports] == [False, True]
    assert reports[0].summary == f"빠진 것 1개: {PL} 아직 안 읽음 (read_document)"
    assert "아직 빠진 것" in text(model.seen[4])  # 에이전트는 빠진 것 목록을 도구 결과로 받았다
    assert model.calls == 8 and sorted(m.read) == ["invoice.pdf", "packing.pdf"]


def test_agent_cannot_override_user_doc_type():
    m = Models()
    model = ScriptedModel([
        [("classify_document", {"key": INV})],
        [("read_document", {"key": INV})],
        [("cross_check", {})],
        [("finish_report", {})],
    ])
    run_job("job-1", files(INV, typed=(INV,)), fetch, reader=m.reader, classifier=m.classifier, agent_model=model)
    assert m.classified == []
    assert "사용자가 정한 종류" in text(model.seen[1])


def test_turn_limit_then_code_finishes():
    m = Models()
    model = ScriptedModel([[("cross_check", {})]] * 30)  # 엉뚱한 도구만 계속 부른다
    job = run_job("job-1", files(INV, PL), fetch, reader=m.reader, classifier=m.classifier, agent_model=model)
    assert model.calls == MAX_TURNS
    reports = [s for s in job.steps if s.tool == "finish_report"]
    assert reports[0].summary.startswith("에이전트가 다 못 끝낸 것을 코드가 이어서 함: ") and not reports[0].ok
    assert (reports[-1].summary, reports[-1].ok) == ("조건을 모두 채움", True)
    assert sorted(m.read) == ["invoice.pdf", "packing.pdf"]
    assert job.result.issues[0].rule_id == "X-WT-01"


def test_agent_error_falls_back_to_code():
    class Broken(ScriptedModel):
        async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
            raise RuntimeError("Bedrock 오류")
            yield  # pragma: no cover

    m = Models()
    job = run_job("job-1", files(INV, PL), fetch, reader=m.reader, classifier=m.classifier, agent_model=Broken([]))
    assert (job.steps[0].tool, job.steps[0].ok) == ("agent", False)
    assert "Bedrock 오류" in job.steps[0].summary
    assert tools_of(job).count("read_document") == 2
    assert job.steps[-1].summary == "조건을 모두 채움"


def test_agent_with_later_tools(monkeypatch):
    monkeypatch.setattr(document_agent, "apply_rereads", fake_apply)
    rereads, lines = [], []
    m = Models()
    model = ScriptedModel([
        [("read_document", {"key": INV}), ("read_document", {"key": PL})],
        [("cross_check", {})],
        [("finish_report", {})],
        [("reread_field", {"key": INV, "field": "total_gross_kg"}), ("reread_field", {"key": PL, "field": "total_gross_kg"})],
        [("recommend_hs", {"line": 1}), ("recommend_hs", {"line": 2})],
        [("finish_report", {})],
    ])
    job = run_job(
        "job-1", files(INV, PL, typed=(INV, PL)), fetch, reader=m.reader,
        rereader=fake_rereader(rereads), hs_recommender=fake_hs(lines), agent_model=model,
    )
    assert "reread_field" in model.tool_names and "recommend_hs" in model.tool_names
    reports = [s for s in job.steps if s.tool == "finish_report"]
    assert [r.ok for r in reports] == [False, True]
    assert "(reread_field)" in reports[0].summary and "(recommend_hs)" in reports[0].summary
    assert sorted(rereads) == [("commercial_invoice", "total_gross_kg"), ("packing_list", "total_gross_kg")]
    assert sorted(lines) == [1, 2]
    assert job.result.issues[0].checked_by == "pdf_text"
