"""push_to_wms (에이전트 도구 아님). 담당: 서버. 규칙: .kiro/steering/agent-design.md 8번, 형식: docs/schema.md

에이전트 도구 목록에 넣지 않는다. 외부 시스템에 쓰는 일은 코드만 한다.
작업: e2e-plan.md D1·D2·D3 (P1). 실제 WMS로 바꿀 때는 WmsAdapter 구현만 바꾼다.
"""

import os
import time
import uuid
from functools import cache
from typing import Protocol

from botocore.exceptions import ClientError

from tools.models import Cell, ExtractedDocument, HSResult, JobResult, WmsBy, WmsRecord, WmsState


class WmsAdapter(Protocol):
    """WMS 하나. 가상 WMS(DynamoDB)든 실제 시스템이든 이 모양만 맞추면 된다."""

    def register(self, record: WmsRecord) -> str:
        """등록하고 wms_id를 돌려준다. 같은 idempotency_key면 이미 있는 wms_id를 돌려준다."""
        ...


class RecordNotReady(Exception):
    """WMS에 올릴 기록을 만들 수 없음: B/L 번호가 없거나 둘 이상, 또는 수하인이 비어 있음."""


# WmsRecord.items 한 행의 칸. ERP용 CSV(D4)도 이 칸을 쓴다.
ITEM_KEYS = ("line", "item_code", "name", "qty", "qty_unit", "gross_kg", "net_kg", "hs_code")
# 품목 칸을 가져올 서류 순서. 창고 입고는 포장명세서(포장 수·중량)가 기준이고, 비어 있는 칸만 다음 서류에서 채운다.
ITEM_SOURCES = ("packing_list", "commercial_invoice", "bill_of_lading", "certificate_of_origin")
_CONFIRMED = ("자동 확정", "사람 확정")


def idempotency_key(bl_no: str, job_id: str) -> str:
    """멱등 키 "<B/L 번호>#<작업 ID>" (infra/README.md의 team06-wms 키). 같은 키는 한 번만 등록된다."""
    return f"{bl_no}#{job_id}"


def make_record(
    job_id: str, docs: list[ExtractedDocument], hs: list[HSResult], consignee: str, by: WmsBy
) -> WmsRecord:
    """WMS에 올릴 한 건을 코드가 만든다. 모델은 쓰지 않는다.

    언제: 자동 등록(by=auto) 또는 사람 승인(by=human)으로 push_to_wms를 부르기 직전.
    받는 것: job_id, docs(읽은 서류), hs(품목별 HS 결과), consignee(수하인 = 수입자), by.
    반환: WmsRecord. bl_no는 선하증권의 doc_no(B/L No.), 멱등 키는 idempotency_key(bl_no, job_id).
      items는 행마다 ITEM_KEYS 칸. 칸마다 ITEM_SOURCES 순서로 처음 있는 값을 쓰고, hs_code는 확정된 HS만 넣는다.
    실패: B/L 번호가 없거나 둘 이상이면, 수하인이 비어 있으면 RecordNotReady.
    """
    bl_no = _bl_no(docs)
    if not consignee or not consignee.strip():
        raise RecordNotReady("수하인(수입자)이 비어 있어 WMS에 등록할 수 없습니다")
    return WmsRecord(
        idempotency_key=idempotency_key(bl_no, job_id),
        bl_no=bl_no,
        job_id=job_id,
        consignee=consignee.strip(),
        items=_items(docs, hs),
        by=by,
    )


def _bl_no(docs: list[ExtractedDocument]) -> str:
    """선하증권의 B/L No. 칸. 코드가 푼 value를 먼저 쓰고, 없으면 raw를 쓴다."""
    found: list[str] = []
    for doc in docs:
        if doc.doc_type != "bill_of_lading" or doc.doc_no is None:
            continue
        cell = doc.doc_no
        text = cell.value if isinstance(cell.value, str) and cell.value.strip() else cell.raw
        if text and text.strip() and text.strip() not in found:
            found.append(text.strip())
    if not found:
        raise RecordNotReady(
            "B/L 번호가 없어 WMS에 등록할 수 없습니다. 선하증권을 올렸는지, B/L No. 칸을 읽었는지 확인해 주세요"
        )
    if len(found) > 1:
        raise RecordNotReady(f"B/L 번호가 둘 이상입니다 ({', '.join(found)}). 한 건에는 B/L 하나만 올려 주세요")
    return found[0]


def _text(cell: Cell | None) -> str | None:
    """글자 칸: 서류에 적힌 그대로(raw)를 공백만 정리해 쓴다. raw가 없으면 value."""
    if cell is None:
        return None
    if cell.raw and cell.raw.strip():
        return " ".join(cell.raw.split())
    return str(cell.value) if cell.value not in (None, "") else None


def _items(docs: list[ExtractedDocument], hs: list[HSResult]) -> list[dict]:
    """행(line)마다 품명·수량·중량·확정 HS를 모은다."""
    rows: dict[int, dict] = {}
    sources = sorted((d for d in docs if d.doc_type in ITEM_SOURCES), key=lambda d: ITEM_SOURCES.index(d.doc_type))
    for doc in sources:
        for item in doc.items:
            row = rows.setdefault(item.line, dict.fromkeys(ITEM_KEYS) | {"line": item.line})
            if row["item_code"] is None:
                row["item_code"] = _text(item.item_code)
            if row["name"] is None:
                row["name"] = _text(item.name)
            if row["qty"] is None and item.qty is not None and item.qty.value is not None:
                row["qty"], row["qty_unit"] = item.qty.value, item.qty.unit
            if row["gross_kg"] is None and item.gross_kg is not None:
                row["gross_kg"] = item.gross_kg.value
            if row["net_kg"] is None and item.net_kg is not None:
                row["net_kg"] = item.net_kg.value
    confirmed = {r.line: r.hs_code for r in hs if r.status in _CONFIRMED and r.hs_code}
    for row in rows.values():
        row["hs_code"] = confirmed.get(row["line"])
    return [rows[line] for line in sorted(rows)]


class DynamoWms:
    """WmsAdapter의 가상 WMS판 (DynamoDB team06-wms). 칸 약속은 infra/README.md "테이블".

    키 idempotency_key("<B/L 번호>#<작업 ID>"), 칸 wms_id · record(WmsRecord JSON 문자열) · registered_at(초).
    같은 키는 조건부 쓰기(attribute_not_exists)로 한 번만 넣는다. 재시도·동시 요청이 와도 처음 준 wms_id를 돌려준다.
    """

    def __init__(self, table):
        self.table = table

    def register(self, record: WmsRecord) -> str:
        wms_id = f"wms-{uuid.uuid4().hex[:8]}"
        item = {
            "idempotency_key": record.idempotency_key,
            "wms_id": wms_id,
            "record": record.model_dump_json(),
            "registered_at": int(time.time()),
        }
        try:
            self.table.put_item(Item=item, ConditionExpression="attribute_not_exists(idempotency_key)")
            return wms_id
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
        existing = self.table.get_item(Key={"idempotency_key": record.idempotency_key}, ConsistentRead=True)["Item"]
        print(f"[wms] 이미 등록됨 key={record.idempotency_key} wms_id={existing['wms_id']}")
        return existing["wms_id"]


@cache
def dynamo_wms() -> DynamoWms:
    """Lambda에서 쓰는 가상 WMS. 테이블은 환경 변수 WMS_TABLE(team06-wms). 타임아웃 5초, 재시도 1회."""
    import boto3
    from botocore.config import Config

    config = Config(connect_timeout=5, read_timeout=5, retries={"max_attempts": 2})
    return DynamoWms(boto3.resource("dynamodb", config=config).Table(os.environ["WMS_TABLE"]))


class ApprovalRefused(Exception):
    """불일치가 남아 승인해도 등록하지 않음 (API는 409)."""


def can_auto_register(result: JobResult) -> bool:
    """자동 등록 조건: 불일치·확인 필요가 하나도 없고 모든 품목의 HS가 확정됨."""
    raise NotImplementedError("D2: 자동 등록 조건 (서버 담당)")


def push_to_wms(record: WmsRecord, *, adapter: WmsAdapter) -> WmsState:
    """가상 WMS에 한 건 등록한다.

    언제: finish_report 직후 can_auto_register가 참이면(by=auto), 또는 사람이 승인하면(by=human).
    받는 것: record(멱등 키 포함, make_record로 만든다), adapter(Lambda에서는 dynamo_wms()).
    반환: WmsState(status='등록됨', by, wms_id). 같은 멱등 키로 다시 부르면 처음 받은 wms_id가 그대로 온다.
    실패: 멱등 키가 "<B/L 번호>#<작업 ID>"가 아니면 ValueError (재시도해도 한 번만 들어가야 해서). 저장소 오류는 그대로 올린다.
    """
    print(f"[tool] push_to_wms key={record.idempotency_key} by={record.by}")
    expected = idempotency_key(record.bl_no, record.job_id)
    if record.idempotency_key != expected:
        raise ValueError(f"멱등 키가 B/L 번호 + 작업 ID와 다릅니다: {record.idempotency_key} (기대: {expected})")
    wms_id = adapter.register(record)
    return WmsState(status="등록됨", by=record.by, wms_id=wms_id)


def approve(result: JobResult, by: WmsBy = "human") -> None:
    """사람 승인 전 검사. 불일치가 남았으면 ApprovalRefused."""
    raise NotImplementedError("D3: 승인 검사 (서버 담당)")
