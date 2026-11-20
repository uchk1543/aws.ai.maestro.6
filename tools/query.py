"""query_shipments. 담당: 판독. 규칙: .kiro/steering/agent-design.md 9번, 형식: docs/schema.md

작업: e2e-plan.md E4 (P1). 모델은 질문을 조건(ChatFilters)으로 바꾸기만 하고, 기간 계산·조회·건수·정렬은 여기서 코드가 한다.
통관 지연 기준은 검증 담당이 docs/schema.md에 정한다 (E1, #29·#114). 데이터셋 생성기(samples/make_extra.py)와 같은 값이다.
#257: 현황 Agent의 도구가 쓰는 집계(count_shipments)와 그래프(make_chart)도 여기서 코드가 만든다. 모델은 기준·종류만 고른다.
"""

import os
from collections import Counter
from datetime import date, timedelta
from functools import cache
from typing import Protocol

from tools.models import (
    Chart,
    ChartPoint,
    ChartType,
    ChatFilters,
    CountResult,
    DocumentRecord,
    GroupBy,
    Job,
    JobSummary,
    PeriodResolved,
    QueryResult,
    Shipment,
)

# 통관 지연: (오늘 − 입항일) ≥ DELAY_DAYS일이고 수리·반출이 아님. 입항일 당일이 0일 (E1, #29 · docs/schema.md)
DELAY_STATUS = "통관 지연"
DELAY_DAYS = 3
CLEARED = ("수리", "반출")
DELAY_RULE = f"입항 후 {DELAY_DAYS}일 지나도 수리·반출 아님"


class ShipmentStore(Protocol):
    """화물 기록(team06-shipments). 구현: api/ (DynamoDB), 테스트: 메모리 목록."""

    def all(self) -> list[Shipment]: ...


class JobSource(Protocol):
    """작업·서류 읽기 (#257, team06-jobs). 현황 Agent의 get_job·find_jobs·list_documents가 쓴다. 읽기만 한다.

    구현: api/handler.py HandlerJobs (GET /jobs/{id}·GET /jobs·GET /documents와 같은 코드), 테스트: 메모리.
    """

    def job(self, job_id: str) -> Job | None: ...

    def jobs(self) -> list[JobSummary]: ...

    def documents(self) -> list[DocumentRecord]: ...


class SeedRowExists(Exception):
    """미리 넣은 가상 화물 기록(job_id 없음)이라 덮어쓰지 않았다 (E3)."""


class ShipmentWriter(Protocol):
    """화물 기록 쓰기 (E3, tools/report.record_shipment). 구현: DynamoShipments, 테스트: 메모리.

    put은 미리 넣은 기록(job_id 없음)을 덮어쓰지 않는다. 그런 줄이 있으면 SeedRowExists.
    """

    def get(self, bl_no: str) -> Shipment | None: ...

    def put(self, row: Shipment) -> None: ...


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

    def get(self, bl_no: str) -> Shipment | None:
        item = self.table.get_item(Key={"bl_no": bl_no}).get("Item")
        return Shipment.model_validate(item) if item else None

    def put(self, row: Shipment) -> None:
        """한 줄을 쓴다. 미리 넣은 기록(job_id 칸 없음)이 이미 있으면 쓰지 않고 SeedRowExists (조건부 쓰기라 동시에 써도 지킨다)."""
        from botocore.exceptions import ClientError

        item = row.model_dump(mode="json", exclude_none=True)  # job_id가 없으면 칸 없음 (시드와 같은 모양)
        try:
            self.table.put_item(
                Item=item, ConditionExpression="attribute_not_exists(bl_no) OR attribute_exists(job_id)"
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                raise SeedRowExists(row.bl_no) from exc
            raise


@cache
def dynamo_shipments() -> DynamoShipments:
    """Lambda에서 쓰는 화물 기록 (조회 all, 쓰기 get·put). 테이블은 환경 변수 SHIPMENTS_TABLE(team06-shipments). 타임아웃 5초, 재시도 1회."""
    import boto3
    from botocore.config import Config

    config = Config(connect_timeout=5, read_timeout=5, retries={"max_attempts": 2})
    return DynamoShipments(boto3.resource("dynamodb", config=config).Table(os.environ["SHIPMENTS_TABLE"]))


def resolve_period(filters: ChatFilters, today: date) -> PeriodResolved | None:
    """기간 조건을 한국 시간 기준 날짜 범위로 바꾼다. 모델이 날짜를 계산하지 않는다.

    받는 것: filters(period, range면 date_from·date_to), today(한국 시간 오늘. agent.today_kst()).
    반환: PeriodResolved(양 끝 포함). 주는 월요일~일요일, 달은 1일~말일. 기간 조건이 없으면 None.
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
    elif period in ("this_month", "last_month"):  # #257
        start = today.replace(day=1)
        if period == "last_month":
            start = (start - timedelta(days=1)).replace(day=1)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
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


def _squash(text: str) -> str:
    """띄어쓰기·대소문자를 무시하고 비교하려고 공백을 빼고 대문자로."""
    return "".join(text.split()).upper()


def _status_ok(row: Shipment, status: str, today: date) -> bool:
    """한 상태 조건에 맞는지. '통관 지연'은 지연 규칙, 그 밖은 상태 값."""
    if _same_status(status, DELAY_STATUS):
        return is_delayed(row, today)
    return _same_status(row.customs_status, status)


def select_rows(filters: ChatFilters, *, store: ShipmentStore, today: date) -> tuple[list[Shipment], PeriodResolved | None, str | None]:
    """조회 조건에 맞는 화물을 고른다 (query_shipments·count_shipments 공통).

    받는 것: filters(상태·기간, #257의 그중 상태·수입자·품명·B/L), store, today(한국 시간).
    반환: (입항일·B/L 순으로 정렬한 줄, 계산한 기간, 쓴 상태 규칙 설명). 규칙 설명은 두 상태 중 하나가 통관 지연일 때만.
      수입자·품명은 띄어쓰기·대소문자를 무시하고 포함하면, B/L은 같으면 맞음.
    """
    period = resolve_period(filters, today)
    rows = store.all()
    if period is not None:
        rows = [r for r in rows if period.from_ <= r.arrived_at <= period.to]
    statuses = [s for s in (filters.status, filters.and_status) if s]
    for status in statuses:
        rows = [r for r in rows if _status_ok(r, status, today)]
    if filters.consignee:
        rows = [r for r in rows if _squash(filters.consignee) in _squash(r.consignee)]
    if filters.item:
        rows = [r for r in rows if _squash(filters.item) in _squash(r.item)]
    if filters.bl_no:
        rows = [r for r in rows if _squash(filters.bl_no) == _squash(r.bl_no)]
    rule = DELAY_RULE if any(_same_status(s, DELAY_STATUS) for s in statuses) else None
    return sorted(rows, key=lambda r: (r.arrived_at, r.bl_no)), period, rule


def query_shipments(filters: ChatFilters, *, store: ShipmentStore, today: date) -> QueryResult:
    """조회 조건으로 화물 기록을 찾고 센다. 조회·집계·정렬은 코드가 한다.

    언제: 현황 조회 Agent가 질문을 조건으로 바꾼 뒤 (#257부터는 Agent가 도구로 부른다).
    받는 것: filters, store, today(한국 시간).
    반환: QueryResult. 기간은 입항일 기준(양 끝 포함), 상태가 '통관 지연'이면 지연 규칙으로 고른다.
      건수는 코드가 센 값, 쓴 상태 규칙 설명(rule)은 통관 지연일 때만. 정렬은 입항일, B/L 번호 순.
    """
    print(f"[tool] query_shipments filters={filters.model_dump(exclude_none=True, mode='json')} today={today}")
    rows, period, rule = select_rows(filters, store=store, today=today)
    return QueryResult(filters=filters, period_resolved=period, rule=rule, rows=rows, count=len(rows))


GROUP_LABELS: dict[str, str] = {
    "status": "통관 상태", "consignee": "수입자", "item": "품목", "day": "입항일", "week": "입항 주", "month": "입항 달",
}
FLOW_ORDER = ("입항", "수입신고", "심사 중", "검사 중", *CLEARED)  # 통관 상태 진행 순서 (docs/schema.md 화물 기록)


def _group_key(row: Shipment, group_by: GroupBy) -> tuple:
    """(정렬 값, 묶음 이름). 날짜 묶음은 날짜로, 상태는 진행 순서로 정렬한다."""
    d = row.arrived_at
    if group_by == "day":
        return d, f"{d.month}/{d.day}"
    if group_by == "week":
        start = d - timedelta(days=d.weekday())
        end = start + timedelta(days=6)
        return start, f"{start.month}/{start.day}~{end.month}/{end.day}"
    if group_by == "month":
        return d.replace(day=1), f"{d.year}-{d.month:02d}"
    if group_by == "status":
        known = next((i for i, s in enumerate(FLOW_ORDER) if _same_status(s, row.customs_status)), len(FLOW_ORDER))
        return known, row.customs_status
    name = row.consignee if group_by == "consignee" else row.item
    return name, name


def count_shipments(filters: ChatFilters, group_by: GroupBy, *, store: ShipmentStore, today: date) -> CountResult:
    """조회 조건으로 고른 화물을 group_by로 묶어 센다 (#257). 모델은 기준만 고르고 세는 것은 코드다.

    언제: 현황 Agent가 '수입자별', '주별', '상태별' 같은 질문을 받았을 때. 그래프(make_chart)의 재료다.
    받는 것: filters(query_shipments와 같음), group_by(status·consignee·item·day·week·month), store, today(한국 시간).
    반환: CountResult. 날짜 묶음(day·week·month, 입항일 기준, 주는 월~일)과 상태(진행 순서)는 그 순서로,
      수입자·품목은 많은 순(같으면 이름 순). total은 고른 화물 수 = 묶음 건수의 합.
    """
    print(f"[tool] count_shipments group_by={group_by} filters={filters.model_dump(exclude_none=True, mode='json')} today={today}")
    rows, period, rule = select_rows(filters, store=store, today=today)
    counts: Counter = Counter()
    order: dict[str, object] = {}
    for row in rows:
        key, label = _group_key(row, group_by)
        counts[label] += 1
        order[label] = key
    if group_by in ("consignee", "item"):
        labels = sorted(counts, key=lambda label: (-counts[label], label))
    else:
        labels = sorted(counts, key=lambda label: (order[label], label))
    groups = [ChartPoint(label=label, value=counts[label]) for label in labels]
    return CountResult(
        filters=filters, period_resolved=period, rule=rule, group_by=group_by, groups=groups, total=len(rows), rows=rows
    )


def make_chart(chart_type: ChartType, counted: CountResult, title: str) -> Chart:
    """집계 결과로 그래프를 만든다 (#257). 값·축은 코드가 집계에서 그대로 옮기고, 화면은 계산 없이 그린다.

    받는 것: chart_type(bar·line·pie, 모델이 고름), counted(count_shipments 결과), title(코드가 조건으로 만든 제목).
    반환: Chart. points는 counted.groups와 같은 값·같은 순서.
    """
    print(f"[tool] make_chart type={chart_type} group_by={counted.group_by} points={len(counted.groups)}")
    return Chart(
        type=chart_type, title=title, x_label=GROUP_LABELS[counted.group_by], y_label="건수",
        points=[p.model_copy() for p in counted.groups],
    )
