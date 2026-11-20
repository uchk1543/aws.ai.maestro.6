"""API Lambda team06-api 진입점 (API Gateway HTTP API, 이벤트 형식 2.0). 담당: 서버. 형식: docs/schema.md 약속 2

CloudFront가 /api/*를 API Gateway로 보내고, rawPath에 /api가 붙어 온다 (/api/jobs). 앞의 /api를 떼고 나눈다.
옮기는 동안 /api 없는 경로(/jobs)도 같은 곳으로 간다.
    GET  /api/               → {"ok": true}            (배포 확인)
    POST /api/uploads        → {"uploads"}             (F2, 파일마다 S3에 직접 PUT할 미리 서명된 URL)
    POST /api/jobs           → {"job_id"}              (F3, queued로 저장하고 처리 Lambda를 비동기로 부른 뒤 바로 응답)
    GET  /api/jobs/{id}      → Job                     (화면이 2초마다)
    POST /api/jobs/{id}/hs   → {"declaration_draft"}   (C3, 사람이 고른 HS 반영. D2: 조건을 채우면 WMS 자동 등록)
    POST /api/jobs/{id}/approve → {"wms"}              (D3, 사람 승인으로 WMS 등록. 불일치가 남았으면 409)
    POST /api/chat           → ChatResponse            (E5, 현황 조회. 1번 agent.query_agent)
    GET  /api/documents?doc_type=…&cursor=… → DocumentsResponse (G10 #143, 문서 분류 내역. team06-jobs Scan)
         거르기(F11 #195): job_status · grade · rule_id · hs=pending
    GET  /api/stats           → StatsResponse          (F11 #195, 대시보드 통계. team06-jobs·team06-shipments Scan)
    GET  /api/jobs/{id}/files → JobFilesResponse        (F7 #156, 서류 보기: 원본 주소 + 읽은 칸)
서류 처리(run_job)는 처리 Lambda team06-worker(api/worker.py)가 한다. API Gateway는 요청 하나를 30초 안에 끝내야 한다.

환경 변수: JOBS_TABLE(team06-jobs), DOCS_BUCKET(team06-docs-...), MODEL_ID, HS_HISTORY_TABLE(team06-hs-history),
WMS_TABLE(team06-wms), SHIPMENTS_TABLE(team06-shipments), WORKER_FUNCTION(team06-worker, API Lambda에만)
"""

import base64
import json
import os
import re
import time
import unicodedata
import uuid
from functools import cache

from botocore.exceptions import BotoCoreError, ClientError
from pydantic import TypeAdapter

from tools import declaration, hs, report, wms
from tools.models import (
    DOC_TYPE_KO,
    Cell,
    DeclarationDraft,
    DocPage,
    DocType,
    DocumentRecord,
    DocumentsResponse,
    ExtractedDocument,
    ExtractedItem,
    Job,
    JobFilesResponse,
    JobFileView,
    AutoRate,
    DelayedShipment,
    FlowStage,
    OcrResult,
    RuleCount,
    StatsResponse,
    TodoCounts,
    ReadField,
    Step,
    WmsState,
)
from tools.ocr import locate_marks
from tools.query import DELAY_RULE, dynamo_shipments, is_delayed

ALLOWED_DOC_TYPES = {"commercial_invoice", "packing_list", "bill_of_lading", "certificate_of_origin"}  # 약속 1의 4종 (#129)
JOB_ID = re.compile(r"^job-[0-9a-f]{8}$")
HS_CODE = re.compile(r"^[0-9]{10}$")  # 10자리 HSK
APPROVER_MAX = 50  # 승인자 이름 길이. 화면 입력칸(WmsPanel maxLength)과 같다
KEY_PREFIX = "uploads/"
API_PREFIX = "/api"  # CloudFront → API Gateway가 rawPath 앞에 붙여 보낸다
# 올릴 수 있는 형식 (화면 web/src/pages/UploadPage.tsx ACCEPT와 같다). 읽기(tools/extract.py)는 확장자로 PDF·이미지를 가른다
UPLOAD_TYPES = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
UNKNOWN_TYPE = "application/octet-stream"  # 브라우저가 type을 모를 때 화면이 보내는 값 (web/src/api.ts contentTypeOf)
UPLOAD_SECONDS = 300  # 미리 서명된 URL 유효 시간. 약속 2 "몇 분 뒤 만료"
NAME_MAX = 80  # S3 키에 넣는 파일 이름(확장자 뺀) 길이
_DOCS = TypeAdapter(list[ExtractedDocument])


# ---------------------------------------------------------------------------
# AWS 자원 (테스트에서 바꿔 끼운다)
# ---------------------------------------------------------------------------
@cache
def _table():
    import boto3

    return boto3.resource("dynamodb").Table(os.environ["JOBS_TABLE"])


@cache
def _s3():
    import boto3
    from botocore.config import Config

    # s3v4 + virtual: 미리 서명된 URL이 지역 주소(<버킷>.s3.ap-northeast-2.amazonaws.com)로 나온다.
    # 기본값은 전역 주소(<버킷>.s3.amazonaws.com)라 새 버킷이면 307로 돌려보내고, 브라우저의 CORS 사전 요청이 실패한다.
    config = Config(
        signature_version="s3v4",
        s3={"addressing_style": "virtual"},
        connect_timeout=5,
        read_timeout=5,
        retries={"max_attempts": 2},
    )
    return boto3.client("s3", config=config)


@cache
def _lambda():
    import boto3
    from botocore.config import Config

    return boto3.client("lambda", config=Config(connect_timeout=5, read_timeout=5, retries={"max_attempts": 2}))


def fetch_object(key: str) -> bytes:
    """DOCS_BUCKET에서 파일을 받는다."""
    print(f"[tool] s3_get key={key}")
    return _s3().get_object(Bucket=os.environ["DOCS_BUCKET"], Key=key)["Body"].read()


def store_object(key: str, data: bytes, content_type: str) -> None:
    """DOCS_BUCKET에 파일을 쓴다. 처리 Lambda가 PDF 쪽 그림(uploads/…pN.jpg)을 둘 때 쓴다 (F10 #188). 권한: uploads/* PutObject."""
    print(f"[tool] s3_put key={key} bytes={len(data)}")
    _s3().put_object(Bucket=os.environ["DOCS_BUCKET"], Key=key, Body=data, ContentType=content_type)


def presign_upload(key: str, content_type: str) -> str:
    """DOCS_BUCKET의 key에 PUT할 미리 서명된 URL을 만든다. S3를 부르지 않고 서명만 한다.

    언제: POST /uploads에서 파일마다.
    받는 것: key(uploads/로 시작), content_type. content-type도 서명에 들어가서, PUT할 때 같은 헤더를 보내야 한다.
    반환: UPLOAD_SECONDS초 동안 쓸 수 있는 URL. URL에 서명이 들어 있어 로그에는 남기지 않는다.
    """
    print(f"[tool] s3_presign_put key={key} content_type={content_type}")
    return _s3().generate_presigned_url(
        "put_object",
        Params={"Bucket": os.environ["DOCS_BUCKET"], "Key": key, "ContentType": content_type},
        ExpiresIn=UPLOAD_SECONDS,
        HttpMethod="PUT",
    )


def invoke_worker(job_id: str, files: list[dict]) -> None:
    """처리 Lambda(WORKER_FUNCTION)를 비동기로 부른다. 기다리지 않는다.

    언제: POST /jobs가 작업을 queued로 저장한 직후 (F3).
    받는 것: job_id, files([{"key", "doc_type"}], 검사를 마친 값). 처리 Lambda가 받는 이벤트가 이 둘이다 (#36 약속).
    반환: 없음. Lambda가 이벤트를 받지 않았으면(202가 아니면) RuntimeError, 호출 오류는 botocore 예외를 그대로 낸다.
    """
    function = os.environ["WORKER_FUNCTION"]
    print(f"[api] invoke_worker function={function} job={job_id} files={len(files)}")
    res = _lambda().invoke(
        FunctionName=function,
        InvocationType="Event",
        Payload=json.dumps({"job_id": job_id, "files": files}, ensure_ascii=False).encode("utf-8"),
    )
    if res.get("StatusCode") != 202:
        raise RuntimeError(f"처리 Lambda가 이벤트를 받지 않았습니다 (StatusCode={res.get('StatusCode')})")


def save_job(job: Job, keep: dict | None = None) -> None:
    """Job을 JSON 문자열 한 칸으로 저장한다 (float → Decimal 변환 문제를 피함).

    keep: 같은 줄에서 그대로 둘 다른 칸(docs·importer 등). 주면 data·updated_at만 바꿔 쓴다.
    """
    _table().put_item(
        Item={
            **(keep or {}),
            "job_id": job.job_id,
            "data": job.model_dump_json(by_alias=True),
            "updated_at": int(time.time()),
        }
    )


def _load_item(job_id: str) -> dict | None:
    return _table().get_item(Key={"job_id": job_id}).get("Item")


def load_job(job_id: str) -> Job | None:
    item = _load_item(job_id)
    return Job.model_validate_json(item["data"]) if item else None


def load_job_docs(item: dict) -> tuple[list[ExtractedDocument], str | None] | None:
    """HS를 다시 반영하거나 승인할 때 쓸 읽은 서류와 수입자. 서류 기록이 없으면 None.

    언제: POST /jobs/{id}/hs·/approve. 모델을 다시 부르지 않으려고 저장해 둔 값을 쓴다 (agent-design.md 6번).
    받는 것: team06-jobs의 한 줄. docs 칸(ExtractedDocument 목록 JSON)과 importer 칸(수입자)을 읽는다.
      두 칸은 처리 Lambda(api/worker.py)가 마지막 저장 때 쓴다 (#122).
    반환: (서류 목록, 수입자). docs 칸이 없으면 None. importer 칸이 없으면 수입자는 None이다
      (상업송장 consignee_name을 못 읽었을 때. 그 칸은 #110이 약속 1에 더하기 전까지 없다).
    """
    raw_docs, importer = item.get("docs"), item.get("importer")
    if not raw_docs:
        return None
    return _DOCS.validate_json(raw_docs), importer or None


class DynamoHSHistory:
    """tools.hs.HSHistory의 DynamoDB판 (team06-hs-history). 키: importer(파티션) + item_key(정렬)."""

    def __init__(self, table):
        self.table = table

    def get(self, importer: str, item_key: str) -> str | None:
        item = self.table.get_item(Key={"importer": importer, "item_key": item_key}).get("Item")
        return item["hs"] if item else None

    def put(self, importer: str, item_key: str, hs: str, job_id: str) -> None:
        self.table.put_item(
            Item={"importer": importer, "item_key": item_key, "hs": hs, "job_id": job_id, "updated_at": int(time.time())}
        )


def _mark_registered(job_id: str, bl_no: str) -> Step:
    """WMS에 등록된 뒤 그 작업의 화물 기록 상태를 '수입신고'로 고치고 단계 한 줄을 돌려준다 (E3, report.mark_registered).

    언제: 사람 승인(D3)이나 HS 선택 뒤 자동 등록(D2)으로 push_to_wms가 성공한 뒤, save_job 전.
      처리 직후 자동 등록(#154)은 화물 기록을 처음부터 '수입신고'로 써서(record_shipment registered) 이 함수를 부르지 않는다.
    반환: Step. 예외를 내지 않는다. 저장소를 못 만들어도(SHIPMENTS_TABLE 없음 등) ok=False 한 줄만 남기고,
      WMS 등록 결과는 그대로 저장한다.
    """
    try:
        store = dynamo_shipments()
    except Exception as exc:
        print(f"[error] {report.REGISTER_TOOL} job={job_id} {type(exc).__name__}: {exc}")
        return Step(tool=report.REGISTER_TOOL, summary=f"화물 기록 상태를 고치지 못함: {type(exc).__name__}", ok=False)
    return report.mark_registered(job_id, bl_no, store)


@cache
def _hs_history() -> DynamoHSHistory:
    import boto3
    from botocore.config import Config

    config = Config(connect_timeout=5, read_timeout=5, retries={"max_attempts": 2})
    return DynamoHSHistory(boto3.resource("dynamodb", config=config).Table(os.environ["HS_HISTORY_TABLE"]))


@cache
def _hs_table() -> hs.CsvHSTable:
    """HS부호 표(data/hs/hs_codes.csv). Lambda 실행 환경마다 처음 한 번만 읽는다 (처리 Lambda와 같은 zip에 들어 있다)."""
    return hs.load_hs_table()


def _hs_known(code: str) -> bool:
    """사람이 고른 HS가 HS부호 표에 있는 10자리 코드인지 본다 (#181).

    언제: POST /jobs/{id}/hs에서 이력을 쓰기 전. 표에 없는 코드가 신고서 초안과 확정 이력에 들어가지 않게 한다.
    받는 것: code(고른 코드). 반환: 10자리 ASCII 숫자이고 표에 있으면 True.
    표 확인은 tools/hs.py의 is_known_hs(#164)가 한다. 형식은 _validate_choices가 먼저 보지만 여기서도 한 번 더 본다.
    """
    return hs.is_known_hs(code, _hs_table())


# ---------------------------------------------------------------------------
# 응답
# ---------------------------------------------------------------------------
def _response(status: int, body) -> dict:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json; charset=utf-8"},
        "body": json.dumps(body, ensure_ascii=False),
    }


def _error(status: int, message: str) -> dict:
    return _response(status, {"error": message})


def _body(event: dict):
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    return json.loads(raw) if raw else {}


def _safe_name(name: str) -> str | None:
    """화면이 보낸 파일 이름을 S3 키에 넣을 이름으로 바꾼다. 올릴 수 없는 형식이면 None.

    경로(/, \\)는 버리고, 글자·숫자·_·- 밖의 문자는 _로 바꾼다. 한글은 남긴다 (단계 기록에 파일 이름이 보인다).
    점도 바뀌므로 '..'이 남지 않는다 (POST /jobs의 key 검사). 확장자는 소문자로 둔다.
    """
    base = re.split(r"[\\/]", unicodedata.normalize("NFC", name))[-1].strip()
    stem, suffix = os.path.splitext(base)
    suffix = suffix.lower()
    if suffix not in UPLOAD_TYPES:
        return None
    stem = re.sub(r"[^\w-]+", "_", stem).strip("_")[:NAME_MAX] or "file"
    return stem + suffix


def _validate_uploads(body) -> tuple[list[tuple[str, str]] | None, str | None]:
    """POST /uploads 요청 검사. ([(키에 넣을 파일 이름, content_type)], 오류 메시지)"""
    files = body.get("files") if isinstance(body, dict) else None
    if not isinstance(files, list) or not files:
        return None, "files 목록이 비어 있습니다"
    from agent.document_agent import MAX_FILES

    if len(files) > MAX_FILES:
        return None, f"서류는 한 번에 {MAX_FILES}개까지입니다"
    clean = []
    for f in files:
        name = f.get("name") if isinstance(f, dict) else None
        content_type = f.get("content_type") if isinstance(f, dict) else None
        if not isinstance(name, str) or not name.strip():
            return None, "name(파일 이름)이 필요합니다"
        safe = _safe_name(name)
        if safe is None:
            return None, f"PDF, PNG, JPG만 올릴 수 있습니다 ({name[:NAME_MAX]})"
        expected = UPLOAD_TYPES[os.path.splitext(safe)[1]]
        if content_type not in (expected, UNKNOWN_TYPE):
            return None, f"{safe}의 content_type은 {expected}여야 합니다"
        clean.append((safe, content_type))
    return clean, None


def _validate_files(body) -> tuple[list[dict] | None, str | None]:
    """POST /jobs 요청 검사. (files, 오류 메시지)"""
    files = body.get("files") if isinstance(body, dict) else None
    if not isinstance(files, list) or not files:
        return None, "files 목록이 비어 있습니다"
    from agent.document_agent import MAX_FILES

    if len(files) > MAX_FILES:
        return None, f"서류는 한 번에 {MAX_FILES}개까지입니다"
    clean = []
    for f in files:
        key = f.get("key") if isinstance(f, dict) else None
        doc_type = f.get("doc_type") if isinstance(f, dict) else None
        if not isinstance(key, str) or not key.startswith(KEY_PREFIX) or ".." in key:
            return None, f"key는 '{KEY_PREFIX}'로 시작해야 합니다"
        # doc_type 칸은 꼭 있어야 하고, 값이 null이면 run_job이 classify_document로 분류한다 (B1·B9).
        # 화면(G9)은 늘 null을 보낸다 (#129)
        if "doc_type" not in f:
            return None, "doc_type 칸이 필요합니다 (모르면 null)"
        if doc_type is not None and doc_type not in ALLOWED_DOC_TYPES:
            return None, f"doc_type은 null이거나 {sorted(ALLOWED_DOC_TYPES)} 중 하나입니다"
        clean.append({"key": key, "doc_type": doc_type})
    return clean, None


def _validate_choices(body, lines: set[int]) -> tuple[dict[int, str] | None, str | None]:
    """POST /jobs/{id}/hs 요청 검사. lines: 이 작업의 HS 결과에 있는 품목 행. ({행: HS}, 오류 메시지)"""
    choices = body.get("choices") if isinstance(body, dict) else None
    if not isinstance(choices, list) or not choices:
        return None, "choices 목록이 비어 있습니다"
    picked: dict[int, str] = {}
    for c in choices:
        line = c.get("line") if isinstance(c, dict) else None
        code = c.get("hs") if isinstance(c, dict) else None
        if not isinstance(line, int) or isinstance(line, bool) or line not in lines:
            return None, f"line은 이 작업의 품목 행 {sorted(lines)} 중 하나입니다"
        if line in picked:
            return None, f"{line}행을 두 번 골랐습니다"
        if not isinstance(code, str) or not HS_CODE.match(code):
            return None, "hs는 숫자 10자리입니다 (예: 8507600000)"
        picked[line] = code
    return picked, None


def _validate_approver(body) -> tuple[str | None, str | None]:
    """POST /jobs/{id}/approve 요청 검사. 공백을 한 칸으로 줄인 승인자 이름. (승인자, 오류 메시지)"""
    approver = body.get("approver") if isinstance(body, dict) else None
    if not isinstance(approver, str) or not approver.strip():
        return None, "approver(승인자 이름)가 필요합니다"
    approver = " ".join(approver.split())
    if len(approver) > APPROVER_MAX:
        return None, f"approver는 {APPROVER_MAX}자까지입니다"
    return approver, None


def _line_doc(docs: list[ExtractedDocument], line: int) -> ExtractedDocument | None:
    """확정 이력 키를 만들 서류. 그 행이 있는 상업송장을 먼저, 없으면 그 행이 있는 첫 서류."""
    having = [d for d in docs if any(i.line == line for i in d.items)]
    return next((d for d in having if d.doc_type == "commercial_invoice"), having[0] if having else None)


# ---------------------------------------------------------------------------
# 경로
# ---------------------------------------------------------------------------
def create_uploads(body) -> dict:
    """POST /uploads. 파일마다 화면이 S3에 직접 PUT할 미리 서명된 URL을 준다 (F2).

    언제: 업로드 화면(G2)에서 '업로드'를 누를 때. 화면은 받은 url로 파일을 PUT한 뒤 key로 POST /jobs를 부른다.
      파일이 API를 거치지 않아 API Gateway·Lambda 요청 크기 한도에 걸리지 않는다.
    받는 것: {"files": [{"name", "content_type"}]}. PDF·PNG·JPG, 10개까지.
      content_type은 확장자에 맞는 값이거나 application/octet-stream. PUT할 때 같은 content-type 헤더를 보내야 한다.
    반환: 200 {"uploads": [{"key", "url"}]} (요청 순서대로) / 400 요청 형식.
      key는 uploads/<묶음 ID>/<순번>-<파일 이름>이라 같은 이름을 여러 번 올려도 겹치지 않는다. url은 UPLOAD_SECONDS초 뒤 만료.
    """
    files, problem = _validate_uploads(body)
    if problem:
        return _error(400, problem)
    batch = uuid.uuid4().hex
    uploads = []
    for n, (name, content_type) in enumerate(files, start=1):
        key = f"{KEY_PREFIX}{batch}/{n}-{name}"
        uploads.append({"key": key, "url": presign_upload(key, content_type)})
    print(f"[api] uploads batch={batch} files={len(uploads)}")
    return _response(200, {"uploads": uploads})


def create_job(body) -> dict:
    """POST /jobs. 작업을 queued로 저장하고 처리 Lambda를 비동기로 부른 뒤 job_id를 바로 돌려준다 (F3).

    언제: 화면이 서류를 S3에 올린 뒤. 서류 처리는 처리 Lambda(api/worker.py)가 하고, 화면은 GET /jobs/{id}로 진행을 본다.
    받는 것: {"files": [{"key", "doc_type"}]}.
    반환: 200 {"job_id"} / 400 요청 형식 / 502 처리 Lambda를 부르지 못함 (작업은 failed로 남긴다).
    """
    files, problem = _validate_files(body)
    if problem:
        return _error(400, problem)

    job_id = f"job-{uuid.uuid4().hex[:8]}"
    # files·created_at은 문서 분류 내역(GET /documents, #143)이 읽는다. 처리 Lambda는 keep으로 그대로 둔다
    columns = {"files": json.dumps(files, ensure_ascii=False), "created_at": int(time.time())}
    save_job(Job(job_id=job_id, status="queued"), keep=columns)  # 처리 Lambda보다 먼저 저장해야 바로 오는 GET이 작업을 찾는다
    try:
        invoke_worker(job_id, files)
    except Exception as exc:  # 권한·이름·제한 오류. queued로 두면 화면이 끝없이 기다리므로 failed로 바꾼다
        print(f"[error] invoke_worker job={job_id} {type(exc).__name__}: {exc}")
        save_job(Job(job_id=job_id, status="failed", error=f"처리를 시작하지 못했습니다 ({type(exc).__name__})"), keep=columns)
        return _error(502, "서류 처리를 시작하지 못했습니다. 잠시 뒤 다시 올려 주세요")
    print(f"[job] {job_id} status=queued files={len(files)}")
    return _response(200, {"job_id": job_id})


def get_job(job_id: str) -> dict:
    if not JOB_ID.match(job_id):
        return _error(404, "작업을 찾을 수 없습니다")
    job = load_job(job_id)
    if job is None:
        return _error(404, "작업을 찾을 수 없습니다")
    return _response(200, job.model_dump(mode="json", by_alias=True))


def choose_hs(job_id: str, body) -> dict:
    """POST /jobs/{id}/hs. 사람이 고른 HS로 확정하고, 확정 이력에 저장하고, 신고서 초안을 다시 채운다.
    그다음 자동 등록 조건을 다시 검사해, 다 채우면 바로 가상 WMS에 등록하고(by=auto) 작업을 done으로 끝낸다 (D2).
    등록하면 화물 기록 상태도 '수입신고'로 고친다 (E3).

    언제: 화면에서 '사람 확인 필요' 품목의 HS를 고른 뒤 (agent-design.md 6·8번). 모델 호출 없음.
    받는 것: {"choices": [{"line", "hs"}]}. line은 이 작업의 HS 결과에 있는 행, hs는 HS부호 표에 있는 10자리.
      후보 3개 밖의 코드도 표에 있으면 받고, 단계 기록에 '후보 밖에서 직접 입력'을 남긴다 (#181).
    반환: 200 {"declaration_draft"} / 400 요청 형식, HS부호 표에 없는 코드 / 404 없는 작업
      / 409 처리 중, 서류 기록이 없음, 수입자를 몰라 확정 이력을 남길 수 없음.
      WMS 상태는 GET /jobs/{id}의 result.wms로 본다. 등록을 못 해도(조건 미달, B/L 없음, 저장소 오류)
      HS 선택은 저장하고 200이다. 그때는 승인 대기로 남아 사람이 승인한다 (D3).
    """
    if not JOB_ID.match(job_id):
        return _error(404, "작업을 찾을 수 없습니다")
    item = _load_item(job_id)
    if item is None:
        return _error(404, "작업을 찾을 수 없습니다")
    job = Job.model_validate_json(item["data"])
    if job.status != "waiting_approval" or job.result is None:
        return _error(409, f"HS는 승인 대기 중인 작업에서만 고를 수 있습니다 (지금: {job.status})")
    results = {r.line: r for r in job.result.hs}
    picked, problem = _validate_choices(body, set(results))
    if problem:
        return _error(400, problem)
    unknown = [f"{line}행 {code}" for line, code in picked.items() if not _hs_known(code)]
    if unknown:  # 표에 없는 코드는 신고서·이력에 넣지 않는다 (#181)
        return _error(400, f"HS부호 표에 없는 코드입니다: {', '.join(unknown)}. 10자리 HSK를 확인해 주세요")
    context = load_job_docs(item)
    if context is None:
        return _error(409, "이 작업에는 저장된 서류 기록이 없어 신고서 초안을 다시 채울 수 없습니다")
    docs, importer = context
    if importer is None:  # 확정 이력 키가 수입자 + 품목이라 수입자 없이는 남길 수 없다
        return _error(409, "상업송장에서 수입자(Consignee)를 읽지 못해 HS를 확정할 수 없습니다")
    line_docs = {line: _line_doc(docs, line) for line in picked}
    missing = sorted(line for line, doc in line_docs.items() if doc is None)
    if missing:
        return _error(409, f"서류 기록에 {missing}행이 없습니다")

    # 후보 3개 밖에서 직접 넣은 코드는 단계 기록에 남긴다 (#181). 확정하면 후보가 바뀔 수 있어 먼저 본다
    outside = {line for line, code in picked.items() if code not in {c.hs for c in results[line].candidates}}

    # 모두 검사한 뒤에 이력을 쓴다 (요청이 틀렸는데 이력만 남는 일을 막는다)
    history = _hs_history()
    for line, code in picked.items():
        print(f"[api] confirm_by_human job={job_id} line={line} hs={code}")
        key = hs.item_key(line_docs[line], line)
        results[line] = hs.confirm_by_human(results[line], code, importer, key, job_id, history=history)
    job.result.hs = [results[r.line] for r in job.result.hs]
    draft = declaration.draft_declaration(docs, job.result.issues, job.result.hs)
    job.result.declaration_draft = draft
    chosen = ", ".join(
        f"{line}행 {code}" + (" (후보 밖에서 직접 입력)" if line in outside else "") for line, code in picked.items()
    )
    job.steps.append(Step(tool="confirm_by_human", summary=f"사람 확정: {chosen}", ok=True))
    job.steps.append(draft_step(draft))

    # HS 선택을 먼저 저장한다. WMS 기록은 같은 멱등 키면 처음 것만 남으므로, 저장된 HS로만 만든다
    save_job(job, keep=item)

    # 자동 등록 재검사 (D2, agent-design.md 8번). 등록 실패는 예외로 오지 않고 단계 기록에 남는다
    before = (job.result.wms, len(job.steps))
    if auto_register(job, docs, importer):
        job.steps.append(_mark_registered(job_id, wms._bl_no(docs)))  # 등록됐으니 B/L 번호는 하나다
    if (job.result.wms, len(job.steps)) != before:
        save_job(job, keep=item)
    return _response(200, {"declaration_draft": draft.model_dump(mode="json")})


def draft_step(draft: DeclarationDraft) -> Step:
    """신고서 초안을 채운 단계 한 줄. HS 선택(choose_hs)과 처리 Lambda(처리 직후 초안, #154)가 같은 글로 남긴다."""
    return Step(
        tool="draft_declaration", summary=f"신고서 초안 {len(draft.fields)}칸, 비운 칸 {len(draft.blank_fields)}개", ok=True
    )


def auto_register(job: Job, docs: list[ExtractedDocument], importer: str | None) -> bool:
    """자동 등록 조건(D2, agent-design.md 8번)을 검사해, 다 채우면 가상 WMS에 등록하고 그 결과를 job에 넣는다.

    언제: HS 선택을 저장한 뒤(choose_hs), 처리 Lambda가 done으로 끝난 작업을 마지막으로 저장하기 전(#154).
    받는 것: job(result가 있는 작업. 그 자리에서 고친다), docs(읽은 서류), importer(수입자. 모르면 None).
    반환: 이번에 새로 등록했으면 True. 화물 기록 상태(E3)는 부르는 쪽이 고친다.
      고치는 것: result.wms = 등록됨(by=auto) 또는 승인 대기. 새로 등록했으면 status = done과 push_to_wms 한 줄.
      조건은 채웠는데 못 했으면(B/L·수입자 없음, 가상 WMS 오류 등) push_to_wms ok=False 한 줄로 이유를 남긴다.
      조건 미달(문제가 남음, HS 대기)은 정상 흐름이라 단계를 더하지 않는다. 예외는 올리지 않는다 (wms.register_if_ready).
    """
    before = job.result.wms
    state, reason = wms.register_if_ready(job.job_id, docs, job.result, importer or "")
    job.result.wms = state
    if state.status == "등록됨" and (before is None or before.status != "등록됨"):
        job.status = "done"  # 사람이 승인할 것이 남지 않았다 (D3 승인과 같다). HS를 다시 고르면 409
        job.steps.append(Step(tool="push_to_wms", summary=f"WMS 자동 등록: {state.wms_id}", ok=True))
        return True
    if reason:
        job.steps.append(Step(tool="push_to_wms", summary=f"WMS 자동 등록 못 함: {reason}", ok=False))
    return False


def _wms_body(state: WmsState) -> dict:
    """승인 응답 (약속 2). by는 넣지 않는다. 화면은 GET /jobs/{id}의 result.wms에서 by를 읽는다."""
    return {"wms": {"status": state.status, "wms_id": state.wms_id}}


def approve_job(job_id: str, body) -> dict:
    """POST /jobs/{id}/approve. 사람이 승인하면 가상 WMS에 등록하고(by=human) 작업을 끝낸다.

    언제: '확인 필요'가 남은 건을 사람이 화면에서 보고 승인할 때 (agent-design.md 8번 예외). 모델 호출 없음.
    받는 것: {"approver"}: 승인자 이름. 공백만이면 안 되고 50자까지. 단계 기록에 남긴다.
    반환: 200 {"wms": {"status", "wms_id"}} / 400 요청 형식 / 404 없는 작업
      / 409 {"error"}: 불일치가 남음, 승인 대기 중이 아님, 서류 기록이 없음, B/L 번호·수하인이 없어 기록을 못 만듦,
        같은 B/L이 다른 작업으로 이미 등록됨(#176. 이때만 단계 기록에 이유를 한 줄 남긴다. 같은 이유면 다시 남기지 않는다)
      / 502 가상 WMS 저장 실패 (작업은 그대로라 다시 승인하면 된다).
    이미 등록된 작업이면 다시 등록하지 않고 그 상태를 돌려준다. WMS 쪽도 멱등 키라 재시도해도 한 번만 들어간다.
    저장: result.wms = {등록됨, human, wms_id}, status = done, steps에 push_to_wms 한 줄과 mark_registered 한 줄(E3).
      화면은 승인 뒤 GET /jobs/{id}를 다시 불러 result.wms(by 포함)를 쓴다.
    """
    if not JOB_ID.match(job_id):
        return _error(404, "작업을 찾을 수 없습니다")
    item = _load_item(job_id)
    if item is None:
        return _error(404, "작업을 찾을 수 없습니다")
    approver, problem = _validate_approver(body)
    if problem:
        return _error(400, problem)
    job = Job.model_validate_json(item["data"])
    if job.result is not None and job.result.wms is not None and job.result.wms.status == "등록됨":
        return _response(200, _wms_body(job.result.wms))
    if job.status != "waiting_approval" or job.result is None:
        return _error(409, f"승인은 승인 대기 중인 작업에서만 할 수 있습니다 (지금: {job.status})")
    try:
        wms.approve(job.result, "human")
    except wms.ApprovalRefused as exc:
        return _error(409, str(exc))
    context = load_job_docs(item)
    if context is None:
        return _error(409, "이 작업에는 저장된 서류 기록이 없어 WMS에 올릴 기록을 만들 수 없습니다")
    docs, importer = context
    try:  # 수입자를 모르면 make_record가 '수하인(수입자)이 비어 있어' RecordNotReady를 낸다
        record = wms.make_record(job_id, docs, job.result.hs, importer or "", "human")
    except wms.RecordNotReady as exc:
        return _error(409, str(exc))

    print(f"[api] approve job={job_id}")
    try:
        state = wms.push_to_wms(record, adapter=wms.dynamo_wms())
    except wms.DuplicateBL as exc:  # 같은 B/L이 다른 작업으로 이미 있다 (#176). 작업은 승인 대기 그대로, 이유만 남긴다
        reason = str(exc)
        print(f"[api] approve job={job_id} 등록 안 함: {reason}")
        # 막힌 승인을 다시 눌러도 같은 이유면 단계 기록에는 한 줄만 둔다 (승인자가 달라도). 409는 매번 돌려준다
        if not any(s.tool == "push_to_wms" and not s.ok and s.summary.endswith(reason) for s in job.steps):
            job.steps.append(Step(tool="push_to_wms", summary=f"사람 승인({approver}) 했지만 WMS에 등록하지 않음: {reason}", ok=False))
            save_job(job, keep=item)
        return _error(409, reason)
    except (BotoCoreError, ClientError) as exc:
        print(f"[error] WMS 등록 실패 job={job_id} {type(exc).__name__}: {exc}")
        return _error(502, "가상 WMS에 등록하지 못했습니다. 잠시 뒤 다시 승인해 주세요 (같은 건은 한 번만 들어갑니다)")
    job.result.wms = state
    job.status = "done"
    job.steps.append(Step(tool="push_to_wms", summary=f"사람 승인({approver})으로 WMS 등록: {state.wms_id}", ok=True))
    job.steps.append(_mark_registered(job_id, record.bl_no))
    save_job(job, keep=item)
    return _response(200, _wms_body(state))


MAX_QUESTION = 500  # 현황 질문 길이 한도


def chat(body) -> dict:
    """POST /chat. 현황 질문에 답한다 (E5, 1번 agent.query_agent). 형식: docs/examples/chat_response.json

    받는 것: {"session_id", "message"}. message는 비지 않은 글자 500자까지, session_id는 글자(없으면 '-').
    반환: 200 ChatResponse / 400 요청 형식. 조회·건수는 코드가 하고 모델은 질문을 조건으로만 바꾼다.
    """
    message = body.get("message") if isinstance(body, dict) else None
    session_id = body.get("session_id") if isinstance(body, dict) else None
    if not isinstance(message, str) or not message.strip():
        return _error(400, "message가 비어 있습니다")
    if len(message) > MAX_QUESTION:
        return _error(400, f"message는 {MAX_QUESTION}자까지입니다")
    if session_id is not None and not isinstance(session_id, str):
        return _error(400, "session_id는 글자입니다")
    from agent.query_agent import answer
    from tools.query import dynamo_shipments

    res = answer(message.strip(), session_id or "-", store=dynamo_shipments())
    return _response(200, res.model_dump(mode="json", by_alias=True))


# ---------------------------------------------------------------------------
# 문서 분류 내역 (G10 #143)
# ---------------------------------------------------------------------------
LIST_DOC_TYPES = (*sorted(ALLOWED_DOC_TYPES), "unknown")  # 화면의 종류 칩. unknown = 분류 못 함·분류 실패
DOC_PAGE = 50  # 한 쪽 서류 수
_KO_TO_TYPE = {ko: t for t, ko in DOC_TYPE_KO.items()}
# 단계 기록 문장. agent/document_agent.py의 classify_document 기록과 같은 형식이다 (test_handler가 실제 run_job 출력으로 지킨다)
_CLASSIFIED = re.compile(
    r"^(?P<name>.+?) → (?P<ko>" + "|".join(map(re.escape, _KO_TO_TYPE)) + r") \((?P<reason>.*)\)$", re.S
)
_CLASSIFY_FAILED = re.compile(r"^(?P<name>.+?) 분류 실패: (?P<error>.*)$", re.S)


def _kst_minute(seconds: int) -> str:
    """초(UTC 기준 epoch) → 한국 시간 'YYYY-MM-DD HH:MM'. Lambda 시계는 UTC다."""
    from datetime import datetime

    from agent import KST

    return datetime.fromtimestamp(seconds, KST).strftime("%Y-%m-%d %H:%M")


def _scan_jobs() -> list[dict]:
    """team06-jobs를 끝까지 읽는다. 작업은 데모 규모(수십 건)라 Scan으로 충분하다."""
    items, kwargs = [], {}
    while True:
        page = _table().scan(**kwargs)
        items += page.get("Items", [])
        if "LastEvaluatedKey" not in page:
            return items
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def _classifications(job: Job) -> dict[str, tuple[DocType, str]]:
    """단계 기록에서 파일 이름 → (분류 결과, 근거). 분류 실패는 (unknown, '분류 실패: …')."""
    found: dict[str, tuple[DocType, str]] = {}
    for step in job.steps:
        if step.tool != "classify_document":
            continue
        if (m := _CLASSIFIED.match(step.summary)) is not None:
            found[m["name"]] = (_KO_TO_TYPE[m["ko"]], m["reason"])
        elif (m := _CLASSIFY_FAILED.match(step.summary)) is not None:
            found[m["name"]] = ("unknown", f"분류 실패: {m['error']}")
    return found


def _raw(cell) -> str | None:
    return cell.raw if cell is not None and cell.raw else None


def job_documents(item: dict) -> list[DocumentRecord]:
    """작업 한 줄을 서류 단위 기록으로 펼친다. 아직 분류 전인 서류(queued·running)는 빼고, 끝난 작업에서 기록이 없으면 unknown.

    언제: GET /documents. 받는 것: team06-jobs의 한 줄 (data, docs, files, created_at).
    files 칸이 없는 옛 작업(#143 전)은 읽은 서류(docs)만 펼친다.
    """
    job = Job.model_validate_json(item["data"])
    docs = {d.file: d for d in (_DOCS.validate_json(item["docs"]) if item.get("docs") else [])}
    files = json.loads(item["files"]) if item.get("files") else [{"key": k, "doc_type": None} for k in docs]
    classified = _classifications(job)
    created_at = _kst_minute(int(item.get("created_at") or item.get("updated_at") or 0))
    records = []
    for f in files:
        key, name = f["key"], f["key"].rsplit("/", 1)[-1]
        if f.get("doc_type"):
            doc_type, by, reason = f["doc_type"], "user", "올릴 때 사용자가 고른 종류"
        elif name in classified:
            (doc_type, reason), by = classified[name], "model"
        elif key in docs:  # files 칸이 없는 옛 작업(#143 전)에서 종류를 정해 올린 서류. 분류 기록 없이 읽기만 했다
            doc_type, by, reason = docs[key].doc_type, "user", "올릴 때 고른 종류 (분류 기록 없음)"
        elif job.status in ("queued", "running"):
            continue  # 아직 분류하지 않았다
        else:
            doc_type, by, reason = "unknown", "model", "분류 기록이 없음"
        doc = docs.get(key)
        records.append(DocumentRecord(
            job_id=job.job_id, key=key, file_name=name, doc_type=doc_type, classified_by=by, reason=reason,
            doc_no=_raw(doc.doc_no) if doc else None, consignee=_raw(doc.consignee_name) if doc else None,
            job_status=job.status, created_at=created_at,
        ))
    return records


JOB_STATUSES = ("queued", "running", "waiting_approval", "done", "failed")
GRADES = ("불일치", "확인 필요", "참고")


def _document_filters(query: dict) -> tuple[dict, str | None]:
    """GET /documents 의 거르기 조건 (F11 #195). 반환: (조건, 문제가 있으면 400 문장)."""
    filters = {k: query[k] for k in ("job_status", "grade", "rule_id", "hs") if query.get(k)}
    if filters.get("job_status") not in (None, *JOB_STATUSES):
        return filters, f"job_status는 {', '.join(JOB_STATUSES)} 중 하나입니다"
    if filters.get("grade") not in (None, *GRADES):
        return filters, f"grade는 {', '.join(GRADES)} 중 하나입니다"
    if filters.get("hs") not in (None, "pending"):
        return filters, "hs는 pending만 받습니다"
    if len(filters.get("rule_id", "")) > 40:
        return filters, "rule_id가 너무 깁니다"
    return filters, None


def job_matches(job: Job, filters: dict) -> bool:
    """작업이 거르기 조건을 모두 채우는지. 조건은 작업 단위다 (그 작업의 서류가 모두 나온다).

    grade: 그 등급의 문제가 남은 작업, rule_id: 그 규칙에 걸린 작업, hs=pending: HS를 사람이 골라야 하는 품목이 있는 작업.
    """
    issues = job.result.issues if job.result else []
    if "job_status" in filters and job.status != filters["job_status"]:
        return False
    if "grade" in filters and not any(i.grade == filters["grade"] for i in issues):
        return False
    if "rule_id" in filters and not any(i.rule_id == filters["rule_id"] for i in issues):
        return False
    if "hs" in filters and not (job.result and any(h.status == "사람 확인 필요" for h in job.result.hs)):
        return False
    return True


def list_documents(query: dict | None) -> dict:
    """GET /documents?doc_type=…&cursor=…. 문서 분류 내역 (G10 #143). 모델 호출 없음.

    받는 것: doc_type(LIST_DOC_TYPES 중 하나), cursor(앞 쪽이 준 next_cursor, 없으면 첫 쪽),
             거르기(선택, F11 #195): job_status, grade(불일치 · 확인 필요 · 참고), rule_id, hs=pending. 대시보드 통계에서 들어올 때 쓴다.
    반환: 200 DocumentsResponse (counts는 전체 작업 기준, 거르기가 있으면 그 안에서. items는 최근 작업 먼저 DOC_PAGE건) / 400 요청 형식.
    """
    query = query or {}
    doc_type, cursor = query.get("doc_type"), query.get("cursor") or "0"
    if doc_type not in LIST_DOC_TYPES:
        return _error(400, f"doc_type은 {', '.join(LIST_DOC_TYPES)} 중 하나입니다")
    if not cursor.isdigit():
        return _error(400, "cursor가 잘못됐습니다")
    filters, problem = _document_filters(query)
    if problem:
        return _error(400, problem)
    records: list[DocumentRecord] = []
    for item in _scan_jobs():
        try:
            if filters and not job_matches(Job.model_validate_json(item["data"]), filters):
                continue
            records += job_documents(item)
        except Exception as exc:  # 깨진 줄 하나 때문에 목록 전체가 실패하지 않게 한다
            print(f"[warn] documents job={item.get('job_id')} 건너뜀: {type(exc).__name__}: {exc}")
    records.sort(key=lambda r: (r.created_at, r.job_id), reverse=True)
    counts = {t: 0 for t in LIST_DOC_TYPES}
    for r in records:
        counts[r.doc_type] += 1
    picked = [r for r in records if r.doc_type == doc_type]
    start = int(cursor)
    page = picked[start:start + DOC_PAGE]
    more = start + DOC_PAGE < len(picked)
    body = DocumentsResponse(counts=counts, items=page, next_cursor=str(start + DOC_PAGE) if more else None)
    print(f"[api] documents doc_type={doc_type} 거르기={filters} 전체 {len(records)}장, 이 종류 {len(picked)}장, 쪽 {start}")
    return _response(200, body.model_dump(mode="json"))


# ---------------------------------------------------------------------------
# 대시보드 통계 (F11 #195). 모델 호출 없음, 날짜는 한국 시간
# ---------------------------------------------------------------------------
FLOW_STATUSES = ("입항", "수입신고", "심사 중", "검사 중", "수리", "반출")  # docs/schema.md 화물 기록 (진행 순서)
DELAYED_MAX = 10
TOP_RULES = 5


def _squash_status(text: str) -> str:
    return "".join(text.split())  # '심사중'과 '심사 중'을 같게 본다 (tools/query.py 와 같은 규칙)


def build_stats(items: list[dict], shipments: list, today) -> StatsResponse:
    """작업 줄과 화물 기록으로 대시보드 통계를 센다 (F11 #195). 화면은 이 숫자를 다시 세지 않는다.

    받는 것: team06-jobs 줄 목록, 화물 기록(Shipment) 목록, 오늘(한국 시간 date).
    """
    jobs, records = [], []
    for item in items:
        try:
            jobs.append(Job.model_validate_json(item["data"]))
            records += job_documents(item)
        except Exception as exc:  # 깨진 줄 하나 때문에 통계 전체가 실패하지 않게 한다
            print(f"[warn] stats job={item.get('job_id')} 건너뜀: {type(exc).__name__}: {exc}")
    waiting = [j for j in jobs if j.status == "waiting_approval" and j.result]
    delayed = sorted(
        (s for s in shipments if is_delayed(s, today)), key=lambda s: ((today - s.arrived_at).days, s.bl_no), reverse=True,
    )
    flow = {status: 0 for status in FLOW_STATUSES}
    by_squash = {_squash_status(s): s for s in FLOW_STATUSES}
    for s in shipments:
        status = by_squash.get(_squash_status(s.customs_status))
        if status:
            flow[status] += 1
    docs_by_type = {t: 0 for t in LIST_DOC_TYPES}
    for r in records:
        docs_by_type[r.doc_type] += 1
    finished = [j for j in jobs if j.status in ("waiting_approval", "done") and j.result]
    rules: dict[str, dict] = {}
    for job in sorted(finished, key=lambda j: j.job_id):  # 같은 순서로 세어 예시 문장이 흔들리지 않게
        for issue in job.result.issues:
            entry = rules.setdefault(issue.rule_id, {"count": 0, "grades": {}, "example": issue.evidence})
            entry["count"] += 1
            entry["grades"][issue.grade] = entry["grades"].get(issue.grade, 0) + 1
    top = sorted(rules.items(), key=lambda kv: (-kv[1]["count"], kv[0]))[:TOP_RULES]
    return StatsResponse(
        today=today,
        todo=TodoCounts(
            waiting_approval=len(waiting),
            mismatch_jobs=sum(1 for j in waiting if any(i.grade == "불일치" for i in j.result.issues)),
            hs_pending=sum(1 for j in waiting for h in j.result.hs if h.status == "사람 확인 필요"),
            unclassified=docs_by_type["unknown"],
            delayed=len(delayed),
        ),
        flow=[FlowStage(status=s, count=n) for s, n in flow.items()],
        delayed=[
            DelayedShipment(
                bl_no=s.bl_no, consignee=s.consignee, item=s.item, arrived_at=s.arrived_at,
                customs_status=s.customs_status, days=(today - s.arrived_at).days, job_id=s.job_id,
            )
            for s in delayed[:DELAYED_MAX]
        ],
        delay_rule=DELAY_RULE,
        docs_by_type=docs_by_type,
        auto=AutoRate(
            finished=len(finished), auto=sum(1 for j in finished if j.result.wms and j.result.wms.by == "auto"),
        ),
        top_rules=[
            RuleCount(rule_id=rule_id, grade=max(e["grades"], key=lambda g: (e["grades"][g], -GRADES.index(g))),
                      count=e["count"], example=e["example"])
            for rule_id, e in top
        ],
    )


def stats() -> dict:
    """GET /stats. 대시보드 통계 (F11 #195). 화물 기록을 못 읽어도 작업 통계는 준다 (화물 칸은 0)."""
    try:
        shipments = dynamo_shipments().all()
    except Exception as exc:
        print(f"[warn] stats 화물 기록을 읽지 못함: {type(exc).__name__}: {exc}")
        shipments = []
    body = build_stats(_scan_jobs(), shipments, report._today())
    print(f"[api] stats 작업 대기 {body.todo.waiting_approval}, 지연 {body.todo.delayed}, 화물 {len(shipments)}건")
    return _response(200, body.model_dump(mode="json"))


# ---------------------------------------------------------------------------
# 서류 보기 (F7 #156): 원본 주소 + 읽은 칸. 위변조 확인 화면(G12 #150) 왼쪽 원본 | 오른쪽 OCR 결과
# ---------------------------------------------------------------------------
VIEW_SECONDS = 300  # 원본 보기 주소 유효 시간
IMAGE_HEAD_BYTES = 262_144  # 이미지 크기(px)를 알려고 앞부분만 받는다
_LABELS = {
    "doc_no": "서류 번호", "total_gross_kg": "총중량", "total_qty": "총수량", "consignee_name": "수하인",
    "exporter_name": "수출자", "shipper_name": "송하인", "notify_name": "통지처", "total_amount": "합계 금액",
    "incoterms": "인도 조건", "payment_term": "결제 조건", "origin": "원산지", "total_packages": "총포장 수",
    "total_cbm": "용적(CBM)", "vessel_voyage": "선명·항차", "port_loading": "선적항", "port_discharge": "양륙항",
    "onboard_date": "본선 적재일", "container_no": "컨테이너 번호", "freight_term": "운임 조건", "co_no": "증명서 번호",
    "issue_date": "발급일", "departure_date": "출항일", "invoice_date": "송장 날짜", "issued_retroactively": "소급 발급",
    "item_code": "품목 코드", "name": "품명", "hs_code": "HS 코드", "qty": "수량", "gross_kg": "총중량",
    "net_kg": "순중량", "unit_price": "단가", "amount": "금액", "origin_criterion": "원산지 기준",
}


def presign_view(key: str, content_type: str) -> str:
    """DOCS_BUCKET의 key를 볼 미리 서명된 GET 주소. 형식을 정해 브라우저가 내려받지 않고 띄우게 한다. 주소는 로그에 남기지 않는다."""
    print(f"[tool] s3_presign_get key={key}")
    return _s3().generate_presigned_url(
        "get_object",
        Params={"Bucket": os.environ["DOCS_BUCKET"], "Key": key, "ResponseContentType": content_type,
                "ResponseContentDisposition": "inline"},
        ExpiresIn=VIEW_SECONDS,
    )


def image_size(key: str) -> tuple[int, int] | None:
    """이미지 앞부분만 받아 가로·세로 px를 읽는다. 못 읽으면 None (그때는 쪽 그림 없이 원본 주소만 준다)."""
    try:
        from io import BytesIO

        from PIL import Image

        head = _s3().get_object(Bucket=os.environ["DOCS_BUCKET"], Key=key, Range=f"bytes=0-{IMAGE_HEAD_BYTES - 1}")["Body"].read()
        with Image.open(BytesIO(head)) as img:
            return img.size
    except Exception as exc:  # 깨진 그림, 앞부분에 크기가 없음 등
        print(f"[warn] image_size key={key} {type(exc).__name__}: {exc}")
        return None


def read_fields(doc: ExtractedDocument | None) -> list[ReadField]:
    """읽은 서류를 칸 한 줄씩 펼친다. 칸 경로는 IssueCell.field와 같아 화면이 불일치 칸을 바로 짚는다. 비어 있는 칸은 뺀다."""
    if doc is None:
        return []
    out: list[ReadField] = []

    def add(path: str, label: str, cell) -> None:
        if isinstance(cell, Cell) and (cell.raw is not None or cell.unreadable is not None):
            out.append(ReadField(field=path, label=label, raw=cell.raw, value=cell.value, unit=cell.unit, unreadable=cell.unreadable))

    for name in ExtractedDocument.model_fields:
        add(name, _LABELS.get(name, name), getattr(doc, name))
    for i, item in enumerate(doc.items):
        for name in ExtractedItem.model_fields:
            add(f"items[{i}].{name}", f"{item.line}행 {_LABELS.get(name, name)}", getattr(item, name))
    return out


def job_files(job_id: str) -> dict:
    """GET /jobs/{id}/files. 작업에 올라온 서류마다 원본 주소와 읽은 칸을 준다 (F7 #156). 모델 호출 없음.

    반환: 200 JobFilesResponse (올린 순서, 아직 분류 전 서류는 뺀다) / 404 없는 작업.
    PDF는 처리 Lambda가 그려 둔 쪽 그림(pages 칸)이 있으면 그것을, 없으면 빈 목록(원본을 iframe으로)을 준다 (F10 #188).
    marks(칸 위치)는 처리 Lambda가 저장한 OCR(ocr 칸)에서 분류 근거·읽은 칸의 글자를 찾아 채운다. OCR이 없으면 빈 목록.
    """
    if not JOB_ID.match(job_id):
        return _error(404, "작업을 찾을 수 없습니다")
    item = _load_item(job_id)
    if item is None:
        return _error(404, "작업을 찾을 수 없습니다")
    docs = {d.file: d for d in (_DOCS.validate_json(item["docs"]) if item.get("docs") else [])}
    ocr = json.loads(item["ocr"]) if item.get("ocr") else {}
    rendered = json.loads(item["pages"]) if item.get("pages") else {}
    views = []
    for rec in job_documents(item):
        content_type = UPLOAD_TYPES.get(os.path.splitext(rec.key)[1].lower(), UNKNOWN_TYPE)
        url = presign_view(rec.key, content_type)
        size = image_size(rec.key) if content_type.startswith("image/") and rec.key not in rendered else None
        if size:
            pages = [DocPage(url=url, width=size[0], height=size[1])]
        else:  # PDF·회전된 사진: 처리 Lambda가 그려 둔 쪽 그림 (F10)
            pages = [
                DocPage(url=presign_view(p["key"], "image/jpeg"), width=p["width"], height=p["height"])
                for p in rendered.get(rec.key, [])
            ]
        fields = read_fields(docs.get(rec.key))
        # 칸 위치는 그림 위에 그리므로 쪽 그림이 있을 때만 준다
        marks = locate_marks(fields, OcrResult.model_validate(ocr[rec.key]), rec.reason) if rec.key in ocr and pages else []
        views.append(JobFileView(
            key=rec.key, file_name=rec.file_name, doc_type=rec.doc_type, classified_by=rec.classified_by,
            reason=rec.reason, url=url, content_type=content_type, pages=pages, marks=marks, fields=fields,
        ))
    print(f"[api] job_files job={job_id} files={len(views)}")
    return _response(200, JobFilesResponse(files=views).model_dump(mode="json"))


# 약속 2에 있지만 아직 없는 경로 → 작업 ID (e2e-plan.md). 만들면 여기서 지운다.
_PLANNED: dict[tuple[str, str], str] = {}


def _planned_route(method: str, path: str) -> str | None:
    parts = path.split("/")
    if len(parts) == 4 and parts[1] == "jobs":
        path = f"/jobs/{{id}}/{parts[3]}"
    return _PLANNED.get((method, path))


def _route_path(raw_path: str | None) -> str:
    """rawPath에서 앞의 /api와 끝의 /를 뗀다. '/api/jobs/' → '/jobs', '/api' → '/', '/jobs' → '/jobs'.

    /api로 시작해도 '/apix'처럼 다음 글자가 '/'가 아니면 떼지 않는다.
    """
    path = (raw_path or "/").rstrip("/") or "/"
    if path == API_PREFIX or path.startswith(API_PREFIX + "/"):
        path = path[len(API_PREFIX):] or "/"
    return path


def lambda_handler(event, context):
    """API Gateway HTTP API(페이로드 2.0) 요청을 경로별로 나눈다. /api 없는 옛 경로도 받는다."""
    http = event.get("requestContext", {}).get("http", {})
    method, path = http.get("method", "GET"), _route_path(event.get("rawPath"))
    print(f"[api] {method} {event.get('rawPath')} → {path}")
    try:
        if method == "GET" and path == "/":
            return _response(200, {"ok": True})
        if method == "POST" and path == "/uploads":
            return create_uploads(_body(event))
        if method == "POST" and path == "/jobs":
            return create_job(_body(event))
        if method == "GET" and path.startswith("/jobs/") and path.count("/") == 2:
            return get_job(path.split("/")[2])
        parts = path.split("/")
        if method == "GET" and len(parts) == 4 and parts[1] == "jobs" and parts[3] == "files":
            return job_files(parts[2])
        if method == "POST" and len(parts) == 4 and parts[1] == "jobs" and parts[3] == "hs":
            return choose_hs(parts[2], _body(event))
        if method == "POST" and len(parts) == 4 and parts[1] == "jobs" and parts[3] == "approve":
            return approve_job(parts[2], _body(event))
        if method == "POST" and path == "/chat":
            return chat(_body(event))
        if method == "GET" and path == "/documents":
            return list_documents(event.get("queryStringParameters"))
        if method == "GET" and path == "/stats":
            return stats()
        planned = _planned_route(method, path)
        if planned:
            return _error(501, f"아직 만들지 않은 경로입니다 ({planned}). 형식은 docs/schema.md 약속 2")
        return _error(404, "없는 경로입니다")
    except json.JSONDecodeError:
        return _error(400, "본문이 JSON이 아닙니다")
    except Exception as exc:
        print(f"[error] {type(exc).__name__}: {exc}")
        return _error(500, "서버 오류")
