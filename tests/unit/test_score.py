"""eval/score.py 단위 테스트. 가짜 정답지와 가짜 Issue로 센다. AWS와 Bedrock은 부르지 않는다."""

import contextlib
import csv
import io

from eval.score import (
    EVAL_DIR,
    format_report,
    load_answers,
    load_formats,
    oracle_docs,
    score_detection,
    score_fields,
)
from tools.models import Cell, ExtractedDocument, Issue, IssueCell
from tools.validate import cross_check

COLUMNS = ["set_id", "split", "doc", "field", "planted_value", "original_value", "error_type", "expected_rule_id", "line", "phase", "variant"]


def answer(set_id, doc="", field="", error_type="none", phase="", variant="", split="dev"):
    row = dict.fromkeys(COLUMNS, "")
    row.update(set_id=set_id, split=split, doc=doc, field=field, error_type=error_type, phase=phase, variant=variant)
    return row


def issue(grade, *cells, rule_id="X-WT-01"):
    return Issue(
        rule_id=rule_id, grade=grade, evidence="근거",
        cells=[IssueCell(doc=d, field=f, raw=None) for d, f in cells],
    )


ANSWERS = [
    answer("D1", "packing_list", "total_gross_kg", "decimal_shift", "P0"),
    answer("D2", "commercial_invoice", "invoice_no", "char_swap", "P0"),
    answer("D3"),
    answer("D4", variant="invoice_no_format"),
    answer("D5", "bill_of_lading", "total_gross_kg", "net_as_gross", "P1"),  # P1 줄뿐이면 P0 기준 정상 세트
    answer("T1", "packing_list", "total_qty", "zero_slip", "P0", split="test"),
]
PAIR = ("commercial_invoice", "packing_list")


def test_detects_planted_cell_and_counts_only_dev():
    issues = {"D1": [issue("불일치", ("commercial_invoice", "total_gross_kg"), ("packing_list", "total_gross_kg"))]}
    r = score_detection(ANSWERS, issues, "dev")
    assert (r["planted"], r["detected"]) == (1, 1)  # 결과가 있는 D1만 센다. T1은 test라서 세지 않는다
    assert r["misses"] == []
    assert r["not_run_sets"] == 4  # D2~D5는 결과가 없어 채점하지 않는다
    # D2도 결과를 주면(문제 없음) 놓친 것으로 센다
    r = score_detection(ANSWERS, {**issues, "D2": []}, "dev")
    assert (r["planted"], r["detected"]) == (2, 1)
    assert r["misses"] == [{"set_id": "D2", "doc": "commercial_invoice", "field": "invoice_no", "error_type": "char_swap"}]


def test_wrong_cell_is_not_detection():
    # 같은 세트에서 엉뚱한 칸(총수량)을 짚음 → 탐지가 아니다
    issues = {"D1": [issue("불일치", ("commercial_invoice", "total_qty"), ("packing_list", "total_qty"), rule_id="X-QTY-01")]}
    r = score_detection([answer("D1", "packing_list", "total_gross_kg", "decimal_shift", "P0")], issues, "dev")
    assert r["detected"] == 0 and r["wrong_cell_sets"] == 1 and r["extra_hard_issues"] == 1


def test_check_needed_is_flagged_but_not_detected():
    issues = {"D1": [issue("확인 필요", ("packing_list", "total_gross_kg"))]}
    r = score_detection([answer("D1", "packing_list", "total_gross_kg", "decimal_shift", "P0")], issues, "dev")
    assert (r["detected"], r["flagged"]) == (0, 1)


def test_row_level_cells_fold_into_document_total():
    # 약속 2 예시: items[0].gross_kg로 짚어도 서류 전체 값(total_gross_kg)으로 묶어 센다
    issues = {"D1": [issue("불일치", ("packing_list", "items[0].gross_kg"))]}
    r = score_detection([answer("D1", "packing_list", "total_gross_kg", "decimal_shift", "P0")], issues, "dev")
    assert r["detected"] == 1


def test_doc_no_counts_as_invoice_no():
    issues = {"D2": [issue("불일치", ("commercial_invoice", "doc_no"), ("packing_list", "doc_no"), rule_id="X-INV-01")]}
    r = score_detection([answer("D2", "commercial_invoice", "invoice_no", "char_swap", "P0")], issues, "dev")
    assert r["detected"] == 1


def test_false_positive_counted_on_normal_sets_only_for_hard_issues():
    issues = {
        "D3": [issue("불일치", ("commercial_invoice", "total_qty"), rule_id="X-QTY-01")],  # 오탐
        "D4": [issue("참고", ("packing_list", "doc_no"), rule_id="X-INV-01")],  # 참고는 괜찮다
        "D5": [issue("확인 필요", ("packing_list", "total_qty"), rule_id="X-QTY-01")],  # 확인 필요만
    }
    r = score_detection(ANSWERS, issues, "dev")
    assert r["normal_sets"] == 3
    assert r["false_positive_sets"] == 1 and r["false_positives"][0]["set_id"] == "D3"
    assert r["check_needed_sets"] == 1
    assert r["by_variant"]["invoice_no_format"] == {"sets": 1, "false_positive_sets": 0}


def test_variant_false_positive_is_reported_by_variant():
    issues = {"D4": [issue("불일치", ("packing_list", "doc_no"), rule_id="X-INV-01")]}
    r = score_detection(ANSWERS, issues, "dev")
    assert r["by_variant"]["invoice_no_format"] == {"sets": 1, "false_positive_sets": 1}


def test_p1_only_set_is_normal_for_p0():
    # D5는 B/L 오류(P1)만 있다. P0 기준으로는 정상 세트이고, P0 불일치가 나오면 오탐이다
    r = score_detection(ANSWERS, {"D5": []}, "dev")
    assert r["normal_sets"] == 1 and r["planted"] == 0
    r = score_detection(ANSWERS, {"D5": []}, "dev", phases=("P0", "P1"))
    assert r["planted"] == 1 and r["detected"] == 0 and r["normal_sets"] == 0


def test_by_format_uses_sets_csv_formats():
    issues = {"D1": [issue("불일치", ("packing_list", "total_gross_kg"))]}
    r = score_detection(ANSWERS, issues, "dev", fmt_by_doc={("D1", "packing_list"): "scan"})
    assert r["by_format"] == {"scan": {"detected": 1, "planted": 1}}


def write_fields(tmp_path, rows):
    path = tmp_path / "fields.csv"
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["set_id", "doc", "field", "answer"])
        writer.writerows(rows)
    return path


def read_doc(doc_type, no=None, qty=None, kg=None):
    return ExtractedDocument(
        doc_type=doc_type, file=f"f/{doc_type}",
        doc_no=Cell(raw=no, value=no) if no else None,
        total_qty=Cell(raw=str(qty), value=qty) if qty is not None else None,
        total_gross_kg=Cell(raw=str(kg), value=kg) if kg is not None else None,
    )


def test_score_fields_counts_cells_and_docs(tmp_path):
    path = write_fields(tmp_path, [
        ("D1", "commercial_invoice", "invoice_no", "QDT/26/0289"),
        ("D1", "commercial_invoice", "total_qty", "2650"),
        ("D1", "commercial_invoice", "total_gross_kg", "842.7"),
        ("D1", "commercial_invoice", "exporter_name", "채점 대상 아님"),
        ("D1", "bill_of_lading", "total_gross_kg", "842.7"),  # P0 서류가 아니라 세지 않는다
    ])
    docs = {"D1": [read_doc("commercial_invoice", no="QDT/26/0289", qty=2650, kg=842.0)]}  # 총중량을 틀리게 읽음
    r = score_fields(path, docs)
    assert (r["docs"], r["docs_correct"]) == (1, 0)
    assert (r["cells"], r["cells_correct"]) == (3, 2)
    assert r["by_field"]["total_gross_kg"] == {"correct": 0, "total": 1}
    assert r["wrong"] == [{"set_id": "D1", "doc": "commercial_invoice", "field": "total_gross_kg", "answer": "842.7", "read": 842.0}]


def test_score_fields_separates_unread_from_wrong(tmp_path):
    path = write_fields(tmp_path, [("D1", "packing_list", "total_qty", "100"), ("D1", "packing_list", "invoice_no", "A-1")])
    docs = {"D1": [read_doc("packing_list", qty=None, no="A-2")]}
    r = score_fields(path, docs)
    assert r["unread"] == 1 and r["cells_correct"] == 0
    assert [w["field"] for w in r["wrong"]] == ["invoice_no"]  # 못 읽은 칸은 틀림 목록에 넣지 않는다


def test_score_fields_missing_doc_and_unrun_set(tmp_path):
    path = write_fields(tmp_path, [("D1", "packing_list", "total_qty", "100"), ("D2", "packing_list", "total_qty", "5")])
    r = score_fields(path, {"D1": []})  # D2는 읽지 않았으므로 채점하지 않는다
    assert r["docs"] == 1 and r["missing_docs"] == 1


def test_invoice_no_must_match_exactly(tmp_path):
    # 읽기 채점은 구분 기호를 맞춰 주지 않는다. 글자가 그대로 같아야 한다
    path = write_fields(tmp_path, [("D1", "packing_list", "invoice_no", "QDT/26/0279")])
    r = score_fields(path, {"D1": [read_doc("packing_list", no="QDT26/0279")]})
    assert r["cells_correct"] == 0


def test_format_report_uses_counts_not_percentages():
    issues = {"D1": [issue("불일치", ("packing_list", "total_gross_kg"))], "D2": [], "D3": []}
    text = format_report(score_detection(ANSWERS, issues, "dev"))
    assert "심은 오류 2건 중 1건 탐지" in text
    assert "정상 세트 1세트 중 오탐 0세트" in text
    assert "%" not in text
    assert "놓침: D2 commercial_invoice.invoice_no (char_swap)" in text


def test_dev_answer_key_scored_with_oracle_reads_has_no_miss_and_no_false_positive():
    """정답 값(오류 포함)을 그대로 읽은 것처럼 두고 규칙만 채점한다. 읽기 오류가 없을 때의 상한이다."""
    docs = oracle_docs()
    with contextlib.redirect_stdout(io.StringIO()):
        issues = {s: cross_check(d) for s, d in docs.items() if len(d) >= 2}
    r = score_detection(load_answers(), issues, "dev", fmt_by_doc=load_formats())
    assert r["planted"] > 0 and r["normal_sets"] > 0
    assert r["misses"] == []
    assert r["false_positive_sets"] == 0
    fields = score_fields(EVAL_DIR / "fields.csv", docs)
    assert fields["cells_correct"] == fields["cells"] > 0

# FB06 #163에서 만든 P1 규칙 4개가 잡아야 하는 심은 오류 (정답지의 P1 줄)
FB06_PLANTED = {
    ("D011", "bill_of_lading", "total_packages"),  # X-PKG-01
    ("D016", "bill_of_lading", "container_no"),  # X-CNTR-01
    ("D046", "certificate_of_origin", "invoice_no"),  # X-INV-01 (원산지증명서)
    ("D053", "commercial_invoice", "total_amount"),  # X-SUM-01
}


def _score_p1_oracle():
    docs = oracle_docs(with_p1=True)
    with contextlib.redirect_stdout(io.StringIO()):
        issues = {s: cross_check(d) for s, d in docs.items() if len(d) >= 2}
    return score_detection(load_answers(), issues, "dev", phases=("P0", "P1"), fmt_by_doc=load_formats()), issues


def test_p1_정답_값_채점에서_FB06_규칙_네_개가_심은_오류를_잡는다():
    r, _ = _score_p1_oracle()
    missed = {(m["set_id"], m["doc"], m["field"]) for m in r["misses"]}
    assert not (FB06_PLANTED & missed)  # 심은 네 건은 놓치지 않는다
    assert r["detected"] >= 43  # P0 37건 + FB06 4건 + 선하증권 총중량 2건


def test_p1_정답_값_채점에서_정상_세트_오탐은_0():
    r, _ = _score_p1_oracle()
    assert r["normal_sets"] > 0
    assert r["false_positive_sets"] == 0
    assert r["check_needed_sets"] == 0  # 확인 필요도 정상 세트에는 나오지 않는다


def test_p1_정답_값_채점의_남은_놓침은_발표_뒤로_미룬_규칙뿐():
    """X-HS-01 · X-FRT-01 · X-OC-01 · X-RETRO-01은 이슈 #163이 발표 뒤로 미뤘다. 그 밖의 규칙에서 놓치면 안 된다."""
    r, _ = _score_p1_oracle()
    rule_of = {(a["set_id"], a["doc"], a["field"]): a["expected_rule_id"] for a in load_answers()}
    left = {rule_of[(m["set_id"], m["doc"], m["field"])] for m in r["misses"]}
    assert left <= {"X-HS-01", "X-FRT-01", "X-OC-01", "X-RETRO-01"}, left


def test_기본_oracle은_P0_서류만_만든다():
    docs = oracle_docs()
    assert {d.doc_type for ds in docs.values() for d in ds} == {"commercial_invoice", "packing_list"}


def test_p1_oracle_포장명세서_총포장수는_심기_전_값():
    docs = oracle_docs(with_p1=True)["D011"]
    by_type = {d.doc_type: d for d in docs}
    assert by_type["bill_of_lading"].total_packages.value == 325  # 심은 값
    assert by_type["packing_list"].total_packages.value == 327  # 심기 전 값
    assert by_type["commercial_invoice"].items[0].amount.value == by_type["commercial_invoice"].total_amount.value  # 총금액은 안 틀림


def test_p1_oracle_상업송장_줄_금액은_심기_전_총금액():
    inv = {d.doc_type: d for d in oracle_docs(with_p1=True)["D053"]}["commercial_invoice"]
    assert inv.total_amount.value == 29701 and inv.items[0].amount.value == 29710


def test_p1_oracle_스타일_2_상업송장에는_품목_HS가_찍힌다():
    inv = {d.doc_type: d for d in oracle_docs(with_p1=True)["D067"]}["commercial_invoice"]
    assert inv.items[1].hs_code.raw == "6402.19"  # 심은 헷갈리는 HS (X-HS-01)
    assert sum(it.amount.value for it in inv.items) == inv.total_amount.value  # 2행부터 줄 금액 0이라 X-SUM-01 합이 그대로


def test_p1_oracle_HS_대조는_서류끼리_다른_세트만_잡는다():
    from tools.validate import cross_check

    found = {k for k, v in oracle_docs(with_p1=True).items() for i in cross_check(v) if i.rule_id == "X-HS-01" and i.grade != "참고"}
    assert found == {"D061", "D067"}  # D015·D062는 서류끼리 같은 헷갈리는 HS라 대조로는 못 잡는다
