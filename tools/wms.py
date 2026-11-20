"""push_to_wms (에이전트 도구 아님). 담당: 서버. 규칙: .kiro/steering/agent-design.md 8번, 형식: docs/schema.md

에이전트 도구 목록에 넣지 않는다. 외부 시스템에 쓰는 일은 코드만 한다.
작업: e2e-plan.md D1·D2·D3 (P1), D4 ERP용 CSV (P2). 실제 WMS로 바꿀 때는 WmsAdapter 구현만 바꾼다.
"""

import csv
import io
import os
import time
import uuid
from collections.abc import Iterable
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


# ERP용 CSV 칸 (D4). 한 줄 = 품목 한 행. 앞 넷은 건(WmsRecord) 칸, 나머지는 ITEM_KEYS. bl_no + job_id + line은 겹치지 않는다.
ERP_CSV_COLUMNS = ("bl_no", "job_id", "consignee", "by", *ITEM_KEYS)
# 엑셀 같은 스프레드시트가 수식으로 읽는 첫 글자 (OWASP CSV Injection). 서류에서 읽은 글자는 데이터로만 다룬다.
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def export_erp_csv(records: Iterable[WmsRecord]) -> str:
    """ERP에 넘길 CSV 글자를 만든다. WMS에 올린 것과 같은 검증 데이터(WmsRecord)로 만든다 (agent-design.md 8번).

    언제: 가상 WMS에 등록한 건을 ERP로 넘길 때. 모델은 쓰지 않는다.
    받는 것: records(WmsRecord 목록. make_record로 만들어 push_to_wms에 넘긴 기록 그대로).
    반환: 머리줄이 ERP_CSV_COLUMNS인 CSV 글자(RFC 4180, 줄 끝 CRLF). 품목 한 행이 한 줄이고 빈 값은 빈칸이다.
      hs_code는 기록에 든 확정 HS뿐이다. 품목이 없는 건도 건 칸만 채운 한 줄로 남긴다.
      같은 멱등 키가 또 오면 처음 것만 쓴다 (WMS처럼 같은 건이 두 번 들어가지 않게).
      글자 칸이 = + - @ 로 시작하면 앞에 '를 붙인다 (스프레드시트에서 수식으로 실행되지 않게). 숫자 칸은 그대로다.
      파일로 저장할 때는 utf-8-sig로 써야 엑셀에서 한글이 깨지지 않는다.
    """
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=ERP_CSV_COLUMNS)
    writer.writeheader()
    seen: set[str] = set()
    lines = 0
    for record in records:
        if record.idempotency_key in seen:
            continue
        seen.add(record.idempotency_key)
        head = {"bl_no": record.bl_no, "job_id": record.job_id, "consignee": record.consignee, "by": record.by}
        for item in record.items or [{}]:
            row = head | {key: item.get(key) for key in ITEM_KEYS}
            writer.writerow({key: _csv_cell(value) for key, value in row.items()})
            lines += 1
    print(f"[wms] ERP CSV {len(seen)}건 {lines}줄")
    return out.getvalue()


def _csv_cell(value: str | int | float | None) -> str | int | float:
    """CSV 칸 하나. None은 빈칸, 수식으로 읽힐 글자는 앞에 '를 붙인다."""
    if value is None:
        return ""
    if isinstance(value, str) and value.startswith(_FORMULA_START):
        return "'" + value
    return value


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
    """자동 등록 조건(agent-design.md 8번)을 코드로 검사한다.

    언제: finish_report 직후, 그리고 사람이 HS를 고른 뒤. register_if_ready가 부른다.
    받는 것: result(문제 목록, 품목별 HS 결과).
    반환: 불일치·확인 필요가 하나도 없고(참고는 괜찮다) 모든 품목의 HS가 확정됐으면 True.
      HS 결과가 하나도 없으면 False (HS를 아직 안 돌렸으면 확정됐다고 볼 수 없다).
    """
    if any(issue.grade in ("불일치", "확인 필요") for issue in result.issues):
        return False
    if not result.hs:
        return False
    return all(r.status in _CONFIRMED and r.hs_code for r in result.hs)


def register_if_ready(
    job_id: str,
    docs: list[ExtractedDocument],
    result: JobResult,
    consignee: str,
    *,
    adapter: WmsAdapter | None = None,
) -> tuple[WmsState, str | None]:
    """자동 등록 조건을 다 채우면 사람 손 없이 바로 가상 WMS에 등록한다 (by=auto).

    언제: 처리 Lambda가 done으로 끝난 작업을 마지막으로 저장하기 직전(#154), 사람이 HS를 고른 뒤(POST /jobs/{id}/hs).
      둘 다 api/handler.auto_register를 거친다. HS 선택은 고른 HS를 먼저 저장하고 부른다. 같은 멱등 키는 처음 기록만 남아서,
      저장 전 HS로 등록하면 어긋난다. 처리 Lambda는 HS가 그 실행에서 처음 나와 다시 고를 일이 없어서 등록 뒤 한 번에 저장한다
      (화면이 승인 대기를 받으면 새로 고침을 멈추므로 중간 저장을 하지 않는다).
    받는 것: job_id, docs(읽은 서류), result(문제·HS·지금 WMS 상태), consignee(수하인 = 수입자),
      adapter(테스트용. 없으면 가상 WMS dynamo_wms()).
    반환: (WMS 상태, 못 한 이유).
      - 등록했으면 (WmsState(등록됨, auto, wms_id), None). 이미 등록된 건은 그 상태를 그대로 돌려준다.
      - 조건 미달(불일치·확인 필요·HS 대기)이면 (승인 대기, None). 정상 흐름이라 이유를 붙이지 않는다.
      - 조건은 채웠는데 못 했으면 (승인 대기, 이유): 서류 품목 행에 HS 결과가 없음, 기록을 못 만듦(B/L 번호·수하인 없음),
        가상 WMS 오류. 부르는 쪽이 이유를 단계 기록에 남겨 사람이 보게 한다.
      예외는 올리지 않는다. 앞 단계(HS 선택 저장 등)를 막지 않으려고서다. 사람이 승인하면 그때 다시 등록하고(D3),
      멱등 키라 두 번 들어가지 않는다.
    """
    if result.wms is not None and result.wms.status == "등록됨":
        return result.wms, None
    waiting = WmsState(status="승인 대기")
    if not can_auto_register(result):
        return waiting, None
    missing = _lines_without_hs(docs, result.hs)
    if missing:
        reason = f"{', '.join(f'{n}행' for n in missing)}은 HS 결과가 없습니다"
        print(f"[wms] 자동 등록 안 함 job={job_id}: {reason}")
        return waiting, reason
    try:
        record = make_record(job_id, docs, result.hs, consignee, "auto")
    except RecordNotReady as exc:
        print(f"[wms] 자동 등록 안 함 job={job_id}: {exc}")
        return waiting, str(exc)
    try:
        return push_to_wms(record, adapter=adapter if adapter is not None else dynamo_wms()), None
    except Exception as exc:  # 저장소 오류뿐 아니라 설정 오류(WMS_TABLE 없음 등)도 승인 대기로 돌린다
        print(f"[error] WMS 자동 등록 실패 job={job_id} {type(exc).__name__}: {exc}")
        return waiting, f"가상 WMS 오류({type(exc).__name__}). 승인하면 다시 등록합니다"


def _lines_without_hs(docs: list[ExtractedDocument], hs: list[HSResult]) -> list[int]:
    """서류에는 있는데 HS 결과가 없는 품목 행. 모든 품목에 HS가 있어야 자동 등록한다."""
    with_hs = {r.line for r in hs}
    lines = {item.line for doc in docs if doc.doc_type in ITEM_SOURCES for item in doc.items}
    return sorted(lines - with_hs)


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
    """사람 승인 전 검사 (agent-design.md 8번 예외).

    언제: POST /jobs/{id}/approve에서 make_record·push_to_wms를 부르기 전.
    받는 것: result(문제 목록), by(승인 경로. 지금은 human만 부른다).
    반환: 없음. 확인 필요·참고만 남았으면 통과한다 (사람이 보고 승인했으므로).
    실패: 불일치가 하나라도 남았으면 ApprovalRefused. 승인해도 등록하지 않고, 서류를 고쳐 다시 올려야 한다.
    """
    left = [i for i in result.issues if i.grade == "불일치"]
    if left:
        rules = ", ".join(dict.fromkeys(i.rule_id for i in left))
        raise ApprovalRefused(
            f"불일치 {len(left)}건({rules})이 남아 있어 WMS에 등록할 수 없습니다. 서류를 고쳐 다시 올려 주세요"
        )
