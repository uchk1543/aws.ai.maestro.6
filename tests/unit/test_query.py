"""query_shipments·resolve_period 단위 테스트 (모델·AWS 호출 없음).

현황 질문 정답지 eval/queries.csv 20문항의 기대 조건을 그대로 넣어, 가상 화물 기록 76건에서 센 건수·기간·규칙이 맞는지 본다.
"""

import csv
import json
from datetime import date
from pathlib import Path

import pytest

from tests.unit.fakes import MemoryShipments
from tools.models import ChatFilters, Shipment
from tools.query import DELAY_RULE, is_delayed, query_shipments, resolve_period

ROOT = Path(__file__).resolve().parents[2]
SHIPMENTS = [Shipment.model_validate(r) for r in json.loads((ROOT / "samples/data/shipments.json").read_text(encoding="utf-8"))]
QUERIES = list(csv.DictReader((ROOT / "eval/queries.csv").open(encoding="utf-8", newline="")))


@pytest.mark.parametrize("q", QUERIES, ids=[q["query_id"] for q in QUERIES])
def test_answer_key_counts(q):
    cond = json.loads(q["expected_conditions"])
    filters = ChatFilters.model_validate({k: cond[k] for k in ("status", "period", "date_from", "date_to")})
    result = query_shipments(filters, store=MemoryShipments(SHIPMENTS), today=date.fromisoformat(cond["today"]))
    assert result.count == int(q["expected_count"]) == len(result.rows)
    got = result.period_resolved.model_dump(mode="json", by_alias=True) if result.period_resolved else None
    assert got == cond["period_resolved"]
    assert result.rule == cond["rule"]


def test_week_is_monday_to_sunday_in_given_today():
    sunday = date(2026, 11, 22)
    p = resolve_period(ChatFilters(period="this_week"), sunday)
    assert (p.from_, p.to) == (date(2026, 11, 16), date(2026, 11, 22))
    p = resolve_period(ChatFilters(period="last_week"), date(2026, 11, 23))  # 월요일이면 지난주는 바로 전 주
    assert (p.from_, p.to) == (date(2026, 11, 16), date(2026, 11, 22))


def test_range_with_one_side_or_reversed():
    one = resolve_period(ChatFilters(period="range", date_from=date(2026, 11, 9)), date(2026, 11, 21))
    assert (one.from_, one.to) == (date(2026, 11, 9), date(2026, 11, 9))
    rev = resolve_period(ChatFilters(period="range", date_from=date(2026, 11, 13), date_to=date(2026, 11, 9)), date(2026, 11, 21))
    assert (rev.from_, rev.to) == (date(2026, 11, 9), date(2026, 11, 13))
    assert resolve_period(ChatFilters(period="range"), date(2026, 11, 21)) is None
    assert resolve_period(ChatFilters(), date(2026, 11, 21)) is None


def ship(arrived: date, status: str, bl: str = "BL-1") -> Shipment:
    return Shipment(bl_no=bl, consignee="샘플무역", item="배터리", arrived_at=arrived, customs_status=status, last_event_at=arrived)


def test_delay_rule_boundary():
    today = date(2026, 11, 21)
    # E1: 입항일 당일이 0일, 3일째부터 지연 (11/17 입항 → 11/20부터)
    assert not is_delayed(ship(date(2026, 11, 17), "심사 중"), date(2026, 11, 19))
    assert is_delayed(ship(date(2026, 11, 17), "심사 중"), date(2026, 11, 20))
    assert is_delayed(ship(date(2026, 11, 18), "심사 중"), today)
    assert not is_delayed(ship(date(2026, 11, 1), "반출"), today)


def test_status_ignores_spaces_and_rows_sorted():
    rows = [ship(date(2026, 11, 19), "검사 중", "B"), ship(date(2026, 11, 17), "검사 중", "A"), ship(date(2026, 11, 17), "수리", "C")]
    result = query_shipments(ChatFilters(status="검사중"), store=MemoryShipments(rows), today=date(2026, 11, 21))
    assert [r.bl_no for r in result.rows] == ["A", "B"] and result.count == 2 and result.rule is None


def test_zero_rows_still_returns_conditions():
    result = query_shipments(
        ChatFilters(status="통관 지연", period="today"), store=MemoryShipments([]), today=date(2026, 11, 21)
    )
    assert result.count == 0 and result.rows == [] and result.rule == DELAY_RULE
    assert result.period_resolved.from_ == date(2026, 11, 21)
