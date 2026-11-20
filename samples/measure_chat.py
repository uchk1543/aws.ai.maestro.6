"""현황 조회 측정 (E5). 담당: 판독. 규칙: .kiro/steering/agent-design.md 11번 '현황 조회: 질문 20개의 기대 조건·기대 건수와 맞는 수'

eval/queries.csv 질문을 실제 모델로 조건(ChatFilters)으로 바꾸고, 가상 화물 기록(data/seed 또는 samples/data)에서 센 건수를 정답과 맞춘다.
기준일은 --today(기본: 한국 시간 오늘)다. 시드 날짜를 그날로 옮기고(PM이 시드를 넣을 때와 같다), 정답도 그날 날짜로
다시 계산한다 (samples/seed_dates.py, #170). 정답지 그대로(2026-11-21)를 재려면 --today 2026-11-21. 질문 하나에 모델 호출 한 번.

실행:
    export MODEL_ID=<global 추론 프로필 ID>
    uv run python -m samples.measure_chat
    uv run python -m samples.measure_chat --only Q01 Q12 --today 2026-11-21
"""

import argparse
import json
import statistics
import time
from datetime import date
from pathlib import Path

from agent.query_agent import answer
from samples.seed_dates import BASE_DAY, expected_for, load_queries, shift_rows, today_kst
from tests.unit.fakes import MemoryShipments
from tools.models import Shipment

ROOT = Path(__file__).resolve().parent.parent
SEEDS = [ROOT / "data" / "seed" / "shipments.json", ROOT / "samples" / "data" / "shipments.json"]
KEYS = ("status", "period", "date_from", "date_to")


def main() -> None:
    parser = argparse.ArgumentParser(description="현황 조회 측정 (질문 20개)")
    parser.add_argument("--only", nargs="+", help="질문 ID. 예: Q01 Q12")
    parser.add_argument("--today", type=date.fromisoformat, default=None, help="기준일 YYYY-MM-DD (기본: 한국 시간 오늘)")
    args = parser.parse_args()

    today = args.today or today_kst()
    seed = next(p for p in SEEDS if p.exists())
    rows = shift_rows(json.loads(seed.read_text(encoding="utf-8")), today)
    store = MemoryShipments([Shipment.model_validate(r) for r in rows])
    queries = [q for q in load_queries() if not args.only or q["query_id"] in args.only]
    cond_ok = count_ok = 0
    times = []
    for q in expected_for(today, rows, queries):
        expected = q["conditions"]
        started = time.perf_counter()
        res = answer(q["question"], "measure", store=store, today=today)
        times.append(time.perf_counter() - started)
        got = res.filters.model_dump(mode="json")
        same = all(got.get(k) == expected.get(k) for k in KEYS)
        right = len(res.rows) == q["count"]
        cond_ok += same
        count_ok += right
        diff = "" if same else "  조건 " + ", ".join(f"{k}={got.get(k)}(정답 {expected.get(k)})" for k in KEYS if got.get(k) != expected.get(k))
        print(f"{'O' if same and right else 'X'} {q['query_id']} {q['question']} → {len(res.rows)}건 (정답 {q['count']}){diff}")
        print(f"     답: {res.answer}")
    print(f"\n질문 {len(queries)}개 (한 번 측정, 화물 기록 {seed.relative_to(ROOT)}, 기준일 {today}, 시드 날짜 {(today - BASE_DAY).days:+d}일)")
    print(f"  조건 일치 {cond_ok}/{len(queries)}, 건수 일치 {count_ok}/{len(queries)}")
    print(f"  시간: 평균 {statistics.mean(times):.1f}초, 최대 {max(times):.1f}초")


if __name__ == "__main__":
    main()
