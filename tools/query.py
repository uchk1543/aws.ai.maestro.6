"""query_shipments. 담당: 판독. 규칙: .kiro/steering/agent-design.md 9번, 형식: docs/schema.md

작업: e2e-plan.md E4 (P1). 모델은 질문을 조건(ChatFilters)으로 바꾸기만 하고, 기간 계산·조회·건수·정렬은 여기서 코드가 한다.
통관 지연 기준은 검증 담당이 docs/schema.md에 정한다 (E1, #29·#114). 데이터셋 생성기(samples/make_extra.py)와 같은 값이다.
"""

import os
from datetime import date, timedelta
from functools import cache
from typing import Protocol

from tools.models import ChatFilters, PeriodResolved, QueryResult, Shipment

# 통관 지연: (오늘 − 입항일) ≥ DELAY_DAYS일이고 수리·반출이 아님. 입항일 당일이 0일 (E1, #29 · docs/schema.md)
DELAY_STATUS = "통관 지연"
DELAY_DAYS = 3
CLEARED = ("수리", "반출")
DELAY_RULE = f"입항 후 {DELAY_DAYS}일 지나도 수리·반출 아님"


class ShipmentStore(Protocol):
    """화물 기록(team06-shipments). 구현: api/ (DynamoDB), 테스트: 메모리 목록."""

    def all(self) -> list[Shipment]: ...


class DynamoShipments:
    """ShipmentStore의 DynamoDB판 (team06-shipments, 키 bl_no). 칸 약속은 infra/README.md "테이블".

    날짜는 YYYY-MM-DD 문자열, job_id가 없으면 칸 없음 (infra/seed_shipments.py와 같은 모양).
    all()은 Scan을 끝까지 넘겨 읽는다. 화물 기록은 100건 안팎이라 Scan으로 충분하다.
    """

    def __init__(self, table):
        self.table = table

    def all(self) -> list[Shipment]:
        items, kwargs = [], {}
        while True:
            page = self.table.scan(**kwargs)
            items += page.get("Items", [])
            if "LastEvaluatedKey" not in page:
                break
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
        return [Shipment.model_validate(item) for item in items]


@cache
def dynamo_shipments() -> DynamoShipments:
    """Lambda에서 쓰는 화물 기록. 테이블은 환경 변수 SHIPMENTS_TABLE(team06-shipments). 타임아웃 5초, 재시도 1회."""
    import boto3
    from botocore.config import Config

    config = Config(connect_timeout=5, read_timeout=5, retries={"max_attempts": 2})
    return DynamoShipments(boto3.resource("dynamodb", config=config).Table(os.environ["SHIPMENTS_TABLE"]))


def resolve_period(filters: ChatFilters, today: date) -> PeriodResolved | None:
    """기간 조건을 한국 시간 기준 날짜 범위로 바꾼다. 모델이 날짜를 계산하지 않는다.

    받는 것: filters(period, range면 date_from·date_to), today(한국 시간 오늘. agent.today_kst()).
    반환: PeriodResolved(양 끝 포함). 주는 월요일~일요일. 기간 조건이 없으면 None.
      range에서 한쪽 날짜만 있으면 그날 하루, 앞뒤가 바뀌었으면 바로잡는다. 둘 다 없으면 None.
    """
    period = filters.period
    if period is None:
        return None
    if period == "today":
        start = end = today
    elif period in ("this_week", "last_week"):
        start = today - timedelta(days=today.weekday())
        if period == "last_week":
            start -= timedelta(days=7)
        end = start + timedelta(days=6)
    else:  # range
        start, end = filters.date_from or filters.date_to, filters.date_to or filters.date_from
        if start is None or end is None:
            return None
        start, end = min(start, end), max(start, end)
    return PeriodResolved.model_validate({"from": start, "to": end})


def is_delayed(row: Shipment, today: date) -> bool:
    """통관 지연인지. 입항일 당일이 0일이고, DELAY_DAYS일째부터 수리·반출이 아니면 지연 (11/17 입항 → 11/20부터)."""
    return (today - row.arrived_at).days >= DELAY_DAYS and row.customs_status not in CLEARED


def _same_status(a: str, b: str) -> bool:
    """'검사중'과 '검사 중'처럼 띄어쓰기만 다른 상태는 같게 본다."""
    return "".join(a.split()) == "".join(b.split())


def query_shipments(filters: ChatFilters, *, store: ShipmentStore, today: date) -> QueryResult:
    """조회 조건으로 화물 기록을 찾고 센다. 조회·집계·정렬은 코드가 한다.

    언제: 현황 조회 Agent가 질문을 조건으로 바꾼 뒤.
    받는 것: filters, store, today(한국 시간).
    반환: QueryResult. 기간은 입항일 기준(양 끝 포함), 상태가 '통관 지연'이면 지연 규칙으로 고른다.
      건수는 코드가 센 값, 쓴 상태 규칙 설명(rule)은 통관 지연일 때만. 정렬은 입항일, B/L 번호 순.
    """
    print(f"[tool] query_shipments filters={filters.model_dump(exclude_none=True, mode='json')} today={today}")
    period = resolve_period(filters, today)
    rows = store.all()
    if period is not None:
        rows = [r for r in rows if period.from_ <= r.arrived_at <= period.to]
    rule = None
    if filters.status and _same_status(filters.status, DELAY_STATUS):
        rows = [r for r in rows if is_delayed(r, today)]
        rule = DELAY_RULE
    elif filters.status:
        rows = [r for r in rows if _same_status(r.customs_status, filters.status)]
    rows = sorted(rows, key=lambda r: (r.arrived_at, r.bl_no))
    return QueryResult(filters=filters, period_resolved=period, rule=rule, rows=rows, count=len(rows))
