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
