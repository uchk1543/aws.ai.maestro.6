"""tools/wms.py 가상 WMS(D1) 단위 테스트. DynamoDB는 가짜 테이블로 바꾼다 (AWS 호출 없음)."""

import pytest
from botocore.exceptions import ClientError

from tests.unit.fakes import MemoryWms
from tools import wms
from tools.models import Cell, ExtractedDocument, ExtractedItem, HSResult, WmsRecord, WmsState

JOB = "job-0000d001"
BL = "BL-2026-0001"
IMPORTER = "샘플무역"


def bl_doc(raw: str | None = BL) -> ExtractedDocument:
    doc_no = Cell(raw=raw, value=raw.strip()) if raw else Cell(unreadable="흐림")
    return ExtractedDocument(doc_type="bill_of_lading", file="uploads/s1/bl.pdf", doc_no=doc_no)


def item(line: int, **cells: dict) -> ExtractedItem:
    return ExtractedItem(line=line, **{name: Cell(**cell) for name, cell in cells.items()})


def sample_docs() -> list[ExtractedDocument]:
    """1행은 포장명세서와 상업송장에 함께, 2행은 상업송장에만 있다. 포장명세서 1행 순중량은 흐려서 못 읽었다."""
    pl = ExtractedDocument(
        doc_type="packing_list",
        file="uploads/s1/packing_list.pdf",
        items=[
            item(
                1,
                item_code={"raw": "BP-200", "value": "BP-200"},
                name={"raw": "LITHIUM-ION  BATTERY PACK", "value": "lithium-ion battery pack"},
                qty={"raw": "500 CTNS", "value": 500, "unit": "CTN"},
                gross_kg={"raw": "6,520.00 KGS", "value": 6520.0},
                net_kg={"unreadable": "흐림"},
            )
        ],
    )
    ci = ExtractedDocument(
        doc_type="commercial_invoice",
        file="uploads/s1/invoice.pdf",
        items=[
            item(
                1,
                name={"raw": "LITHIUM-ION BATTERY PACK", "value": "lithium-ion battery pack"},
                qty={"raw": "2,650 PCS", "value": 2650, "unit": "EA"},
                net_kg={"raw": "6,100.00 KGS", "value": 6100.0},
            ),
            item(2, name={"raw": "CHARGER", "value": "charger"}, qty={"raw": "10 PCS", "value": 10, "unit": "EA"}),
        ],
    )
    return [ci, pl, bl_doc()]


HS = [
    HSResult(line=1, status="사람 확정", by="human", hs_code="8507600000"),
    HSResult(line=2, status="사람 확인 필요"),
]


def record(by="auto", job_id=JOB) -> WmsRecord:
    return wms.make_record(job_id, sample_docs(), HS, IMPORTER, by)


def test_idempotency_key_is_bl_and_job():
    assert wms.idempotency_key(BL, JOB) == "BL-2026-0001#job-0000d001"


def test_make_record_takes_bl_items_and_confirmed_hs():
    rec = wms.make_record(JOB, sample_docs(), HS, f"  {IMPORTER} ", "auto")
    assert (rec.idempotency_key, rec.bl_no, rec.job_id) == (f"{BL}#{JOB}", BL, JOB)
    assert (rec.consignee, rec.by) == (IMPORTER, "auto")
    # 포장명세서 값을 먼저 쓰고, 못 읽은 순중량만 상업송장에서 채운다. 확정 전 HS는 넣지 않는다
    assert rec.items == [
        {"line": 1, "item_code": "BP-200", "name": "LITHIUM-ION BATTERY PACK", "qty": 500, "qty_unit": "CTN",
         "gross_kg": 6520.0, "net_kg": 6100.0, "hs_code": "8507600000"},
        {"line": 2, "item_code": None, "name": "CHARGER", "qty": 10, "qty_unit": "EA",
         "gross_kg": None, "net_kg": None, "hs_code": None},
    ]
    assert all(tuple(row) == wms.ITEM_KEYS for row in rec.items)


def test_make_record_same_bl_twice_is_fine():
    docs = sample_docs() + [bl_doc(f" {BL} ")]
    assert wms.make_record(JOB, docs, HS, IMPORTER, "human").bl_no == BL


@pytest.mark.parametrize(
    "docs",
    [
        [d for d in sample_docs() if d.doc_type != "bill_of_lading"],  # 선하증권 없음
        [d for d in sample_docs() if d.doc_type != "bill_of_lading"] + [bl_doc(None)],  # B/L No. 못 읽음
        sample_docs() + [bl_doc("BL-2026-0002")],  # B/L이 둘
    ],
    ids=["no-bl", "bl-unreadable", "two-bls"],
)
def test_make_record_needs_exactly_one_bl(docs):
    with pytest.raises(wms.RecordNotReady, match="B/L"):
        wms.make_record(JOB, docs, HS, IMPORTER, "auto")


@pytest.mark.parametrize("consignee", ["", "   "])
def test_make_record_needs_consignee(consignee):
    with pytest.raises(wms.RecordNotReady, match="수하인"):
        wms.make_record(JOB, sample_docs(), HS, consignee, "auto")


def test_push_to_wms_registers_once():
    memory = MemoryWms()
    first = wms.push_to_wms(record(), adapter=memory)
    again = wms.push_to_wms(record(), adapter=memory)  # 재시도
    assert first == again == WmsState(status="등록됨", by="auto", wms_id="wms-0001")
    assert list(memory.records) == [f"{BL}#{JOB}"]


def test_push_to_wms_keeps_by():
    state = wms.push_to_wms(record(by="human"), adapter=MemoryWms())
    assert (state.status, state.by) == ("등록됨", "human")


def test_push_to_wms_rejects_key_that_is_not_bl_and_job():
    memory = MemoryWms()
    bad = record().model_copy(update={"idempotency_key": JOB})
    with pytest.raises(ValueError, match="멱등 키"):
        wms.push_to_wms(bad, adapter=memory)
    assert memory.records == {}


# ---------------------------------------------------------------------------
# DynamoWms (team06-wms)
# ---------------------------------------------------------------------------
class FakeWmsTable:
    """team06-wms 흉내. 조건 attribute_not_exists(idempotency_key)만 안다."""

    def __init__(self, fail_code: str | None = None):
        self.items: dict[str, dict] = {}
        self.fail_code = fail_code
        self.reads: list[bool] = []

    def put_item(self, Item, ConditionExpression=None):
        if self.fail_code:
            raise ClientError({"Error": {"Code": self.fail_code, "Message": "가짜 오류"}}, "PutItem")
        key = Item["idempotency_key"]
        if ConditionExpression == "attribute_not_exists(idempotency_key)" and key in self.items:
            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException", "Message": "이미 있음"}}, "PutItem")
        self.items[key] = Item

    def get_item(self, Key, ConsistentRead=False):
        self.reads.append(ConsistentRead)
        item = self.items.get(Key["idempotency_key"])
        return {"Item": item} if item else {}


def test_dynamo_wms_writes_one_item_per_key():
    table = FakeWmsTable()
    store = wms.DynamoWms(table)
    first = store.register(record())
    again = store.register(record(by="human"))  # 같은 키로 다시 와도 덮어쓰지 않는다
    assert first.startswith("wms-") and again == first
    [item] = table.items.values()
    assert item["idempotency_key"] == f"{BL}#{JOB}" and item["wms_id"] == first
    assert isinstance(item["registered_at"], int)
    assert WmsRecord.model_validate_json(item["record"]) == record()  # 처음 기록 그대로
    assert table.reads == [True]  # 이미 있을 때만, 강한 일관성으로 읽는다


def test_dynamo_wms_new_job_is_new_item():
    table = FakeWmsTable()
    store = wms.DynamoWms(table)
    assert store.register(record()) != store.register(record(job_id="job-0000d002"))
    assert sorted(table.items) == [f"{BL}#{JOB}", f"{BL}#job-0000d002"]


def test_dynamo_wms_other_errors_are_raised():
    store = wms.DynamoWms(FakeWmsTable(fail_code="ProvisionedThroughputExceededException"))
    with pytest.raises(ClientError):
        store.register(record())


def test_push_to_wms_with_dynamo_wms():
    table = FakeWmsTable()
    state = wms.push_to_wms(record(), adapter=wms.DynamoWms(table))
    assert state.status == "등록됨" and state.wms_id == table.items[f"{BL}#{JOB}"]["wms_id"]
