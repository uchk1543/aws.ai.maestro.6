"""시드 화물 기록의 날짜를 그날로 옮기고, 현황 질문 정답을 그날 날짜로 다시 계산한다 (#170 FB13). 담당: 판독.

시드(data/seed/shipments.json)와 정답(eval/queries.csv)은 기준일 2026-11-21(토, 데모 날)에 맞춰 만들었다
(samples/make_extra.py TODAY). 리허설·평가를 다른 날 하면 '오늘 입항한 화물'이 미래 날짜가 되고 정답 건수도 달라진다.

- shift_rows: 모든 날짜(입항일·마지막 상태 변경일)를 (그날 − 기준일)만큼 옮긴다. 오늘과의 거리로 정하는 것
  (오늘 입항, 통관 지연, 상태만 묻는 질문)은 건수가 그대로이고, 주(월~일) 경계와 날짜를 적은 질문의 건수만 달라진다.
  PM의 infra/seed_shipments.py load()가 넣는 날(한국 시간 오늘)로 옮긴다. reset_demo.py --all도 이 함수를 거친다.
  그래서 시드는 평가 전·데모 직전, 그날 넣는다.
- expected_for: 그날의 질문별 기대 조건·기간·건수. 생성기(make_extra.queries)와 같은 규칙을 여기 따로 적어
  tools/query.py와 맞춰 본다 (tests/unit/test_seed_dates.py). '오늘까지'(date_to_today)는 끝일을 그날로 바꾼다.
  생성기는 reportlab 등이 필요해 import하지 않는다 (이 파일은 표준 라이브러리만 쓴다).

실행 (그날 정답표 보기, 모델·AWS 호출 없음):
    uv run python -m samples.seed_dates                    # 오늘(한국 시간)
    uv run python -m samples.seed_dates --today 2026-11-20
"""

import argparse
import csv
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
QUERIES = ROOT / "eval" / "queries.csv"
SEED = ROOT / "data" / "seed" / "shipments.json"
BASE_DAY = date(2026, 11, 21)  # 시드·정답을 만든 기준일. samples/make_extra.py TODAY와 같다 (테스트가 본다)
DATE_KEYS = ("arrived_at", "last_event_at")
# 통관 지연 = (오늘 − 입항일) ≥ 3일이고 수리·반출이 아님 (docs/schema.md, E1). tools/query.py와 같다 (테스트가 본다)
DELAY_STATUS, DELAY_DAYS, CLEARED = "통관 지연", 3, ("수리", "반출")


def today_kst() -> date:
    """한국 시간 오늘."""
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


def shift_rows(rows: list[dict], today: date) -> list[dict]:
    """시드 줄(JSON 그대로의 dict) 목록의 날짜를 기준일에서 today로 옮긴 새 목록. 원본은 바꾸지 않는다.

    받는 것: rows(arrived_at·last_event_at이 YYYY-MM-DD), today(넣는 날).
    반환: 날짜만 (today − BASE_DAY)일 옮긴 목록. 기준일이면 같은 값의 사본.
    """
    days = (today - BASE_DAY).days
    out = []
    for row in rows:
        moved = dict(row)
        for key in DATE_KEYS:
            if moved.get(key):
                moved[key] = (date.fromisoformat(moved[key]) + timedelta(days=days)).isoformat()
        out.append(moved)
    return out


def load_queries(path: Path = QUERIES) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _week(d: date) -> tuple[date, date]:
    start = d - timedelta(days=d.weekday())
    return start, start + timedelta(days=6)


def _span(cond: dict, today: date) -> tuple[date, date] | None:
    """기간 조건 → 입항일 범위(양 끝 포함). 주는 월요일부터 일요일까지 (make_extra.resolve와 같다)."""
    period = cond["period"]
    if period == "today":
        return today, today
    if period == "this_week":
        return _week(today)
    if period == "last_week":
        return _week(today - timedelta(days=7))
    if period == "range":
        return date.fromisoformat(cond["date_from"]), date.fromisoformat(cond["date_to"])
    return None


def _delayed(row: dict, today: date) -> bool:
    return (today - date.fromisoformat(row["arrived_at"])).days >= DELAY_DAYS and row["customs_status"] not in CLEARED


def expected_for(today: date, rows: list[dict], queries: list[dict] | None = None) -> list[dict]:
    """그날의 정답표.

    받는 것: today(그날), rows(그날로 옮긴 시드 줄, shift_rows 결과), queries(queries.csv 줄. 없으면 읽는다).
    반환: 질문마다 {"query_id", "question", "conditions", "count"}. conditions는 queries.csv의 expected_conditions 모양이고
      today·period_resolved가 그날 값이다. date_to_today가 참이면 date_to도 그날이다. count는 이 파일의 규칙으로 센 건수.
      조회하지 않아야 하는 질문(expect가 '안내'·'되묻기', #165)은 count 0이다 (rows를 돌려주지 않는다).
    """
    out = []
    for q in queries if queries is not None else load_queries():
        cond = json.loads(q["expected_conditions"])
        if cond.get("expect"):
            cond["today"] = today.isoformat()
            out.append({"query_id": q["query_id"], "question": q["question"], "conditions": cond, "count": 0})
            continue
        if cond.get("date_to_today"):
            cond["date_to"] = today.isoformat()
        span = _span(cond, today)
        status = cond["status"]
        hits = [
            r for r in rows
            if (span is None or span[0] <= date.fromisoformat(r["arrived_at"]) <= span[1])
            and (status is None or (_delayed(r, today) if status == DELAY_STATUS else r["customs_status"] == status))
        ]
        cond["today"] = today.isoformat()
        cond["period_resolved"] = {"from": span[0].isoformat(), "to": span[1].isoformat()} if span else None
        out.append({"query_id": q["query_id"], "question": q["question"], "conditions": cond, "count": len(hits)})
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="그날 날짜로 옮긴 시드의 현황 질문 정답표 (모델·AWS 호출 없음)")
    parser.add_argument("--today", type=date.fromisoformat, default=None, help="YYYY-MM-DD. 없으면 한국 시간 오늘")
    args = parser.parse_args()
    today = args.today or today_kst()
    rows = shift_rows(json.loads(SEED.read_text(encoding="utf-8")), today)
    print(f"기준일 {BASE_DAY} → {today} ({(today - BASE_DAY).days:+d}일), 화물 기록 {len(rows)}건")
    for a in expected_for(today, rows):
        span = a["conditions"]["period_resolved"]
        span_text = f"{span['from']}~{span['to']}" if span else "기간 없음"
        print(f"{a['query_id']} {a['count']:>3}건  {span_text:23} {a['question']}")


if __name__ == "__main__":
    main()
