"""단위 테스트용 메모리 구현. AWS 없이 각자 자기 도구를 테스트할 때 쓴다.

실제 구현(DynamoDB 등)은 4번 서버 담당이 api/ 에 같은 모양으로 만든다 (테이블 생성은 PM).
"""

from tools.models import Shipment, WmsRecord


class MemoryHSHistory:
    """tools.hs.HSHistory 메모리 구현."""

    def __init__(self):
        self.rows: dict[tuple[str, str], tuple[str, str]] = {}

    def get(self, importer: str, item_key: str) -> str | None:
        row = self.rows.get((importer, item_key))
        return row[0] if row else None

    def put(self, importer: str, item_key: str, hs: str, job_id: str) -> None:
        self.rows[(importer, item_key)] = (hs, job_id)


class MemoryShipments:
    """tools.query.ShipmentStore 메모리 구현."""

    def __init__(self, rows: list[Shipment] | None = None):
        self.rows = list(rows or [])

    def all(self) -> list[Shipment]:
        return list(self.rows)


class MemoryWms:
    """tools.wms.WmsAdapter 메모리 구현. 같은 멱등 키는 한 번만 등록한다."""

    def __init__(self):
        self.records: dict[str, tuple[str, WmsRecord]] = {}

    def register(self, record: WmsRecord) -> str:
        if record.idempotency_key not in self.records:
            self.records[record.idempotency_key] = (f"wms-{len(self.records) + 1:04d}", record)
        return self.records[record.idempotency_key][0]

    def registered_jobs(self, bl_no: str) -> dict[str, str]:
        return {r.job_id: wms_id for wms_id, r in self.records.values() if r.bl_no == bl_no}


class MemoryChatTable:
    """team06-chat(boto3 Table)의 메모리판 (E6 #157). put_item·query만. 키: session_id(파티션) + ts(정렬).

    put_item은 값을 boto3 resource와 같은 규칙으로 바꿔 둔다 (int → Decimal, float·date는 TypeError, None → NULL).
    query는 KeyConditionExpression=Key("session_id").eq(…)만 받고, ScanIndexForward·Limit를 DynamoDB처럼 따른다.
    fail_put(Item)이 참이면 put_item이, fail_query가 참이면 query가 ClientError를 낸다.
    queries에 받은 조회를 {"session_id", "ScanIndexForward", "Limit"}로 남긴다.
    """

    def __init__(self, *, fail_put=None, fail_query: bool = False):
        self.items: dict[tuple[str, str], dict] = {}
        self.queries: list[dict] = []
        self.fail_put, self.fail_query = fail_put, fail_query

    def put_item(self, *, Item: dict) -> dict:
        if self.fail_put and self.fail_put(Item):
            raise _client_error("PutItem")
        self.items[(Item["session_id"], Item["ts"])] = _as_dynamo(Item)  # 같은 키면 덮어쓴다 (DynamoDB와 같다)
        return {}

    def query(self, *, KeyConditionExpression, ScanIndexForward: bool = True, Limit: int | None = None) -> dict:
        expr = KeyConditionExpression.get_expression()
        key, session_id = expr["values"]
        assert expr["operator"] == "=" and key.name == "session_id", "session_id = :id 조건만 받는다"
        self.queries.append({"session_id": session_id, "ScanIndexForward": ScanIndexForward, "Limit": Limit})
        if self.fail_query:
            raise _client_error("Query")
        rows = sorted((i for (s, _), i in self.items.items() if s == session_id), key=lambda i: i["ts"],
                      reverse=not ScanIndexForward)
        page = rows[:Limit] if Limit is not None else rows
        out = {"Items": [dict(i) for i in page], "Count": len(page)}
        if len(page) < len(rows):
            out["LastEvaluatedKey"] = {"session_id": session_id, "ts": page[-1]["ts"]}
        return out


def _as_dynamo(item: dict) -> dict:
    """boto3 resource가 DynamoDB에 쓰고 다시 읽을 때와 같은 값으로 바꾼다."""
    from boto3.dynamodb.types import TypeDeserializer, TypeSerializer

    ser, de = TypeSerializer(), TypeDeserializer()
    return {name: de.deserialize(ser.serialize(value)) for name, value in item.items()}


def _client_error(operation: str):
    from botocore.exceptions import ClientError

    return ClientError({"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "가짜 실패"}}, operation)
