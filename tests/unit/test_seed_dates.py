"""samples/seed_dates.py 단위 테스트 (#170 FB13). 모델·AWS 호출 없음.

시드 날짜를 그날로 옮겨도 현황 질문 정답을 그날 날짜로 다시 계산할 수 있는지 본다.
그날 정답은 seed_dates(생성기와 같은 규칙)와 tools/query.py(실제 조회 코드) 두 구현이 같아야 한다.
"""

import importlib.util
import json
import re
from datetime import date, timedelta
from pathlib import Path

import pytest

from samples import seed_dates
from samples.seed_dates import BASE_DAY, expected_for, load_queries, shift_rows
from tests.unit.fakes import MemoryShipments
from tools import query
from tools.models import ChatFilters, Shipment

ROOT = Path(__file__).resolve().parents[2]
SEED = json.loads((ROOT / "data" / "seed" / "shipments.json").read_text(encoding="utf-8"))
QUERIES = load_queries()
# 리허설(금) · 데모(토) · 일요일 · 다음 주 월요일 · 그다음 금요일
DAYS = [date(2026, 11, 20), BASE_DAY, date(2026, 11, 22), date(2026, 11, 23), date(2026, 11, 27)]


def test_base_day_and_rules_match_generator_and_query_code():
    text = (ROOT / "samples" / "make_extra.py").read_text(encoding="utf-8")
    y, m, d = map(int, re.search(r"^TODAY = dt\.date\((\d+), (\d+), (\d+)\)", text, re.M).groups())
    assert BASE_DAY == date(y, m, d)  # 시드·정답을 만든 기준일
    assert (seed_dates.DELAY_STATUS, seed_dates.DELAY_DAYS) == (query.DELAY_STATUS, query.DELAY_DAYS)
    assert set(seed_dates.CLEARED) == set(query.CLEARED)


def test_shift_keeps_base_day_and_moves_every_date():
    assert shift_rows(SEED, BASE_DAY) == SEED
    friday = shift_rows(SEED, date(2026, 11, 20))
    for old, new in zip(SEED, friday):
        assert {k: v for k, v in new.items() if k not in ("arrived_at", "last_event_at")} == {
            k: v for k, v in old.items() if k not in ("arrived_at", "last_event_at")
        }
        for k in ("arrived_at", "last_event_at"):
            assert date.fromisoformat(new[k]) == date.fromisoformat(old[k]) - timedelta(days=1)
    assert max(r["arrived_at"] for r in friday) == "2026-11-20"  # 미래에 입항한 화물이 없다
    assert SEED[0]["arrived_at"] == "2026-10-20"  # 원본은 그대로


def test_base_day_answers_are_the_answer_key():
    for q, got in zip(QUERIES, expected_for(BASE_DAY, SEED)):
        cond = json.loads(q["expected_conditions"])
        assert got["query_id"] == q["query_id"] and got["count"] == int(q["expected_count"])
        assert got["conditions"] == cond


@pytest.mark.parametrize("day", DAYS, ids=[d.isoformat() for d in DAYS])
def test_day_answers_match_query_code(day):
    """그날로 옮긴 시드에서 생성기 규칙으로 센 건수 = tools/query.py가 센 건수."""
    rows = shift_rows(SEED, day)
    store = MemoryShipments([Shipment.model_validate(r) for r in rows])
    for got in expected_for(day, rows):
        cond = got["conditions"]
        if cond.get("expect"):  # 조회하지 않아야 하는 질문 (#165)
            assert got["count"] == 0 and cond["today"] == day.isoformat()
            continue
        filters = ChatFilters.model_validate({k: cond[k] for k in ("status", "period", "date_from", "date_to")})
        result = query.query_shipments(filters, store=store, today=day)
        assert result.count == got["count"], got["query_id"]
        resolved = result.period_resolved.model_dump(mode="json", by_alias=True) if result.period_resolved else None
        assert resolved == cond["period_resolved"] and cond["today"] == day.isoformat()
        assert result.rule == cond["rule"]


def test_until_today_follows_the_day():
    """'11월 1일부터 오늘까지'(Q17)는 끝일이 그날이다."""
    [q17] = [a for a in expected_for(date(2026, 11, 20), shift_rows(SEED, date(2026, 11, 20))) if a["query_id"] == "Q17"]
    assert q17["conditions"]["date_to"] == "2026-11-20"
    assert q17["conditions"]["period_resolved"] == {"from": "2026-11-01", "to": "2026-11-20"}


@pytest.mark.parametrize("day", DAYS, ids=[d.isoformat() for d in DAYS])
def test_today_relative_counts_stay_the_same(day):
    """오늘과의 거리로 정하는 질문(오늘 입항, 지금 지연 전체, 상태만 묻기)은 날짜를 옮겨도 건수가 같다."""
    base = {a["query_id"]: a["count"] for a in expected_for(BASE_DAY, SEED)}
    moved = {a["query_id"]: a["count"] for a in expected_for(day, shift_rows(SEED, day))}
    for qid in ("Q03", "Q04", "Q08", "Q15", "Q16", "Q18"):
        assert moved[qid] == base[qid], qid


def test_seed_loader_moves_dates_to_the_day():
    """PM의 infra/seed_shipments.py load()는 넣는 날로 옮긴다. reset_demo.py --all도 이 함수를 쓴다."""
    spec = importlib.util.spec_from_file_location("seed_shipments", ROOT / "infra" / "seed_shipments.py")
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    base = seed.load(seed.seed_file(), today=BASE_DAY)
    friday = seed.load(seed.seed_file(), today=date(2026, 11, 20))
    assert [s.bl_no for s in base] == [s.bl_no for s in friday]
    assert all(f.arrived_at == b.arrived_at - timedelta(days=1) for b, f in zip(base, friday))
    assert [s.model_dump(mode="json") for s in base] == SEED
