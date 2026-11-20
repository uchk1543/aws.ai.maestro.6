"""화물 기록 쓰기(E3) 단위 테스트. 저장소는 메모리·가짜 DynamoDB 테이블 (AWS 호출 없음)."""

from datetime import date

import pytest
from botocore.exceptions import ClientError

from tools.models import Cell, ChatFilters, ExtractedDocument, Shipment
from tools.query import DynamoShipments, SeedRowExists, query_shipments
from tools.report import mark_registered, record_shipment, shipment_row

TODAY = date(2026, 11, 20)


class MemoryWriter:
    """ShipmentWriter·ShipmentStore 메모리 구현. DynamoShipments처럼 미리 넣은 기록(job_id 없음)은 덮어쓰지 않는다."""

    def __init__(self, rows=()):
        self.rows = {r.bl_no: r for r in rows}
        self.puts = 0

    def all(self):
        return list(self.rows.values())

    def get(self, bl_no):
        return self.rows.get(bl_no)

    def put(self, row):
        old = self.rows.get(row.bl_no)
        if old is not None and old.job_id is None:
            raise SeedRowExists(row.bl_no)
        self.puts += 1
        self.rows[row.bl_no] = row


def c(raw):
    return Cell(raw=raw, value=raw)


def docs(bl_no="SMLNSGN26012216", inv_consignee="SAMPLE TRADING KOREA CO., LTD.", bl_consignee="TO ORDER OF SHIPPER",
         names=("WOODEN DINING CHAIR", "WOODEN DINING TABLE")):
    inv = ExtractedDocument.model_validate({
        "doc_type": "commercial_invoice", "file": "uploads/s/inv.pdf",
        "consignee_name": c(inv_consignee).model_dump() if inv_consignee else None,
        "items": [{"line": i + 1, "name": c(n).model_dump()} for i, n in enumerate(names)],
    })
    bl = ExtractedDocument.model_validate({
        "doc_type": "bill_of_lading", "file": "uploads/s/bl.pdf",
        "doc_no": c(bl_no).model_dump() if bl_no else None,
        "consignee_name": c(bl_consignee).model_dump() if bl_consignee else None,
    })
    return [inv, bl]


def seed(bl_no, status="반출", job_id=None):
    return Shipment(bl_no=bl_no, consignee="샘플트레이딩코리아", item="운동화", arrived_at=date(2026, 11, 1),
                    customs_status=status, last_event_at=date(2026, 11, 2), job_id=job_id)


def test_finished_job_writes_one_row_that_query_finds():
    store = MemoryWriter([seed("EXSHSZX26003555")])
    step = record_shipment("job-1", docs(), store, today=TODAY)
    row = store.get("SMLNSGN26012216")
    assert step.ok and step.tool == "record_shipment" and "입항" in step.summary
    assert (row.consignee, row.item) == ("SAMPLE TRADING KOREA CO., LTD.", "WOODEN DINING CHAIR 외 1개 품목")
    assert (row.arrived_at, row.customs_status, row.last_event_at, row.job_id) == (TODAY, "입항", TODAY, "job-1")
    # 끝난 기준: 처리한 건이 현황 조회에 나온다
    found = query_shipments(ChatFilters(period="today"), store=store, today=TODAY)
    assert [r.bl_no for r in found.rows] == ["SMLNSGN26012216"] and found.count == 1


def test_without_bill_of_lading_number_nothing_is_written():
    store = MemoryWriter()
    step = record_shipment("job-1", docs(bl_no=None), store, today=TODAY)
    assert step.ok and "B/L 번호가 없어" in step.summary and store.rows == {}
    step = record_shipment("job-1", docs()[:1], store, today=TODAY)  # 선하증권을 올리지 않음
    assert step.ok and store.rows == {}


def test_consignee_falls_back_to_bill_of_lading_and_is_needed():
    row, _ = shipment_row("job-1", docs(inv_consignee=None), TODAY)
    assert row.consignee == "TO ORDER OF SHIPPER"
    store = MemoryWriter()
    step = record_shipment("job-1", docs(inv_consignee=None, bl_consignee=None), store, today=TODAY)
    assert step.ok and "수하인" in step.summary and store.rows == {}


def test_seed_row_with_same_bill_of_lading_is_never_overwritten():
    store = MemoryWriter([seed("SMLNSGN26012216")])
    step = record_shipment("job-1", docs(), store, today=TODAY)
    assert step.ok and "미리 넣은" in step.summary
    assert store.get("SMLNSGN26012216").job_id is None and store.puts == 0


def test_reprocessing_same_bill_of_lading_keeps_arrival_and_progress():
    store = MemoryWriter([seed("SMLNSGN26012216", status="심사 중", job_id="job-old")])
    record_shipment("job-new", docs(), store, today=TODAY)
    row = store.get("SMLNSGN26012216")
    assert (row.job_id, row.arrived_at, row.customs_status, row.last_event_at) == ("job-new", date(2026, 11, 1), "심사 중", TODAY)


def test_auto_registered_job_starts_at_import_declaration():
    store = MemoryWriter()
    record_shipment("job-1", docs(), store, registered=True, today=TODAY)
    assert store.get("SMLNSGN26012216").customs_status == "수입신고"


def test_registration_moves_only_this_jobs_row_forward():
    later = date(2026, 11, 21)
    store = MemoryWriter([seed("SEED0001"), seed("OTHER0001", status="입항", job_id="job-other"),
                          seed("DONE0001", status="수리", job_id="job-1")])
    record_shipment("job-1", docs(), store, today=TODAY)
    step = mark_registered("job-1", "SMLNSGN26012216", store, today=later)
    row = store.get("SMLNSGN26012216")
    assert step.ok and step.summary.endswith("입항 → 수입신고")
    assert (row.customs_status, row.last_event_at) == ("수입신고", later)
    assert mark_registered("job-1", "SEED0001", store, today=later).ok  # 미리 넣은 기록은 그대로
    assert store.get("SEED0001").customs_status == "반출"
    mark_registered("job-1", "OTHER0001", store, today=later)  # 다른 작업의 기록은 그대로
    assert store.get("OTHER0001").customs_status == "입항"
    mark_registered("job-1", "DONE0001", store, today=later)  # 이미 수리면 뒤로 돌리지 않는다
    assert store.get("DONE0001").customs_status == "수리"
    assert "없어" in mark_registered("job-1", "NONE0001", store, today=later).summary


def test_store_errors_do_not_raise():
    class Broken(MemoryWriter):
        def get(self, bl_no):
            raise RuntimeError("DynamoDB 오류")

    assert not record_shipment("job-1", docs(), Broken(), today=TODAY).ok
    assert not mark_registered("job-1", "SMLNSGN26012216", Broken(), today=TODAY).ok


class FakeTable:
    def __init__(self, fail_code=None):
        self.calls, self.fail_code = [], fail_code

    def put_item(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail_code:
            raise ClientError({"Error": {"Code": self.fail_code, "Message": "x"}}, "PutItem")

    def get_item(self, Key):
        return {"Item": {**seed(Key["bl_no"]).model_dump(mode="json", exclude_none=True)}}


def test_dynamo_put_is_conditional_and_omits_empty_job_id():
    table = FakeTable()
    DynamoShipments(table).put(seed("BL-1", job_id="job-1"))
    [call] = table.calls
    assert call["Item"]["arrived_at"] == "2026-11-01" and call["Item"]["job_id"] == "job-1"
    assert call["ConditionExpression"] == "attribute_not_exists(bl_no) OR attribute_exists(job_id)"
    table = FakeTable()
    DynamoShipments(table).put(seed("BL-2"))
    assert "job_id" not in table.calls[0]["Item"]  # 시드와 같은 모양 (job_id가 없으면 칸 없음)
    assert DynamoShipments(table).get("BL-3").job_id is None


def test_dynamo_condition_failure_is_seed_row_and_other_errors_raise():
    with pytest.raises(SeedRowExists):
        DynamoShipments(FakeTable("ConditionalCheckFailedException")).put(seed("BL-1", job_id="job-1"))
    with pytest.raises(ClientError):
        DynamoShipments(FakeTable("ProvisionedThroughputExceededException")).put(seed("BL-1", job_id="job-1"))
