"""tools/wms.py ERP용 CSV 내보내기(D4) 단위 테스트. AWS 호출 없음."""

import csv
import io

from tools import wms
from tools.models import Cell, ExtractedDocument, ExtractedItem, HSResult, WmsRecord

JOB = "job-0000d004"
BL = "BL-2026-0004"
IMPORTER = "샘플무역"


def read_rows(text: str) -> tuple[list[str], list[dict]]:
    reader = csv.DictReader(io.StringIO(text, newline=""))
    return list(reader.fieldnames or []), list(reader)


def plain_record(job_id: str = JOB, items: list[dict] | None = None, consignee: str = IMPORTER) -> WmsRecord:
    return WmsRecord(
        idempotency_key=wms.idempotency_key(BL, job_id),
        bl_no=BL,
        job_id=job_id,
        consignee=consignee,
        items=items or [],
        by="human",
    )


def made_record() -> WmsRecord:
    """make_record로 만든 기록. 2행 품명에 쉼표가 있고, 2행 HS는 아직 사람 확인 필요다."""
    bl = ExtractedDocument(doc_type="bill_of_lading", file="uploads/s4/bl.pdf", doc_no=Cell(raw=BL, value=BL))
    pl = ExtractedDocument(
        doc_type="packing_list",
        file="uploads/s4/packing_list.pdf",
        items=[
            ExtractedItem(
                line=1,
                item_code=Cell(raw="BP-200", value="BP-200"),
                name=Cell(raw="LITHIUM-ION BATTERY PACK"),
                qty=Cell(raw="500 CTNS", value=500, unit="CTN"),
                gross_kg=Cell(raw="6,520.00 KGS", value=6520.0),
                net_kg=Cell(raw="6,100.00 KGS", value=6100.0),
            ),
            ExtractedItem(
                line=2,
                name=Cell(raw="BICYCLE TYRE 700X23C, NEW"),
                qty=Cell(raw="2,650 PCS", value=2650, unit="EA"),
            ),
        ],
    )
    hs = [
        HSResult(line=1, status="자동 확정", by="history", hs_code="8507600000"),
        HSResult(line=2, status="사람 확인 필요"),
    ]
    return wms.make_record(JOB, [bl, pl], hs, IMPORTER, "auto")


def test_export_erp_csv_one_line_per_item_from_wms_record():
    header, rows = read_rows(wms.export_erp_csv([made_record()]))
    assert header == list(wms.ERP_CSV_COLUMNS)
    assert rows == [
        {"bl_no": BL, "job_id": JOB, "consignee": IMPORTER, "by": "auto", "line": "1", "item_code": "BP-200",
         "name": "LITHIUM-ION BATTERY PACK", "qty": "500", "qty_unit": "CTN", "gross_kg": "6520.0",
         "net_kg": "6100.0", "hs_code": "8507600000"},
        # 확정 전 HS와 없는 칸은 빈칸. 쉼표가 든 품명도 한 칸으로 돌아온다
        {"bl_no": BL, "job_id": JOB, "consignee": IMPORTER, "by": "auto", "line": "2", "item_code": "",
         "name": "BICYCLE TYRE 700X23C, NEW", "qty": "2650", "qty_unit": "EA", "gross_kg": "",
         "net_kg": "", "hs_code": ""},
    ]


def test_export_erp_csv_same_key_once_and_keeps_order():
    first = plain_record(items=[{"line": 1, "name": "CHARGER"}])
    retry = first.model_copy(update={"items": [{"line": 1, "name": "CHANGED"}]})  # 같은 멱등 키
    other = plain_record(job_id="job-0000d005", items=[{"line": 1, "name": "CABLE"}])
    _, rows = read_rows(wms.export_erp_csv([first, retry, other]))
    assert [(r["job_id"], r["name"]) for r in rows] == [(JOB, "CHARGER"), ("job-0000d005", "CABLE")]


def test_export_erp_csv_record_without_items_keeps_one_line():
    _, rows = read_rows(wms.export_erp_csv([plain_record(items=[])]))
    assert rows == [dict.fromkeys(wms.ERP_CSV_COLUMNS, "") | {"bl_no": BL, "job_id": JOB, "consignee": IMPORTER, "by": "human"}]


def test_export_erp_csv_missing_item_keys_are_blank():
    _, [row] = read_rows(wms.export_erp_csv([plain_record(items=[{"line": 3, "qty": 10}])]))
    assert (row["line"], row["qty"], row["name"], row["hs_code"]) == ("3", "10", "", "")


def test_export_erp_csv_text_that_looks_like_formula_is_escaped():
    items = [{"line": 1, "item_code": "+82-10", "name": '=HYPERLINK("http://x","y")', "qty": -1, "qty_unit": "@EA"}]
    _, [row] = read_rows(wms.export_erp_csv([plain_record(items=items, consignee="-샘플무역")]))
    assert (row["item_code"], row["name"], row["qty_unit"]) == ("'+82-10", "'=HYPERLINK(\"http://x\",\"y\")", "'@EA")
    assert row["consignee"] == "'-샘플무역"
    assert row["qty"] == "-1"  # 숫자 칸은 그대로
    assert row["bl_no"] == BL  # 가운데 '-'는 손대지 않는다


def test_export_erp_csv_empty_is_header_only_crlf():
    assert wms.export_erp_csv([]) == ",".join(wms.ERP_CSV_COLUMNS) + "\r\n"
