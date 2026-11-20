"""api/handler.py 단위 테스트. DynamoDB·S3·Bedrock·Lambda 호출은 가짜로 바꾼다."""

import base64
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import boto3
import pytest
from botocore.exceptions import ClientError

import api.handler as handler
import api.worker as worker
import tools.declaration as declaration
import tools.extract as extract
import tools.hs as hs
import tools.report as report
import tools.wms as wms
from tests.unit.fakes import MemoryHSHistory, MemoryWms
from tests.unit.test_report_shipment import TODAY, MemoryWriter
from tools.models import (
    Cell, DeclarationDraft, DeclarationField, ExtractedDocument, Issue, Job, RawDocument, Shipment, WmsState,
)

EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "examples"


@pytest.fixture(autouse=True)
def shipments(monkeypatch):
    """화물 기록(team06-shipments) 대신 메모리판 (E3). 처리 Lambda·승인·자동 등록이 여기에 쓴다. 오늘은 고정."""
    store = MemoryWriter()
    monkeypatch.setattr(handler, "dynamo_shipments", lambda: store)
    monkeypatch.setattr(worker, "dynamo_shipments", lambda: store)
    monkeypatch.setattr(report, "_today", lambda: TODAY)
    return store

TOTALS = {"invoice.pdf": "6,250.00 KGS", "packing_list.pdf": "6,520.00 KGS", "pl_ok.pdf": "6,250 KG"}


class FakeTable:
    def __init__(self):
        self.items = {}

    def put_item(self, Item):
        self.items[Item["job_id"]] = Item

    def get_item(self, Key):
        item = self.items.get(Key["job_id"])
        return {"Item": item} if item else {}

    def scan(self, **kwargs):  # 문서 분류 내역(#143). 한 쪽에 다 준다
        return {"Items": list(self.items.values())}


class FakeLambda:
    """boto3 lambda 클라이언트 대신. invoke 인자를 calls에 남긴다. 실제 처리는 process()가 한다."""

    def __init__(self):
        self.calls = []
        self.status = 202  # 비동기 호출(Event)이 받아들여졌을 때의 값
        self.error = None

    def invoke(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return {"StatusCode": self.status}


@pytest.fixture
def lambda_client(monkeypatch):
    client = FakeLambda()
    monkeypatch.setenv("WORKER_FUNCTION", "team06-worker")
    monkeypatch.setattr(handler, "_lambda", lambda: client)
    return client


def process(client: FakeLambda) -> list[dict]:
    """API가 처리 Lambda에 보낸 이벤트를 차례로 돌린다 (배포에서는 Lambda가 비동기로 돌린다)."""
    done = [worker.lambda_handler(json.loads(c["Payload"]), None) for c in client.calls]
    client.calls.clear()
    return done


@pytest.fixture
def fakes(monkeypatch, lambda_client):
    table = FakeTable()
    monkeypatch.setattr(handler, "_table", lambda: table)
    # S3 대신 키 이름을 바이트로 돌려준다
    monkeypatch.setattr(handler, "fetch_object", lambda key: key.encode())

    def fake_reader(blocks, prompt):
        key = blocks[0]["document"]["source"]["bytes"].decode()
        name = key.rsplit("/", 1)[-1]
        if name == "broken.pdf":
            raise RuntimeError("모델 오류")
        # 총중량만 서류마다 다르고, 송장 번호와 총수량은 같게 둔다 (빈 칸은 '확인 필요'가 되므로 채워야 한다)
        return RawDocument.model_validate(
            {
                "doc_no": {"raw": "INV-2026-001"},
                "total_qty": {"raw": "100 PCS"},
                "total_gross_kg": {"raw": TOTALS[name]},
            }
        )

    monkeypatch.setattr(extract, "_strands_reader", fake_reader)
    return table


def call(method, path, body=None):
    event = {"requestContext": {"http": {"method": method}}, "rawPath": path}
    if body is not None:
        event["body"] = json.dumps(body)
    res = handler.lambda_handler(event, None)
    return res["statusCode"], json.loads(res["body"])


def files(*names):
    types = {"invoice.pdf": "commercial_invoice"}
    return {"files": [{"key": f"uploads/s1/{n}", "doc_type": types.get(n, "packing_list")} for n in names]}


def http_api_event(method, raw_path, body=None, *, encoded=False):
    """CloudFront 뒤의 API Gateway HTTP API가 보내는 페이로드 2.0 모양. encoded면 본문을 base64로 싼다."""
    event = {
        "version": "2.0",
        "routeKey": "ANY /api/{proxy+}",
        "rawPath": raw_path,
        "rawQueryString": "",
        "headers": {"content-type": "application/json", "user-agent": "Amazon CloudFront", "via": "2.0 x.cloudfront.net"},
        "requestContext": {
            "apiId": "abc123",
            "domainName": "abc123.execute-api.ap-northeast-2.amazonaws.com",
            "http": {"method": method, "path": raw_path, "protocol": "HTTP/1.1", "sourceIp": "203.0.113.1"},
            "requestId": "req-1",
            "routeKey": "ANY /api/{proxy+}",
            "stage": "$default",
        },
        "isBase64Encoded": encoded,
    }
    if body is not None:
        text = json.dumps(body, ensure_ascii=False)
        event["body"] = base64.b64encode(text.encode("utf-8")).decode() if encoded else text
    res = handler.lambda_handler(event, None)
    return res["statusCode"], json.loads(res["body"])


@pytest.mark.parametrize("path", ["/api", "/api/", "/"])
def test_health(path):
    """배포 확인: GET /api/ → {"ok": true} (F1 끝난 기준). /api 없는 옛 주소도 받는다."""
    assert call("GET", path) == (200, {"ok": True})


@pytest.mark.parametrize(
    "raw, routed",
    [
        ("/api", "/"), ("/api/", "/"), ("/api/jobs", "/jobs"), ("/api/jobs/job-1234abcd/hs/", "/jobs/job-1234abcd/hs"),
        ("/jobs", "/jobs"), ("/", "/"), ("", "/"), (None, "/"), ("/apix", "/apix"), ("/api-jobs", "/api-jobs"),
    ],
)
def test_route_path_strips_api_prefix(raw, routed):
    assert handler._route_path(raw) == routed


def test_post_saves_queued_and_invokes_worker_without_processing(fakes, lambda_client):
    """끝난 기준: POST /api/jobs는 queued로 저장하고 job_id를 바로 응답한다. 처리 Lambda를 약속(#36)대로 부른다."""
    request = files("invoice.pdf", "packing_list.pdf")

    status, body = call("POST", "/api/jobs", request)

    assert status == 200 and set(body) == {"job_id"}
    job_id = body["job_id"]
    assert call("GET", f"/api/jobs/{job_id}") == (
        200, {"job_id": job_id, "status": "queued", "steps": [], "result": None, "error": None},
    )
    [invoked] = lambda_client.calls
    assert invoked["FunctionName"] == "team06-worker" and invoked["InvocationType"] == "Event"
    assert json.loads(invoked["Payload"]) == {"job_id": job_id, "files": request["files"]}


def test_post_then_worker_shows_mismatch(fakes, lambda_client):
    status, body = call("POST", "/api/jobs", files("invoice.pdf", "packing_list.pdf"))
    assert status == 200
    assert process(lambda_client) == [{"job_id": body["job_id"], "status": "waiting_approval"}]
    status, job = call("GET", f"/api/jobs/{body['job_id']}")
    assert status == 200
    Job.model_validate(job)  # 약속 2 형식
    assert job["status"] == "waiting_approval"
    # 선하증권이 없어 먼저 빠진 서류로 남긴다 (#168). 불일치 칸은 다시 확인한다 (B8): 상업송장·포장명세서 총중량
    # 끝나면 화물 기록 한 줄 (E3). 이 서류에는 선하증권이 없어 쓰지 않았다는 줄이다
    assert [s["tool"] for s in job["steps"]] == [
        "check_missing_docs", "read_document", "read_document", "cross_check", "reread_field", "reread_field",
        "record_shipment",
    ]
    assert "B/L 번호가 없어" in job["steps"][-1]["summary"]
    issue, missing = job["result"]["issues"]
    assert issue["grade"] == "불일치" and issue["rule_id"] == "X-WT-01"
    assert (missing["rule_id"], missing["grade"]) == ("DOC-MISSING", "확인 필요")
    # 승인 대기로 끝나면 화면이 승인 입력을 그리도록 wms를 채운다 (#159, 실제 run_job 출력 FB14)
    assert job["result"]["wms"] == {"status": "승인 대기", "by": None, "wms_id": None}


def test_matching_docs_are_done(fakes, lambda_client):
    """서로 맞는 두 장은 불일치가 없다. 선하증권이 없어 빠진 서류 '확인 필요'만 남고 승인 대기다 (#168)."""
    _, body = call("POST", "/api/jobs", files("invoice.pdf", "pl_ok.pdf"))
    process(lambda_client)
    _, job = call("GET", f"/api/jobs/{body['job_id']}")
    assert job["status"] == "waiting_approval"
    assert [i["rule_id"] for i in job["result"]["issues"]] == ["DOC-MISSING"]


def test_read_failure_is_check_needed(fakes, lambda_client):
    _, body = call("POST", "/api/jobs", files("invoice.pdf", "broken.pdf"))
    process(lambda_client)
    _, job = call("GET", f"/api/jobs/{body['job_id']}")
    assert job["status"] == "waiting_approval"
    assert job["result"]["issues"][0]["rule_id"] == "READ-FAIL"
    assert [s["tool"] for s in job["steps"] if not s["ok"]] == ["read_document"]  # 첫 단계는 빠진 서류 (#168)


def test_old_paths_without_api_prefix_still_work(fakes, lambda_client):
    """옮기는 동안 /api 없는 경로도 받는다 (#36)."""
    _, body = call("POST", "/jobs", files("invoice.pdf", "pl_ok.pdf"))
    process(lambda_client)
    status, job = call("GET", f"/jobs/{body['job_id']}")
    assert status == 200 and job["status"] == "waiting_approval"  # 끝까지 처리됨. 선하증권이 없어 승인 대기 (#168)


def test_http_api_v2_events_end_to_end(fakes, lambda_client):
    """API Gateway HTTP API 2.0 이벤트(본문 base64 포함)로 상태 확인 → 작업 생성 → 처리 → 조회."""
    assert http_api_event("GET", "/api/") == (200, {"ok": True})

    status, body = http_api_event("POST", "/api/jobs", files("invoice.pdf", "packing_list.pdf"), encoded=True)
    assert status == 200
    assert http_api_event("GET", f"/api/jobs/{body['job_id']}")[1]["status"] == "queued"

    process(lambda_client)
    status, job = http_api_event("GET", f"/api/jobs/{body['job_id']}")
    assert status == 200 and job["status"] == "waiting_approval"


@pytest.mark.parametrize("problem", ["error", "status"])
def test_worker_invoke_failure_is_502_and_job_failed(fakes, lambda_client, problem):
    """처리 Lambda를 못 부르면 화면이 끝없이 기다리지 않게 작업을 failed로 남기고 502를 준다."""
    if problem == "error":
        lambda_client.error = ClientError({"Error": {"Code": "AccessDeniedException", "Message": "가짜"}}, "Invoke")
    else:
        lambda_client.status = 200

    status, body = call("POST", "/api/jobs", files("invoice.pdf", "packing_list.pdf"))

    assert status == 502 and "다시 올려" in body["error"]
    [item] = fakes.items.values()
    job = Job.model_validate_json(item["data"])
    assert job.status == "failed" and job.error.startswith("처리를 시작하지 못했습니다")


def test_bad_post_does_not_invoke_worker(fakes, lambda_client):
    assert call("POST", "/api/jobs", {"files": []})[0] == 400
    assert lambda_client.calls == [] and fakes.items == {}


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"files": []},
        {"files": [{"key": "secret/x.pdf", "doc_type": "packing_list"}]},
        {"files": [{"key": "uploads/../x.pdf", "doc_type": "packing_list"}]},
        {"files": [{"key": "uploads/x.pdf", "doc_type": "unknown"}]},
        {"files": [{"key": "uploads/x.pdf", "doc_type": "invoice"}]},
        {"files": [{"key": "uploads/x.pdf"}]},  # doc_type 칸 없음 (null과 다르다)
    ],
)
def test_bad_requests_are_400(fakes, body):
    assert call("POST", "/jobs", body)[0] == 400


@pytest.mark.parametrize(
    "doc_type", [None, "commercial_invoice", "packing_list", "bill_of_lading", "certificate_of_origin"]
)
def test_doc_type_null_or_four_kinds_are_accepted(fakes, lambda_client, doc_type):
    """화면(G9)은 doc_type을 null로 보내고 run_job이 분류한다. 정해 보내면 약속 1의 4종만 받는다 (#129)."""
    status, _ = call("POST", "/api/jobs", {"files": [{"key": "uploads/s1/a.pdf", "doc_type": doc_type}]})

    assert status == 200
    [invoked] = lambda_client.calls
    assert json.loads(invoked["Payload"])["files"] == [{"key": "uploads/s1/a.pdf", "doc_type": doc_type}]


def test_unknown_job_and_path_are_404(fakes):
    assert call("GET", "/jobs/job-00000000")[0] == 404
    assert call("GET", "/api/jobs/job-00000000")[0] == 404
    assert call("GET", "/jobs/../../etc")[0] == 404
    assert call("GET", "/nothing")[0] == 404
    assert call("GET", "/api/nothing")[0] == 404
    assert call("GET", "/apix")[0] == 404


def test_no_planned_routes_left():
    """약속 2의 경로를 모두 만들었다 (/chat은 E5). 501로 남은 경로가 없다."""
    assert handler._PLANNED == {}


# ---------------------------------------------------------------------------
# POST /uploads (F2). 서명은 가짜 S3 클라이언트로 바꾸고, 실제 botocore 서명 모양은 따로 본다.
# ---------------------------------------------------------------------------
class FakeS3:
    def __init__(self):
        self.signed = []

    def generate_presigned_url(self, operation, Params, ExpiresIn, HttpMethod):
        self.signed.append((operation, Params, ExpiresIn, HttpMethod))
        return f"https://s3.test/{Params['Key']}?sig={len(self.signed)}"


@pytest.fixture
def s3(monkeypatch):
    fake = FakeS3()
    monkeypatch.setattr(handler, "_s3", lambda: fake)
    monkeypatch.setenv("DOCS_BUCKET", "team06-docs-test")
    return fake


def test_uploads_give_one_put_url_per_file(s3):
    """끝난 기준: 화면이 받은 url로 S3에 직접 PUT한다. key는 요청 순서대로, 같은 이름도 겹치지 않는다."""
    req = [
        {"name": "invoice.pdf", "content_type": "application/pdf"},
        {"name": "포장 명세서.PNG", "content_type": "image/png"},
        {"name": "invoice.pdf", "content_type": "application/octet-stream"},  # 브라우저가 type을 모를 때
    ]
    status, body = call("POST", "/uploads", {"files": req})

    assert status == 200
    uploads = body["uploads"]
    batch = uploads[0]["key"].split("/")[1]
    assert re.fullmatch(r"[0-9a-f]{32}", batch)
    assert [u["key"] for u in uploads] == [
        f"uploads/{batch}/1-invoice.pdf",
        f"uploads/{batch}/2-포장_명세서.png",
        f"uploads/{batch}/3-invoice.pdf",
    ]
    assert [u["url"] for u in uploads] == [f"https://s3.test/{u['key']}?sig={n}" for n, u in enumerate(uploads, 1)]
    # PUT 서명에 버킷·키·content-type이 들어간다 (화면이 같은 content-type으로 PUT해야 맞는다)
    assert s3.signed == [
        ("put_object", {"Bucket": "team06-docs-test", "Key": u["key"], "ContentType": f["content_type"]}, 300, "PUT")
        for u, f in zip(uploads, req)
    ]
    # 받은 key로 바로 POST /jobs를 부를 수 있다
    jobs = {"files": [{"key": u["key"], "doc_type": "packing_list"} for u in uploads]}
    assert handler._validate_files(jobs) == (jobs["files"], None)


def test_each_upload_request_gets_new_batch(s3):
    req = {"files": [{"name": "a.pdf", "content_type": "application/pdf"}]}
    first, second = call("POST", "/uploads", req)[1], call("POST", "/uploads", req)[1]
    assert first["uploads"][0]["key"] != second["uploads"][0]["key"]


def test_uploads_route_with_api_prefix(s3):
    """배포에서는 rawPath에 /api가 붙어 온다 (F3 _route_path). 화면은 /api/uploads를 부른다."""
    status, body = call("POST", "/api/uploads/", {"files": [{"name": "a.pdf", "content_type": "application/pdf"}]})
    assert status == 200 and body["uploads"][0]["key"].endswith("/1-a.pdf")
    assert len(s3.signed) == 1


@pytest.mark.parametrize(
    "name, safe",
    [
        ("invoice.pdf", "invoice.pdf"),
        ("../../secret/x.PDF", "x.pdf"),  # 경로는 버린다
        ("C:\\fakepath\\inv.jpeg", "inv.jpeg"),
        ("a..b.jpg", "a_b.jpg"),  # '..'이 남으면 POST /jobs가 거절한다
        ("<img src=x onerror=alert(1)>.png", "img_src_x_onerror_alert_1.png"),
        ("상업송장 (최종).pdf", "상업송장_최종.pdf"),
        ("\u1109\u1161\u11bc\u110b\u1165\u11b8.pdf", "상업.pdf"),  # macOS의 풀어 쓴 한글(NFD)은 모아 쓴다
        ("###.pdf", "file.pdf"),  # 남는 글자가 없으면 file
        ("x" * 200 + ".pdf", "x" * handler.NAME_MAX + ".pdf"),
        ("memo.txt", None),
        ("noext", None),
        (".pdf", None),
    ],
)
def test_upload_names_are_made_safe(name, safe):
    assert handler._safe_name(name) == safe


@pytest.mark.parametrize(
    "body",
    [
        {},
        ["a.pdf"],
        {"files": []},
        {"files": "a.pdf"},
        {"files": [{"name": f"{n}.pdf", "content_type": "application/pdf"} for n in range(11)]},
        {"files": ["a.pdf"]},
        {"files": [{"content_type": "application/pdf"}]},
        {"files": [{"name": "  ", "content_type": "application/pdf"}]},
        {"files": [{"name": 7, "content_type": "application/pdf"}]},
        {"files": [{"name": "memo.txt", "content_type": "text/plain"}]},
        {"files": [{"name": "a.pdf"}]},
        {"files": [{"name": "a.pdf", "content_type": "image/png"}]},  # 확장자와 다른 형식
        {"files": [{"name": "a.pdf", "content_type": "text/html"}]},
        {"files": [{"name": "a.pdf", "content_type": "application/pdf"}, {"name": "b.exe", "content_type": handler.UNKNOWN_TYPE}]},
    ],
)
def test_upload_bad_requests_are_400_and_sign_nothing(s3, body):
    status, res = call("POST", "/uploads", body)
    assert status == 400 and res["error"]
    assert s3.signed == []


def test_presigned_url_is_regional_sigv4_with_content_type(monkeypatch):
    """실제 botocore로 서명만 해 본다 (AWS를 부르지 않는다. 자격 증명은 가짜 문자열).

    지역 주소여야 새 버킷에서도 307 없이 브라우저 PUT이 바로 간다. content-type이 서명에 들어가야
    화면이 보낸 형식 그대로 저장된다.
    """
    for name in ("AWS_PROFILE", "AWS_SESSION_TOKEN", "AWS_ENDPOINT_URL", "AWS_ENDPOINT_URL_S3"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "fake-id")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "fake-secret")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-northeast-2")
    monkeypatch.setenv("DOCS_BUCKET", "team06-docs-test")
    monkeypatch.setattr(boto3, "DEFAULT_SESSION", None)  # 다른 곳에서 만든 세션의 자격 증명을 쓰지 않게
    handler._s3.cache_clear()
    try:
        url = handler.presign_upload("uploads/b1/1-상업송장.pdf", "application/pdf")
    finally:
        handler._s3.cache_clear()

    parts = urlsplit(url)
    query = parse_qs(parts.query)
    assert (parts.scheme, parts.netloc) == ("https", "team06-docs-test.s3.ap-northeast-2.amazonaws.com")
    assert unquote(parts.path) == "/uploads/b1/1-상업송장.pdf"
    assert query["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]
    assert query["X-Amz-SignedHeaders"] == ["content-type;host"]
    assert query["X-Amz-Expires"] == [str(handler.UPLOAD_SECONDS)]


# ---------------------------------------------------------------------------
# POST /jobs/{id}/hs (C3). 2번의 item_key·confirm_by_human·draft_declaration은 가짜로 바꾼다.
# ---------------------------------------------------------------------------
HS_JOB = "job-00000c03"
IMPORTER = "ACME KOREA CO., LTD."


def example(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def example_docs() -> list[ExtractedDocument]:
    """예시 포장명세서와, 같은 품목을 다른 품목 코드로 적은 상업송장 (키가 어느 서류에서 왔는지 보려고)."""
    pl = ExtractedDocument.model_validate(example("extract_packing_list.json"))
    ci = pl.model_copy(deep=True, update={"doc_type": "commercial_invoice", "file": "uploads/sample-001/invoice.pdf"})
    ci.items[0].item_code.value = "CI-BP-200"
    return [pl, ci]


def put_hs_job(table, *, status="waiting_approval", with_docs=True, with_importer=True):
    job = Job.model_validate({**example("job_waiting_approval.json"), "job_id": HS_JOB, "status": status})
    if status == "running":
        job.result = None
    item = {"job_id": HS_JOB, "data": job.model_dump_json(by_alias=True), "updated_at": 0}
    if with_docs:
        docs = [d.model_dump(mode="json") for d in example_docs()]
        item |= {"docs": json.dumps(docs, ensure_ascii=False)}
        if with_importer:  # 처리 Lambda는 수입자를 모르면 이 칸을 쓰지 않는다 (#122)
            item["importer"] = IMPORTER
    table.put_item(Item=item)


@pytest.fixture
def wms_memory(monkeypatch):
    """가상 WMS(team06-wms) 대신 메모리판. 승인(D3)과 HS 선택 뒤 자동 등록(D2)이 여기에 쓴다."""
    memory = MemoryWms()
    monkeypatch.setattr(wms, "dynamo_wms", lambda: memory)
    return memory


@pytest.fixture
def hs_fakes(fakes, wms_memory, monkeypatch):
    """C2·C5가 아직 없어서 같은 모양의 가짜를 끼운다. 부른 인자를 calls에 남긴다."""
    history = MemoryHSHistory()
    calls = {"item_key": [], "confirm": [], "draft": []}

    def fake_item_key(doc, line):
        calls["item_key"].append((doc.doc_type, line))
        return next(i for i in doc.items if i.line == line).item_code.value

    def fake_confirm(result, code, importer, key, job_id, *, history):
        calls["confirm"].append((result.line, code, importer, key, job_id))
        history.put(importer, key, code, job_id)
        return result.model_copy(update={"status": "사람 확정", "by": "human", "hs_code": code})

    def fake_draft(docs, issues, hs_results):
        calls["draft"].append(([d.doc_type for d in docs], len(issues), [r.hs_code for r in hs_results]))
        fields = [DeclarationField(name="세번부호", value=r.hs_code, source="hs") for r in hs_results if r.hs_code]
        return DeclarationDraft(fields=fields, blank_fields=["items[0].gross_kg"])

    monkeypatch.setattr(handler, "_hs_history", lambda: history)
    monkeypatch.setattr(hs, "item_key", fake_item_key)
    monkeypatch.setattr(hs, "confirm_by_human", fake_confirm)
    monkeypatch.setattr(declaration, "draft_declaration", fake_draft)
    return fakes, history, calls


def test_hs_choice_fills_draft_and_saves_history(hs_fakes):
    table, history, calls = hs_fakes
    put_hs_job(table)

    status, body = call("POST", f"/jobs/{HS_JOB}/hs", {"choices": [{"line": 1, "hs": "8507600000"}]})

    assert status == 200
    draft = DeclarationDraft.model_validate(body["declaration_draft"])
    assert [(f.name, f.value) for f in draft.fields] == [("세번부호", "8507600000")]
    # 이력 키는 상업송장의 품목 코드, 수입자는 저장해 둔 값
    assert calls["item_key"] == [("commercial_invoice", 1)]
    assert calls["confirm"] == [(1, "8507600000", IMPORTER, "CI-BP-200", HS_JOB)]
    assert history.rows == {(IMPORTER, "CI-BP-200"): ("8507600000", HS_JOB)}
    # 초안은 확정한 HS와 남은 문제로 다시 채운다
    assert calls["draft"] == [(["packing_list", "commercial_invoice"], 1, ["8507600000"])]

    _, job = call("GET", f"/jobs/{HS_JOB}")
    [line1] = job["result"]["hs"]
    assert (line1["status"], line1["by"], line1["hs_code"]) == ("사람 확정", "human", "8507600000")
    assert job["result"]["declaration_draft"] == body["declaration_draft"]
    assert [s["tool"] for s in job["steps"][-2:]] == ["confirm_by_human", "draft_declaration"]
    # 다음 요청을 위해 서류 기록은 그대로 남는다
    assert table.items[HS_JOB]["importer"] == IMPORTER and table.items[HS_JOB]["docs"]


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"choices": []},
        {"choices": [{"line": 2, "hs": "8507600000"}]},  # 이 작업에 없는 행
        {"choices": [{"line": "1", "hs": "8507600000"}]},
        {"choices": [{"line": True, "hs": "8507600000"}]},
        {"choices": [{"line": 1, "hs": "8507.60"}]},
        {"choices": [{"line": 1, "hs": "850760"}]},  # 6자리
        {"choices": [{"line": 1, "hs": 8507600000}]},
        {"choices": [{"line": 1, "hs": "8507600000"}, {"line": 1, "hs": "8507600000"}]},
    ],
)
def test_hs_bad_choices_are_400_and_write_nothing(hs_fakes, body):
    table, history, calls = hs_fakes
    put_hs_job(table)
    assert call("POST", f"/jobs/{HS_JOB}/hs", body)[0] == 400
    assert history.rows == {} and calls["confirm"] == [] and calls["draft"] == []


def test_hs_unknown_job_is_404(hs_fakes):
    assert call("POST", "/jobs/job-00000000/hs", {"choices": [{"line": 1, "hs": "8507600000"}]})[0] == 404
    assert call("POST", "/jobs/nope/hs", {"choices": [{"line": 1, "hs": "8507600000"}]})[0] == 404


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"status": "running"}, "승인 대기 중인 작업에서만"),
        ({"with_docs": False}, "저장된 서류 기록이 없어"),
        ({"with_importer": False}, "수입자(Consignee)를 읽지 못해"),
    ],
    ids=["running", "no-docs", "no-importer"],
)
def test_hs_job_not_ready_is_409(hs_fakes, kwargs, message):
    """처리 중인 작업, 서류 기록이나 수입자가 없는 작업은 고를 수 없다. 이력도 쓰지 않는다."""
    table, history, calls = hs_fakes
    put_hs_job(table, **kwargs)
    status, body = call("POST", f"/jobs/{HS_JOB}/hs", {"choices": [{"line": 1, "hs": "8507600000"}]})
    assert status == 409 and message in body["error"]
    assert history.rows == {} and calls["confirm"] == []


def test_dynamo_hs_history_round_trip():
    class FakeHistoryTable:
        def __init__(self):
            self.items = {}

        def put_item(self, Item):
            self.items[(Item["importer"], Item["item_key"])] = Item

        def get_item(self, Key):
            item = self.items.get((Key["importer"], Key["item_key"]))
            return {"Item": item} if item else {}

    store = handler.DynamoHSHistory(FakeHistoryTable())
    assert store.get(IMPORTER, "BP-200") is None
    store.put(IMPORTER, "BP-200", "8507600000", HS_JOB)
    assert store.get(IMPORTER, "BP-200") == "8507600000"


# ---------------------------------------------------------------------------
# POST /jobs/{id}/approve (D3). 가상 WMS(team06-wms)는 메모리판으로 바꾼다.
# ---------------------------------------------------------------------------
APPROVE_JOB = "job-00000d03"
BL = "BL-2026-0001"


def put_approve_job(
    table, *, grade="불일치", status="waiting_approval", with_docs=True, with_bl=True, with_importer=True, wms_state=None
):
    """예시 작업(문제 1건, 1행 HS 사람 확인 필요)을 넣는다. grade로 그 문제의 등급을 바꾼다."""
    job = Job.model_validate({**example("job_waiting_approval.json"), "job_id": APPROVE_JOB, "status": status})
    job.result.issues[0].grade = grade
    if wms_state is not None:
        job.result.wms = WmsState.model_validate(wms_state)
    item = {"job_id": APPROVE_JOB, "data": job.model_dump_json(by_alias=True), "updated_at": 0}
    if with_docs:
        docs = example_docs()
        if with_bl:
            docs.append(ExtractedDocument(doc_type="bill_of_lading", file="uploads/sample-001/bl.pdf", doc_no=Cell(raw=BL, value=BL)))
        item |= {"docs": json.dumps([d.model_dump(mode="json") for d in docs], ensure_ascii=False)}
        if with_importer:
            item["importer"] = IMPORTER
    table.put_item(Item=item)


@pytest.fixture
def wms_fakes(fakes, wms_memory):
    return fakes, wms_memory


def post_approve(body=None):
    return call("POST", f"/jobs/{APPROVE_JOB}/approve", {"approver": "김담당"} if body is None else body)


def test_approve_registers_by_human_and_saves_wms(wms_fakes):
    """확인 필요만 남은 건은 사람이 승인하면 등록한다. 화면이 다시 부르는 GET에는 by까지 남는다 (G7)."""
    table, memory = wms_fakes
    put_approve_job(table, grade="확인 필요")

    status, body = post_approve({"approver": "  김   담당 "})

    assert (status, body) == (200, {"wms": {"status": "등록됨", "wms_id": "wms-0001"}})
    [(key, (wms_id, record))] = memory.records.items()
    assert (key, wms_id) == (f"{BL}#{APPROVE_JOB}", "wms-0001")
    assert (record.by, record.bl_no, record.job_id, record.consignee) == ("human", BL, APPROVE_JOB, IMPORTER)

    _, job = call("GET", f"/jobs/{APPROVE_JOB}")
    Job.model_validate(job)
    assert job["status"] == "done"
    assert job["result"]["wms"] == {"status": "등록됨", "by": "human", "wms_id": "wms-0001"}
    assert job["steps"][-2] == {"tool": "push_to_wms", "summary": "사람 승인(김 담당)으로 WMS 등록: wms-0001", "ok": True}
    assert job["steps"][-1]["tool"] == "mark_registered"  # 화물 기록 상태 고치기 (E3). 여기서는 줄이 없다
    assert table.items[APPROVE_JOB]["importer"] == IMPORTER and table.items[APPROVE_JOB]["docs"]


def shipment(bl_no=BL, *, job_id=APPROVE_JOB, status="입항") -> Shipment:
    return Shipment(bl_no=bl_no, consignee=IMPORTER, item="품명", arrived_at=TODAY.replace(day=1),
                    customs_status=status, last_event_at=TODAY.replace(day=1), job_id=job_id)


def test_approve_marks_shipment_registered(wms_fakes, shipments):
    """승인으로 WMS에 등록되면 이 작업이 쓴 화물 기록을 '수입신고'로 고친다 (E3). 입항일은 그대로다."""
    table, _ = wms_fakes
    put_approve_job(table, grade="확인 필요")
    shipments.rows[BL] = shipment()

    assert post_approve()[0] == 200

    row = shipments.rows[BL]
    assert (row.customs_status, row.arrived_at, row.last_event_at) == ("수입신고", TODAY.replace(day=1), TODAY)
    _, job = call("GET", f"/jobs/{APPROVE_JOB}")
    assert job["steps"][-1] == {"tool": "mark_registered", "summary": f"화물 기록 B/L {BL}: 입항 → 수입신고", "ok": True}


def test_approve_leaves_seed_shipment_alone(wms_fakes, shipments):
    """같은 B/L의 미리 넣은 가상 기록(job_id 없음)은 고치지 않는다."""
    table, _ = wms_fakes
    put_approve_job(table, grade="확인 필요")
    shipments.rows[BL] = seed = shipment(job_id=None)

    assert post_approve()[0] == 200
    assert shipments.rows[BL] == seed and shipments.puts == 0


def test_approve_still_done_when_shipments_store_fails(wms_fakes, monkeypatch):
    """화물 기록 저장소를 못 만들어도 WMS 등록과 작업 저장은 그대로 끝난다. 단계에만 실패로 남는다."""
    table, memory = wms_fakes
    put_approve_job(table, grade="확인 필요")

    def broken():
        raise KeyError("SHIPMENTS_TABLE")

    monkeypatch.setattr(handler, "dynamo_shipments", broken)

    assert post_approve() == (200, {"wms": {"status": "등록됨", "wms_id": "wms-0001"}})
    _, job = call("GET", f"/jobs/{APPROVE_JOB}")
    assert job["status"] == "done" and len(memory.records) == 1
    assert job["steps"][-1] == {"tool": "mark_registered", "summary": "화물 기록 상태를 고치지 못함: KeyError", "ok": False}


def test_approve_with_mismatch_is_409_and_changes_nothing(wms_fakes):
    """끝난 기준: 불일치가 남았으면 409와 {"error"} 문장 (화면이 그대로 보여 준다). 등록도 저장도 하지 않는다."""
    table, memory = wms_fakes
    put_approve_job(table)  # 예시 그대로: X-WT-01 불일치
    before = dict(table.items[APPROVE_JOB])

    status, body = post_approve()

    assert status == 409
    assert body == {"error": "불일치 1건(X-WT-01)이 남아 있어 WMS에 등록할 수 없습니다. 서류를 고쳐 다시 올려 주세요"}
    assert memory.records == {} and table.items[APPROVE_JOB] == before


def test_approve_twice_registers_once(wms_fakes):
    """두 번 누르거나 재시도해도 WMS에는 한 번, 단계 기록도 한 줄."""
    table, memory = wms_fakes
    put_approve_job(table, grade="확인 필요")

    first, again = post_approve(), post_approve()

    assert first == again == (200, {"wms": {"status": "등록됨", "wms_id": "wms-0001"}})
    assert len(memory.records) == 1
    _, job = call("GET", f"/jobs/{APPROVE_JOB}")
    assert [s["tool"] for s in job["steps"]].count("push_to_wms") == 1


def test_approve_after_auto_register_returns_that_state(wms_fakes):
    """이미 자동 등록(D2)된 건은 다시 등록하지 않고 그 상태를 돌려준다."""
    table, memory = wms_fakes
    put_approve_job(table, grade="참고", status="done", wms_state={"status": "등록됨", "by": "auto", "wms_id": "wms-auto"})
    assert post_approve() == (200, {"wms": {"status": "등록됨", "wms_id": "wms-auto"}})
    assert memory.records == {}


@pytest.mark.parametrize(
    "body",
    [{}, {"approver": ""}, {"approver": "   "}, {"approver": None}, {"approver": 7}, {"approver": "가" * 51}, ["김담당"]],
)
def test_approve_bad_requests_are_400(wms_fakes, body):
    table, memory = wms_fakes
    put_approve_job(table, grade="확인 필요")
    assert post_approve(body)[0] == 400
    assert memory.records == {}


def test_approve_unknown_job_is_404(wms_fakes):
    assert call("POST", "/jobs/job-00000000/approve", {"approver": "김담당"})[0] == 404
    assert call("POST", "/jobs/nope/approve", {"approver": "김담당"})[0] == 404


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"status": "running"}, "승인 대기 중인 작업에서만"),
        ({"with_docs": False}, "저장된 서류 기록이 없어"),
        ({"with_bl": False}, "B/L 번호가 없어"),
        ({"with_importer": False}, "수하인(수입자)이 비어 있어"),
    ],
    ids=["running", "no-docs", "no-bl", "no-importer"],
)
def test_approve_job_not_ready_is_409(wms_fakes, kwargs, message):
    table, memory = wms_fakes
    put_approve_job(table, grade="확인 필요", **kwargs)
    status, body = post_approve()
    assert status == 409 and message in body["error"]
    assert memory.records == {}


def test_approve_wms_failure_is_502_and_job_unchanged(wms_fakes, monkeypatch):
    """저장소 오류면 작업을 그대로 두어 다시 승인할 수 있게 한다."""
    table, _ = wms_fakes
    put_approve_job(table, grade="확인 필요")
    before = dict(table.items[APPROVE_JOB])

    class BrokenWms:
        def register(self, record):
            raise ClientError({"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "가짜"}}, "PutItem")

    monkeypatch.setattr(wms, "dynamo_wms", lambda: BrokenWms())
    status, body = post_approve()
    assert status == 502 and "다시 승인" in body["error"]
    assert table.items[APPROVE_JOB] == before


# ---------------------------------------------------------------------------
# GET /documents 문서 분류 내역 (G10 #143)
# ---------------------------------------------------------------------------
from tools.models import Classification, DocumentsResponse  # noqa: E402

CLASS_OF = {
    "invoice.pdf": ("commercial_invoice", "제목 COMMERCIAL INVOICE, Unit Price·Amount 칸"),
    "packing_list.pdf": ("packing_list", "제목 PACKING LIST (N.W./G.W.) 칸"),
    "memo.pdf": ("unknown", "제목 없음"),
}


def get_documents(doc_type, cursor=None):
    query = {"doc_type": doc_type} if doc_type is not None else None
    if cursor is not None:
        query["cursor"] = cursor
    event = {"requestContext": {"http": {"method": "GET"}}, "rawPath": "/api/documents", "queryStringParameters": query}
    res = handler.lambda_handler(event, None)
    return res["statusCode"], json.loads(res["body"])


@pytest.fixture
def classifier(monkeypatch):
    def fake(blocks, prompt):
        name = blocks[0]["document"]["source"]["bytes"].decode().rsplit("/", 1)[-1]
        if name == "broken.pdf":
            raise RuntimeError("분류 모델 오류")
        doc_type, reason = CLASS_OF[name]
        return Classification(doc_type=doc_type, reason=reason)

    monkeypatch.setattr(extract, "_strands_classifier", fake)


def post_untyped(*names, typed=()):
    body = {"files": [{"key": f"uploads/s1/{n}", "doc_type": CLASS_OF[n][0] if n in typed else None} for n in names]}
    status, res = call("POST", "/api/jobs", body)
    assert status == 200
    return res["job_id"]


def test_documents_follow_real_run_job_classification(fakes, lambda_client, classifier):
    """실제 run_job이 남긴 classify_document 기록에서 종류·근거를 읽는다. 문장 형식이 바뀌면 이 테스트가 깨진다."""
    job_id = post_untyped("invoice.pdf", "packing_list.pdf", "memo.pdf")
    item = fakes.items[job_id]
    assert json.loads(item["files"])[0] == {"key": "uploads/s1/invoice.pdf", "doc_type": None}
    assert isinstance(item["created_at"], int)
    process(lambda_client)

    status, body = get_documents("commercial_invoice")
    assert status == 200
    res = DocumentsResponse.model_validate(body)
    assert res.counts == {"bill_of_lading": 0, "certificate_of_origin": 0, "commercial_invoice": 1, "packing_list": 1, "unknown": 1}
    [rec] = res.items
    assert (rec.job_id, rec.key, rec.file_name) == (job_id, "uploads/s1/invoice.pdf", "invoice.pdf")
    assert (rec.classified_by, rec.reason) == ("model", CLASS_OF["invoice.pdf"][1])
    assert rec.doc_no == "INV-2026-001" and rec.job_status == "waiting_approval"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", rec.created_at) and res.next_cursor is None
    [memo] = DocumentsResponse.model_validate(get_documents("unknown")[1]).items
    assert (memo.file_name, memo.reason, memo.doc_no) == ("memo.pdf", "제목 없음", None)


def test_documents_user_typed_and_failed_classification(fakes, lambda_client, classifier):
    post_untyped("invoice.pdf", "broken.pdf", typed=("invoice.pdf",))
    process(lambda_client)

    [typed] = DocumentsResponse.model_validate(get_documents("commercial_invoice")[1]).items
    assert typed.classified_by == "user" and typed.reason == "올릴 때 사용자가 고른 종류"
    [failed] = DocumentsResponse.model_validate(get_documents("unknown")[1]).items
    assert failed.file_name == "broken.pdf" and failed.reason.startswith("분류 실패: 모델 호출 실패: RuntimeError")


def test_documents_skip_files_not_classified_yet(fakes, lambda_client, classifier):
    post_untyped("invoice.pdf")  # 처리 Lambda를 아직 돌리지 않았다 (queued)
    status, body = get_documents("unknown")
    assert status == 200 and body["items"] == [] and sum(body["counts"].values()) == 0


def test_documents_pages_newest_first(fakes, lambda_client, classifier, monkeypatch):
    monkeypatch.setattr(handler, "DOC_PAGE", 1)
    times = iter([1795000000, 1795000600])
    monkeypatch.setattr(handler.time, "time", lambda: next(times, 1795000600))
    first, second = post_untyped("invoice.pdf"), post_untyped("invoice.pdf")
    process(lambda_client)

    page1 = get_documents("commercial_invoice")[1]
    page2 = get_documents("commercial_invoice", page1["next_cursor"])[1]
    assert [page1["items"][0]["job_id"], page2["items"][0]["job_id"]] == [second, first]
    assert page1["next_cursor"] == "1" and page2["next_cursor"] is None


def test_documents_old_job_without_files_uses_read_doc_type(fakes):
    """#143 전 작업은 files·created_at 칸이 없고, 종류를 정해 올려 분류 기록도 없다. 읽은 서류의 종류를 쓴다."""
    doc = ExtractedDocument(doc_type="commercial_invoice", file="uploads/old/invoice.pdf", doc_no=Cell(raw="INV-OLD", value="INV-OLD"))
    fakes.items["job-0000aaaa"] = {
        "job_id": "job-0000aaaa", "updated_at": 1795000000,
        "data": Job(job_id="job-0000aaaa", status="waiting_approval").model_dump_json(),
        "docs": handler._DOCS.dump_json([doc]).decode(),
    }
    body = get_documents("commercial_invoice")[1]
    [rec] = body["items"]
    assert (rec["file_name"], rec["classified_by"], rec["doc_no"]) == ("invoice.pdf", "user", "INV-OLD")
    assert body["counts"]["unknown"] == 0


@pytest.mark.parametrize(("doc_type", "cursor"), [(None, None), ("invoice", None), ("packing_list", "abc")])
def test_documents_bad_query_is_400(fakes, doc_type, cursor):
    assert get_documents(doc_type, cursor)[0] == 400


# ---------------------------------------------------------------------------
# POST /jobs/{id}/hs 뒤 자동 등록 재검사 (D2, agent-design.md 8번)
# ---------------------------------------------------------------------------
CHOOSE_1 = {"choices": [{"line": 1, "hs": "8507600000"}]}


def example_issue(grade: str) -> Issue:
    """예시 작업의 문제(X-WT-01)를 등급만 바꿔 쓴다."""
    [issue] = Job.model_validate(example("job_waiting_approval.json")).result.issues
    return issue.model_copy(update={"grade": grade})


def bl_doc() -> ExtractedDocument:
    return ExtractedDocument(doc_type="bill_of_lading", file="uploads/sample-001/bl.pdf", doc_no=Cell(raw=BL, value=BL))


def with_lines(docs: list[ExtractedDocument], lines) -> list[ExtractedDocument]:
    """예시 서류의 1행을 lines의 행마다 복사한다."""
    for doc in docs:
        [first] = doc.items
        doc.items = [first.model_copy(deep=True, update={"line": n}) for n in lines]
    return docs


def put_ready_job(table, *, lines=(1,), issues=(), docs=None):
    """lines의 품목이 모두 '사람 확인 필요'이고, 문제는 issues뿐인 작업. docs가 없으면 예시 서류 + 선하증권."""
    job = Job.model_validate({**example("job_waiting_approval.json"), "job_id": HS_JOB})
    [waiting] = job.result.hs
    job.result.issues = list(issues)
    job.result.hs = [waiting.model_copy(update={"line": n}) for n in lines]
    if docs is None:
        docs = with_lines(example_docs(), lines) + [bl_doc()]
    table.put_item(
        Item={
            "job_id": HS_JOB,
            "data": job.model_dump_json(by_alias=True),
            "updated_at": 0,
            "docs": json.dumps([d.model_dump(mode="json") for d in docs], ensure_ascii=False),
            "importer": IMPORTER,
        }
    )


def test_hs_choice_registers_to_wms_when_nothing_is_left(hs_fakes, wms_memory, shipments):
    """끝난 기준: '참고'만 남은 작업에서 마지막 품목의 HS를 고르면 승인 없이 바로 등록한다 (by=auto).
    화물 기록도 '수입신고'로 고친다 (E3)."""
    table, _, _ = hs_fakes
    put_ready_job(table, issues=[example_issue("참고")])
    shipments.rows[BL] = shipment(job_id=HS_JOB)

    status, body = call("POST", f"/jobs/{HS_JOB}/hs", CHOOSE_1)

    assert status == 200 and list(body) == ["declaration_draft"]  # 응답 모양은 약속 2 그대로
    [(wms_id, record)] = wms_memory.records.values()
    assert (record.idempotency_key, record.by, record.consignee) == (f"{BL}#{HS_JOB}", "auto", IMPORTER)
    assert [(row["line"], row["hs_code"]) for row in record.items] == [(1, "8507600000")]

    _, job = call("GET", f"/jobs/{HS_JOB}")
    Job.model_validate(job)
    assert job["status"] == "done"
    assert job["result"]["wms"] == {"status": "등록됨", "by": "auto", "wms_id": wms_id}
    assert job["steps"][-2] == {"tool": "push_to_wms", "summary": f"WMS 자동 등록: {wms_id}", "ok": True}
    assert job["steps"][-1] == {"tool": "mark_registered", "summary": f"화물 기록 B/L {BL}: 입항 → 수입신고", "ok": True}
    assert shipments.rows[BL].customs_status == "수입신고"
    # 등록이 끝난 작업은 HS를 다시 고를 수 없고, 승인을 눌러도 다시 등록하지 않는다 (D3)
    assert call("POST", f"/jobs/{HS_JOB}/hs", CHOOSE_1)[0] == 409
    assert call("POST", f"/jobs/{HS_JOB}/approve", {"approver": "김담당"}) == (
        200, {"wms": {"status": "등록됨", "wms_id": wms_id}},
    )
    assert len(wms_memory.records) == 1


@pytest.mark.parametrize("grade", ["불일치", "확인 필요"])
def test_hs_choice_with_problem_left_waits_for_approval(hs_fakes, wms_memory, grade):
    table, _, _ = hs_fakes
    put_ready_job(table, issues=[example_issue(grade)])

    assert call("POST", f"/jobs/{HS_JOB}/hs", CHOOSE_1)[0] == 200

    _, job = call("GET", f"/jobs/{HS_JOB}")
    assert job["status"] == "waiting_approval"
    assert job["result"]["wms"] == {"status": "승인 대기", "by": None, "wms_id": None}
    assert job["steps"][-1]["tool"] == "draft_declaration"
    assert wms_memory.records == {}


def test_hs_choice_registers_after_last_line(hs_fakes, wms_memory):
    """두 품목 중 하나만 고르면 기다리고, 남은 품목까지 고르면 그때 등록한다."""
    table, _, _ = hs_fakes
    put_ready_job(table, lines=(1, 2))

    assert call("POST", f"/jobs/{HS_JOB}/hs", CHOOSE_1)[0] == 200
    _, job = call("GET", f"/jobs/{HS_JOB}")
    assert (job["status"], job["result"]["wms"]["status"]) == ("waiting_approval", "승인 대기")
    assert wms_memory.records == {}

    assert call("POST", f"/jobs/{HS_JOB}/hs", {"choices": [{"line": 2, "hs": "8507800000"}]})[0] == 200
    _, job = call("GET", f"/jobs/{HS_JOB}")
    assert (job["status"], job["result"]["wms"]["status"], job["result"]["wms"]["by"]) == ("done", "등록됨", "auto")
    [(_, record)] = wms_memory.records.values()
    assert [(row["line"], row["hs_code"]) for row in record.items] == [(1, "8507600000"), (2, "8507800000")]


def pl_only_line_docs() -> list[ExtractedDocument]:
    """포장명세서에만 2행이 있다. finish_report는 상업송장 행에만 HS를 돌리므로 2행은 HS 결과가 없다."""
    pl, ci = example_docs()
    with_lines([pl], (1, 2))
    return [pl, ci, bl_doc()]


@pytest.mark.parametrize(
    "docs, words",
    [(example_docs(), "B/L 번호가 없어"), (pl_only_line_docs(), "2행은 HS 결과가 없습니다")],
    ids=["no-bl", "pl-only-line"],
)
def test_hs_choice_that_cannot_register_says_why(hs_fakes, wms_memory, docs, words):
    """조건은 채웠는데 등록하지 못하면 이유를 단계 기록에 실패로 남긴다. 승인 대기라 사람이 승인할 수 있다 (D3)."""
    table, _, _ = hs_fakes
    put_ready_job(table, docs=docs)

    assert call("POST", f"/jobs/{HS_JOB}/hs", CHOOSE_1)[0] == 200

    _, job = call("GET", f"/jobs/{HS_JOB}")
    assert (job["status"], job["result"]["wms"]["status"]) == ("waiting_approval", "승인 대기")
    last = job["steps"][-1]
    assert (last["tool"], last["ok"]) == ("push_to_wms", False) and words in last["summary"]
    assert wms_memory.records == {}


def test_wms_record_is_built_from_saved_hs(hs_fakes, monkeypatch):
    """HS 선택을 먼저 저장한 뒤 등록한다. WMS에 쓰는 순간 작업에는 이미 고른 HS가 저장돼 있다."""
    table, _, _ = hs_fakes
    seen = []

    class PeekingWms(MemoryWms):
        def register(self, record):
            seen.append(handler.load_job(HS_JOB).result.hs[0].hs_code)
            return super().register(record)

    monkeypatch.setattr(wms, "dynamo_wms", lambda: PeekingWms())
    put_ready_job(table)

    assert call("POST", f"/jobs/{HS_JOB}/hs", CHOOSE_1)[0] == 200
    assert seen == ["8507600000"]


def test_jobs_save_failure_after_registration_can_be_approved(hs_fakes, wms_memory, monkeypatch):
    """등록 뒤 작업 저장이 실패해도 HS 선택은 저장돼 있다. 승인하면 같은 기록·같은 wms_id로 끝난다."""
    table, _, _ = hs_fakes
    put_ready_job(table)
    real_put, writes = table.put_item, []

    def flaky_put(Item):
        writes.append(Item)
        if len(writes) == 2:  # HS 저장 다음, 등록 결과 저장
            raise RuntimeError("가짜 jobs 저장 오류")
        real_put(Item)

    monkeypatch.setattr(table, "put_item", flaky_put)

    assert call("POST", f"/jobs/{HS_JOB}/hs", CHOOSE_1)[0] == 500
    _, job = call("GET", f"/jobs/{HS_JOB}")
    assert (job["status"], job["result"]["wms"]["status"]) == ("waiting_approval", "승인 대기")
    assert job["result"]["hs"][0]["hs_code"] == "8507600000"
    [(wms_id, record)] = wms_memory.records.values()
    assert record.items[0]["hs_code"] == "8507600000"

    assert call("POST", f"/jobs/{HS_JOB}/approve", {"approver": "김담당"}) == (
        200, {"wms": {"status": "등록됨", "wms_id": wms_id}},
    )
    assert len(wms_memory.records) == 1


def test_wms_failure_still_saves_hs_choice(hs_fakes, monkeypatch):
    """가상 WMS가 실패해도 HS 선택·이력·초안은 저장하고 200이다. 승인 대기로 남아 사람이 승인한다 (D3)."""
    table, history, _ = hs_fakes

    class BrokenWms:
        def register(self, record):
            raise ClientError({"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "가짜"}}, "PutItem")

    monkeypatch.setattr(wms, "dynamo_wms", lambda: BrokenWms())
    put_ready_job(table)

    status, body = call("POST", f"/jobs/{HS_JOB}/hs", CHOOSE_1)

    assert status == 200
    _, job = call("GET", f"/jobs/{HS_JOB}")
    assert (job["status"], job["result"]["wms"]["status"]) == ("waiting_approval", "승인 대기")
    assert job["result"]["hs"][0]["status"] == "사람 확정"
    assert job["result"]["declaration_draft"] == body["declaration_draft"]
    assert history.rows == {(IMPORTER, "CI-BP-200"): ("8507600000", HS_JOB)}
    assert job["steps"][-1] == {
        "tool": "push_to_wms", "summary": "WMS 자동 등록 못 함: 가상 WMS 오류(ClientError). 승인하면 다시 등록합니다", "ok": False,
    }


# ---------------------------------------------------------------------------
# GET /jobs/{id}/files 서류 보기 (F7 #156)
# ---------------------------------------------------------------------------
from tools.models import JobFilesResponse  # noqa: E402


class ViewS3:
    """서류 보기용 가짜 S3. GET 서명과 이미지 앞부분 받기만 흉내 낸다."""

    def __init__(self, images: dict[str, bytes]):
        self.images, self.signed, self.ranges = images, [], []

    def generate_presigned_url(self, operation, Params, ExpiresIn, HttpMethod=None):
        self.signed.append((operation, Params, ExpiresIn))
        return f"https://s3.test/{Params['Key']}?sig={len(self.signed)}"

    def get_object(self, Bucket, Key, Range=None):
        from io import BytesIO

        self.ranges.append((Key, Range))
        return {"Body": BytesIO(self.images[Key])}


def _png(width: int, height: int) -> bytes:
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (width, height), "white").save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def view_s3(monkeypatch):
    fake = ViewS3({"uploads/s1/photo.png": _png(1200, 1600)})
    monkeypatch.setattr(handler, "_s3", lambda: fake)
    monkeypatch.setenv("DOCS_BUCKET", "team06-docs-test")
    return fake


def _typed_job(job_id: str, key: str, doc_type: str, status: str = "waiting_approval") -> dict:
    return {
        "job_id": job_id, "updated_at": 1795000000, "files": json.dumps([{"key": key, "doc_type": doc_type}]),
        "data": Job(job_id=job_id, status=status).model_dump_json(),
    }


def test_job_files_give_original_url_and_read_fields(fakes, lambda_client, classifier, view_s3):
    """끝난 기준: 원본 주소(미리 서명된 GET, inline)와 읽은 칸. 칸 경로는 IssueCell.field와 같다."""
    job_id = post_untyped("invoice.pdf", "packing_list.pdf")
    process(lambda_client)

    status, body = call("GET", f"/api/jobs/{job_id}/files")

    assert status == 200
    res = JobFilesResponse.model_validate(body)
    assert [f.file_name for f in res.files] == ["invoice.pdf", "packing_list.pdf"]
    inv = res.files[0]
    assert (inv.doc_type, inv.classified_by, inv.content_type) == ("commercial_invoice", "model", "application/pdf")
    assert inv.url.startswith("https://s3.test/uploads/s1/invoice.pdf") and inv.pages == [] and inv.marks == []
    fields = {f.field: f for f in inv.fields}
    assert fields["total_gross_kg"].raw == "6,250.00 KGS" and fields["total_gross_kg"].label == "총중량"
    assert fields["doc_no"].raw == "INV-2026-001"
    _, issue_job = call("GET", f"/api/jobs/{job_id}")
    issue_cells = {(c["doc"], c["field"]) for i in issue_job["result"]["issues"] for c in i["cells"]}
    shown = {(f.doc_type, r.field) for f in res.files for r in f.fields}
    assert issue_cells and issue_cells <= shown  # 화면이 불일치 칸을 바로 짚는다
    op, params, seconds = view_s3.signed[0]
    assert (op, seconds, params["ResponseContentDisposition"]) == ("get_object", handler.VIEW_SECONDS, "inline")


def test_job_files_image_has_one_page_with_size(fakes, view_s3):
    fakes.items["job-0000bbbb"] = _typed_job("job-0000bbbb", "uploads/s1/photo.png", "packing_list")

    [view] = JobFilesResponse.model_validate(call("GET", "/api/jobs/job-0000bbbb/files")[1]).files

    assert view.content_type == "image/png" and [(p.width, p.height) for p in view.pages] == [(1200, 1600)]
    assert view.fields == []  # 읽지 않은 서류
    assert view_s3.ranges == [("uploads/s1/photo.png", f"bytes=0-{handler.IMAGE_HEAD_BYTES - 1}")]


def test_job_files_broken_image_still_gives_url(fakes, view_s3):
    view_s3.images["uploads/s1/photo.png"] = b"not an image"
    fakes.items["job-0000cccc"] = _typed_job("job-0000cccc", "uploads/s1/photo.png", "packing_list", "done")

    [view] = call("GET", "/api/jobs/job-0000cccc/files")[1]["files"]

    assert view["pages"] == [] and view["url"].startswith("https://s3.test/")


@pytest.mark.parametrize("job_id", ["job-00000000", "nope"])
def test_job_files_unknown_job_is_404(fakes, job_id):
    assert call("GET", f"/api/jobs/{job_id}/files")[0] == 404


def test_presign_view_is_regional_get_with_inline(monkeypatch):
    """실제 botocore로 GET 서명만 해 본다 (AWS를 부르지 않는다)."""
    for name in ("AWS_PROFILE", "AWS_SESSION_TOKEN", "AWS_ENDPOINT_URL", "AWS_ENDPOINT_URL_S3"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "fake-id")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "fake-secret")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-northeast-2")
    monkeypatch.setenv("DOCS_BUCKET", "team06-docs-test")
    monkeypatch.setattr(boto3, "DEFAULT_SESSION", None)
    handler._s3.cache_clear()
    try:
        url = handler.presign_view("uploads/b1/1-invoice.pdf", "application/pdf")
    finally:
        handler._s3.cache_clear()
    parts, query = urlsplit(url), parse_qs(urlsplit(url).query)
    assert parts.netloc == "team06-docs-test.s3.ap-northeast-2.amazonaws.com"
    assert query["response-content-type"] == ["application/pdf"] and query["response-content-disposition"] == ["inline"]
    assert query["X-Amz-Expires"] == [str(handler.VIEW_SECONDS)]
