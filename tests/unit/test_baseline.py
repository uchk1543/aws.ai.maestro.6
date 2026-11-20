"""모델 단독 기준선(H3) 단위 테스트. 모델은 부르지 않는다."""

from eval import baseline
from eval.baseline import Answer, blocks_for, load_dev_sets, score, to_issues


def test_dev_sets_have_invoice_and_packing_list_paths():
    sets = load_dev_sets(["D003", "D005"])
    assert sets["D003"]["commercial_invoice"].name == "doc_a.pdf"
    assert sets["D005"]["commercial_invoice"].name == "doc_b.pdf"  # 자리는 세트마다 sets.csv를 따른다
    assert sets["D005"]["packing_list"].name == "doc_a.pdf"


def test_two_documents_get_different_names():
    blocks = blocks_for(load_dev_sets(["D003"])["D003"])
    names = [b["document"]["name"] for b in blocks if "document" in b]
    assert names == ["Commercial Invoice", "Packing List"]


def test_findings_become_hard_issues_on_both_docs():
    answer = Answer.model_validate({"findings": [
        {"field": "total_gross_kg", "commercial_invoice_raw": "21,683.10", "packing_list_raw": "12,683.10", "evidence": "다름"}]})
    [issue] = to_issues(answer)
    assert issue.grade == "불일치"
    assert [(c.doc, c.field) for c in issue.cells] == [("commercial_invoice", "total_gross_kg"), ("packing_list", "total_gross_kg")]


def test_rescore_counts_detection_and_skips_failed_sets():
    hit = {"findings": [{"field": "total_gross_kg", "commercial_invoice_raw": "a", "packing_list_raw": "b", "evidence": "다름"}]}
    results = {"D003": {"answer": hit, "seconds": 1.0}, "D005": {"answer": {"findings": []}, "seconds": 1.0},
               "D001": {"error": "RuntimeError: x", "seconds": 0.1}}
    r = score(results)
    assert (r["planted"], r["detected"]) == (1, 1)  # D003 총중량 자리 바꿈
    assert (r["normal_sets"], r["false_positive_sets"]) == (1, 0)
    assert r["not_run_sets"] == 75 - 2


def test_saved_dev_answers_rescore_without_model():
    import json

    saved = json.loads((baseline.EVAL_DIR / "results" / "baseline_dev.json").read_text(encoding="utf-8"))
    r = score(saved)
    assert r["not_run_sets"] == 0 and r["planted"] == 37
