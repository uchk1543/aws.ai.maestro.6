"""scripts/e2e_upload.py의 HS 고르기 규칙 (#160). 네트워크·AWS 호출 없음. 담당: PM."""
from scripts.e2e_upload import answer_hs, choices

HS = [
    {"line": 1, "status": "사람 확인 필요", "candidates": [{"hs": "2620210000"}]},
    {"line": 2, "status": "사람 확인 필요", "candidates": [{"hs": "2620210000"}]},
    {"line": 3, "status": "자동 확정", "candidates": []},
]


def test_choose_uses_answer_not_first_candidate():
    picks, skipped = choices(HS, {1: "9401699000", 2: "9403609090", 3: "0000000000"})
    assert picks == [{"line": 1, "hs": "9401699000"}, {"line": 2, "hs": "9403609090"}] and skipped == []


def test_unknown_answer_is_skipped_not_guessed():
    picks, skipped = choices(HS, {1: "9401699000"})
    assert picks == [{"line": 1, "hs": "9401699000"}] and skipped == [2]


def test_answers_come_from_sets_csv():
    answers = answer_hs("D005")
    assert answers == {1: "9401699000", 2: "9403609090"}  # 의자·식탁 (eval/sets.csv)
    assert answer_hs(None) == {} and answer_hs("NOPE") == {}
