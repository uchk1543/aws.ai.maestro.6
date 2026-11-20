"""H2 HS 확정과 자동 처리율 채점 단위 테스트. AWS와 Bedrock을 부르지 않는다. 담당: 검증."""
import pytest

from eval.score import HS_MODES, format_hs_report, load_hs_inputs, score_hs
from tools.hs import CsvHSTable, _norm, _Row, load_hs_table

ANSWER = "8507603000"
TRAP = "8507200000"


def _row(hsk: str, ko: str, en: str) -> _Row:
    return _Row(hsk, ko, en, _norm(ko + " " + en))


@pytest.fixture
def table() -> CsvHSTable:
    return CsvHSTable(
        [
            _row(ANSWER, "에너지 저장장치용", "lithium battery for energy storage"),
            _row(TRAP, "연산 축전지", "lead-acid battery"),
        ]
    )


def _hs_row(sid: str, line: int = 1, item: str = "LITHIUM BATTERY PACK", importer: str = "A사") -> dict:
    return dict(set_id=sid, split="dev", consignee=importer, line=str(line), item=item, hs_answer=ANSWER, trap_hs=TRAP)


def _inputs(rows, *, co_hs=None, inv_hs=None, normal=()):
    return {"rows": rows, "co_hs": co_hs or {}, "inv_hs": inv_hs or {}, "normal": set(normal)}


def test_두번째부터_자동_확정(table):
    r = score_hs(_inputs([_hs_row("D001"), _hs_row("D002")], normal=["D001", "D002"]), table, "none")
    assert (r["rows"], r["auto"], r["by_history"], r["human"]) == (2, 1, 1, 1)
    assert r["wrong_auto"] == 0
    assert (r["normal_sets"], r["auto_registered"]) == (2, 1)  # 첫 세트는 사람 손이 필요하다


def test_수입자가_다르면_이력을_공유하지_않는다(table):
    r = score_hs(_inputs([_hs_row("D001", importer="A사"), _hs_row("D002", importer="B사")]), table, "none")
    assert (r["auto"], r["human"]) == (0, 2)


def test_사람_확인_필요면_정답이_후보_안에_있는지_센다(table):
    r = score_hs(_inputs([_hs_row("D001", item="lithium battery")]), table, "none")
    assert (r["human"], r["human_in_top3"], r["human_in_candidates"]) == (1, 1, 1)
    r = score_hs(_inputs([_hs_row("D001", item="볼트")]), table, "none")
    assert (r["human_in_top3"], r["human_in_candidates"]) == (0, 0)


def test_서류에_정답_10자리가_있고_모델이_정답이면_auto_match(table):
    inputs = _inputs([_hs_row("D001")], co_hs={("D001", 1): ANSWER}, inv_hs={("D001", 1): ANSWER})
    r = score_hs(inputs, table, "oracle")
    assert (r["by_auto_match"], r["wrong_auto"]) == (1, 0)


def test_서류와_모델이_같은_틀린_코드면_틀린_자동_확정으로_센다(table):
    """알려진 한계(C2 PR 본문): 서류 둘과 모델 1순위가 같은 틀린 10자리면 자동 확정된다. 평가가 이를 잡아내는지 본다."""
    inputs = _inputs([_hs_row("D001", item="lead-acid battery")], co_hs={("D001", 1): TRAP}, inv_hs={("D001", 1): TRAP})
    r = score_hs(inputs, table, "trap")
    assert (r["by_auto_match"], r["wrong_auto"], r["trap_auto"]) == (1, 1, 1)


def test_서류가_6자리면_자동_확정_안_됨(table):
    inputs = _inputs([_hs_row("D001")], co_hs={("D001", 1): "850760"}, inv_hs={("D001", 1): "850760"})
    r = score_hs(inputs, table, "oracle")
    assert (r["auto"], r["human"]) == (0, 1)


def test_정상_세트_자동_처리율은_교차검증이_깨끗한_세트만(table):
    rows = [_hs_row("D001"), _hs_row("D002"), _hs_row("D003")]
    r = score_hs(_inputs(rows, normal=["D001", "D002", "D003"]), table, "none", clean_sets={"D001", "D002"})
    assert (r["normal_sets"], r["auto_registered"]) == (3, 1)  # D002만 이력으로 자동, D003은 문제가 남음


def test_정상이_아닌_세트는_자동_처리율에서_뺀다(table):
    r = score_hs(_inputs([_hs_row("D001"), _hs_row("D002")], normal=["D001"]), table, "none")
    assert r["normal_sets"] == 1


def test_모르는_mode는_오류(table):
    with pytest.raises(ValueError):
        score_hs(_inputs([]), table, "model")


def test_보고서는_건수로_쓴다(table):
    text = format_hs_report(score_hs(_inputs([_hs_row("D001")], normal=["D001"]), table, "none"))
    assert "품목 1행" in text and "틀린 것 0건" in text and "정상 1세트 중" in text


def test_실제_정답지로_돌려_틀린_자동_확정이_없다():
    inputs = load_hs_inputs("dev")
    table = load_hs_table()
    for mode in HS_MODES:
        r = score_hs(inputs, table, mode)
        assert r["rows"] == len(inputs["rows"]) > 0
        assert r["auto"] + r["human"] == r["rows"]
        assert r["wrong_auto"] == 0
        assert r["answer_not_in_table"] == 0

def test_bedrock_모드는_모델_함수를_부르고_가짜로_바꾸면_Bedrock을_부르지_않는다(table, monkeypatch):
    """#132: bedrock 모드는 검색어 뽑기와 후보 고르기를 모델에게 맡긴다. 여기서는 _ask_model을 가짜로 바꿔 Bedrock 호출이 없다."""
    import tools.hs as hs_module
    from tools.models import HSCandidate, HSPick, HSSearchTerms

    calls = []

    def fake_ask(prompt, user_text, output_model):
        calls.append(output_model)
        if output_model is HSSearchTerms:
            return HSSearchTerms(terms=["lithium battery"])
        return HSPick(picks=[HSCandidate(hs=ANSWER, name="n", reason="품명 칸")])

    monkeypatch.setattr(hs_module, "_ask_model", fake_ask)
    r = score_hs(_inputs([_hs_row("D001", item="볼트 같은 엉뚱한 품명")]), table, "bedrock")
    assert calls == [HSSearchTerms, HSPick]  # 검색어 한 번, 고르기 한 번
    assert (r["mode"], r["human"], r["human_in_top3"]) == ("bedrock", 1, 1)  # 품명만으로는 못 찾지만 모델 검색어로 찾는다


def test_bedrock_모드는_기본_모드_목록에_없다():
    """돈이 드는 모드라서 --hs만으로는 돌지 않는다."""
    assert "bedrock" not in HS_MODES
