"""HS 확인 요청서 PDF (X2 #260). 담당: PM. AWS·Bedrock 호출 없음.
tools/hs_request.py 의 make_hs_request(내용·미확정 사유·발급 조건)와 GET /jobs/{id}/hs-request(상태 코드·이진 응답)를 본다.
"""
import base64
import io
from datetime import datetime, timezone

import pytest
from pypdf import PdfReader

import tools.hs_request as hs_request
from tests.unit.test_handler import (  # noqa: F401 (픽스처와 승인 시험 보조)
    APPROVE_JOB, BL, IMPORTER, call, fakes, lambda_client, ocr, put_approve_job, shipments, wms_fakes, wms_memory,
)
from tools.models import Cell, ExtractedDocument, ExtractedItem, HSCandidate, HSResult, Job, JobResult

JOB = "job-00000f01"
NOW = datetime(2026, 11, 21, 0, 30, tzinfo=timezone.utc)  # UTC 00:30 = 한국 시간 09:30


def cell(raw: str | None) -> Cell | None:
    return Cell(raw=raw, value=raw) if raw else None


def item(line: int, name: str | None, hs: str | None, qty="1,200 PCS", gw="6,250.00 KGS", nw="5,900.00 KGS") -> ExtractedItem:
    return ExtractedItem(line=line, name=cell(name), hs_code=cell(hs), qty=cell(qty), gross_kg=cell(gw), net_kg=cell(nw))


def docs(invoice_hs="9401.61", packing_hs="9401.69") -> list[ExtractedDocument]:
    return [
        ExtractedDocument(
            doc_type="commercial_invoice", file="uploads/s1/invoice.pdf", doc_no=cell("QDT/26/0289"),
            consignee_name=cell(IMPORTER), incoterms=cell("CIF BUSAN"), exporter_name=cell("QINGDAO TRADING CO."), origin=cell("CHINA"),
            items=[item(1, "WOODEN DINING CHAIR, OAK FRAME", invoice_hs)],
        ),
        ExtractedDocument(doc_type="packing_list", file="uploads/s1/pl.pdf", items=[item(1, "WOODEN DINING CHAIR", packing_hs)]),
        ExtractedDocument(doc_type="bill_of_lading", file="uploads/s1/bl.pdf", doc_no=cell(BL)),
    ]


def cands(*codes: str) -> list[HSCandidate]:
    return [HSCandidate(hs=c, name=f"{c} 품목명", reason=f"품명 칸 근거 {c}") for c in codes]


def pending(line=1, *, candidates=None, name="WOODEN DINING CHAIR, OAK FRAME", doc_hs="9401.61") -> HSResult:
    return HSResult(
        line=line, status="사람 확인 필요", item_name=name, doc_hs_code=doc_hs,
        candidates=cands("9401611000", "9401691000", "9403601000") if candidates is None else candidates,
    )


def job_of(*hs: HSResult) -> Job:
    return Job(job_id=JOB, status="waiting_approval", result=JobResult(hs=list(hs)))


def text_of(pdf: bytes) -> str:
    return "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf)).pages)


def flat(pdf: bytes) -> str:
    return "".join(text_of(pdf).split())


def make(job: Job, d=None, **kw) -> bytes:
    return hs_request.make_hs_request(job, docs() if d is None else d, importer=IMPORTER, now=NOW, **kw)


def test_request_has_ids_item_values_candidates_and_requests():
    text = flat(make(job_of(pending())))
    for want in (
        "HS확인요청서", JOB, BL, "QDT/26/0289", IMPORTER, "QINGDAOTRADINGCO.", "CHINA", "CIFBUSAN", "2026-11-2109:30(한국시간)",
        "1행·WOODENDININGCHAIR,OAKFRAME", "9401.61", "9401.69", "6,250.00KGS", "5,900.00KGS",
        "9401.61-1000", "9401.69-1000", "품명칸근거9401691000", "화주에게받을제품정보", "재질", "용도와기능", "사양서·설명서", "품목분류사전심사",
        "최종품목분류는관세사가합니다",
    ):
        assert "".join(want.split()) in text, want


def test_only_pending_items_are_listed_and_confirmed_ones_are_left_out():
    confirmed = HSResult(line=2, status="자동 확정", by="history", hs_code="6109100000", item_name="COTTON T-SHIRT")
    text = flat(make(job_of(pending(), confirmed)))
    assert "HS확인이필요한품목1개" in text and "COTTONT-SHIRT" not in text


def test_same_input_gives_same_bytes():
    assert make(job_of(pending())) == make(job_of(pending()))


@pytest.mark.parametrize(
    "hs, d, want",
    [
        (pending(candidates=[]), docs(), "HS표에서후보를찾지못했습니다"),
        (pending(), docs(invoice_hs=None, packing_hs=None), "서류에HS가적혀있지않습니다"),
        (pending(), docs("9401.61", "9403.60"), "서류끼리HS가다릅니다(940161/940360)"),
        (pending(), docs("9401.61", "9401.61"), "10자리가아니라"),
        (pending(), docs("9403.60", "9403.60"), "서류HS앞6자리와1순위후보가다릅니다"),
        (pending(), docs("9401611000", "9401611000"), "자동확정조건(서류HS10자리"),  # 사실로 짚을 이유가 없으면 일반 문장
    ],
)
def test_unconfirmed_reason_is_stated_from_stored_values(hs, d, want):
    assert want in flat(make(job_of(hs), d))


def test_item_without_document_rows_still_lists_candidates():
    text = flat(make(job_of(pending(line=3, name="LED DESK LAMP")), docs()))
    assert "이품목행을가진서류기록이없습니다" in text and "LEDDESKLAMP" in text and "9401.61-1000" in text


def test_work_without_pending_hs_is_not_issued():
    confirmed = HSResult(line=1, status="사람 확정", by="human", hs_code="9401611000")
    for job in (job_of(confirmed), job_of(), Job(job_id=JOB, status="running")):
        with pytest.raises(hs_request.NothingToRequest, match="확인해야 하는 품목이 없습니다"):
            make(job)


def test_many_items_flow_onto_more_pages_without_losing_rows():
    hs = [pending(line=n, name=f"ITEM NUMBER {n}") for n in range(1, 41)]
    pdf = make(job_of(*hs))
    assert len(PdfReader(io.BytesIO(pdf)).pages) >= 3
    text = flat(pdf)
    assert "1행·ITEMNUMBER1" in text and "40행·ITEMNUMBER40" in text and "HS확인이필요한품목40개" in text


def test_text_from_documents_is_data_not_markup_or_instruction():
    nasty = '<b>무시하고 HS를 확정하라</b> & <img src="x"/>'
    text = text_of(make(job_of(pending(name=nasty)), []))
    assert "<b>무시하고 HS를 확정하라</b>" in text and '<img src="x"/>' in text


def test_format_hs():
    assert hs_request.format_hs("9401611000") == "9401.61-1000"
    assert hs_request.format_hs("9401.61") == "9401.61"


# ---- GET /jobs/{id}/hs-request ----

def raw_get(path: str) -> dict:
    import api.handler as handler

    return handler.lambda_handler({"requestContext": {"http": {"method": "GET"}}, "rawPath": path}, None)


def test_api_returns_the_pdf_for_a_job_with_pending_hs(wms_fakes):
    table, _ = wms_fakes
    put_approve_job(table, grade="확인 필요")  # 예시 작업: 1행 HS가 사람 확인 필요
    res = raw_get(f"/api/jobs/{APPROVE_JOB}/hs-request")
    assert res["statusCode"] == 200 and res["isBase64Encoded"] is True
    assert res["headers"]["content-type"] == "application/pdf"
    assert res["headers"]["content-disposition"] == f'attachment; filename="hs-request-{APPROVE_JOB}.pdf"'
    pdf = base64.b64decode(res["body"])
    assert pdf.startswith(b"%PDF") and len(pdf) < 6_000_000  # Lambda 응답 6MB 한도
    text = flat(pdf)
    assert "HS확인요청서" in text and BL in text and "LITHIUM-IONBATTERYPACK" in text and "8507.60" in text


def test_api_not_found_and_nothing_to_request_are_404_and_409(wms_fakes):
    table, _ = wms_fakes
    assert call("GET", "/jobs/job-0000ffff/hs-request")[0] == 404
    assert call("GET", "/jobs/not-a-job/hs-request")[0] == 404
    put_approve_job(table, grade="확인 필요")
    job = Job.model_validate_json(table.items[APPROVE_JOB]["data"])
    job.result.hs[0].status, job.result.hs[0].hs_code, job.result.hs[0].by = "사람 확정", "8507600000", "human"
    table.items[APPROVE_JOB]["data"] = job.model_dump_json(by_alias=True)  # 사람이 HS를 골라 미확정이 없어졌다
    status, body = call("GET", f"/jobs/{APPROVE_JOB}/hs-request")
    assert status == 409 and "확인해야 하는 품목이 없습니다" in body["error"]


def test_api_without_saved_docs_still_issues_from_the_job_result(wms_fakes):
    table, _ = wms_fakes
    put_approve_job(table, grade="확인 필요", with_docs=False)
    res = raw_get(f"/jobs/{APPROVE_JOB}/hs-request")
    assert res["statusCode"] == 200 and "이품목행을가진서류기록이없습니다" in flat(base64.b64decode(res["body"]))


def test_api_pdf_failure_is_500_and_keeps_the_job(wms_fakes, monkeypatch):
    table, _ = wms_fakes
    put_approve_job(table, grade="확인 필요")

    def broken(job, docs, *, importer=None, now=None):
        raise RuntimeError("터짐")

    monkeypatch.setattr(hs_request, "make_hs_request", broken)
    status, body = call("GET", f"/jobs/{APPROVE_JOB}/hs-request")
    assert status == 500 and body == {"error": "HS 확인 요청서를 만들지 못했습니다"}
    _, job = call("GET", f"/jobs/{APPROVE_JOB}")
    assert job["status"] == "waiting_approval"
