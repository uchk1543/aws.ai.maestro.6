"""API Lambda team06-api 진입점 (API Gateway HTTP API, 이벤트 형식 2.0). 담당: 서버. 형식: docs/schema.md 약속 2

CloudFront가 /api/*를 API Gateway로 보내고, rawPath에 /api가 붙어 온다 (/api/jobs). 앞의 /api를 떼고 나눈다.
옮기는 동안 /api 없는 경로(/jobs)도 같은 곳으로 간다.
    GET  /api/               → {"ok": true, "version"} (배포 확인. version은 배포한 커밋 GIT_SHA, FB17 #174)
    POST /api/uploads        → {"uploads"}             (F2, 파일마다 S3에 직접 PUT할 미리 서명된 URL)
    POST /api/jobs           → {"job_id"}              (F3, queued로 저장하고 처리 Lambda를 비동기로 부른 뒤 바로 응답)
    GET  /api/jobs/{id}      → Job                     (화면이 2초마다)
    POST /api/jobs/{id}/hs   → {"declaration_draft"}   (C3, 사람이 고른 HS 반영. D2: 조건을 채우면 WMS 자동 등록)
    POST /api/jobs/{id}/approve → {"wms"}              (D3, 사람 승인으로 WMS 등록. 불일치가 남았는데 예외 사유가 없으면 409)
    POST /api/chat           → ChatResponse            (E5, 현황 조회. 1번 agent.query_agent. E6: session_id가 있으면 질문·답을 team06-chat에, 7일 보존)
    GET  /api/documents?doc_type=…&cursor=… → DocumentsResponse (G10 #143, 문서 분류 내역. team06-jobs Scan)
         거르기(F11 #195): job_status · grade · rule_id · hs=pending
    GET  /api/stats           → StatsResponse          (F11 #195, 대시보드 통계. team06-jobs·team06-shipments Scan)
    GET  /api/jobs?next_action=… → JobListResponse     (#252, 다음 할 일이 같은 작업 목록. team06-jobs Scan)
    GET  /api/jobs?all=1&… → JobListResponse          (#281, 작업 내역: 끝난 작업 포함, 서류·걸러낸 문제 요약)
    GET  /api/jobs/{id}/files → JobFilesResponse        (F7 #156, 서류 보기: 원본 주소 + 읽은 칸)
    GET  /api/jobs/{id}/notice?format=md|html → 파일    (F9 #155, 불일치 통지 문서 내려받기. C7 notice_document)
    GET  /api/chat/{id}      → {"messages"}            (E6 #157, 대화 기록 최근 50줄 오래된 순)
서류 처리(run_job)는 처리 Lambda team06-worker(api/worker.py)가 한다. API Gateway는 요청 하나를 30초 안에 끝내야 한다.

환경 변수: JOBS_TABLE(team06-jobs), DOCS_BUCKET(team06-docs-...), MODEL_ID, HS_HISTORY_TABLE(team06-hs-history),
WMS_TABLE(team06-wms), SHIPMENTS_TABLE(team06-shipments), CHAT_TABLE(team06-chat), WORKER_FUNCTION(team06-worker, API Lambda에만),
GIT_SHA(배포한 커밋. infra/deploy.sh가 넣는다, #174)
"""

import base64
import json
import os
import re
import time
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from functools import cache

from botocore.exceptions import BotoCoreError, ClientError
from pydantic import TypeAdapter

from tools import certificate, declaration, hs, hs_request, report, wms
from tools.models import (
    DOC_TYPE_KO,
    Cell,
    ChatFilters,
    ChatHistoryLine,
    ChatHistoryResponse,
    ChatResponse,
    DeclarationDraft,
    DocPage,
    DocType,
    DocumentRecord,
    DocumentsResponse,
    ExtractedContainer,
    ExtractedDocument,
    ExtractedItem,
    Job,
    JobFilesResponse,
    JobFileView,
    IssueBrief,
    JobDocBrief,
    JobListResponse,
    JobSummary,
    AutoRate,
    DelayedShipment,
    FlowStage,
    OcrResult,
    RuleCount,
    StatsResponse,
    TodoCounts,
    ReadField,
    SITE_FIELDS,
    Step,
    WmsState,
)
from tools.ocr import locate_marks
from tools.query import DELAY_RULE, DELAY_STATUS, dynamo_shipments, is_delayed

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
UNKNOWN_VERSION = "unknown"  # GIT_SHA가 없을 때(로컬, deploy.sh가 넣기 전). 커밋을 지어내지 않는다
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
            # next_action 은 GET 때마다 결과로 정하는 칸이라 저장하지 않는다 (FB22)
            "data": job.model_dump_json(by_alias=True, exclude={"next_action"}),
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


class DynamoChatHistory:
    """대화 기록(team06-chat)의 DynamoDB판. 키: session_id(파티션) + ts(정렬). 칸·ts 형식은 docs/schema.md 약속 2 "대화 기록".

    infra/README.md "테이블"의 team06-chat 줄을 넓힌 것이다: ts는 17자리 뒤에 '#<16진수 8자리>#<0|1>'를 붙이고, block_reason 칸을 더한다.
    한 줄 = 최상위 칸 session_id, ts, role, text, expires_at(초, TTL 7일). 답 줄은 blocked와
    값이 있는 filters(map)·count·rule·block_reason을 더한다. null은 칸을 쓰지 않는다.
    읽을 때 count(Decimal)는 int로, 없는 칸은 null로 되돌린다. 형식: docs/schema.md 약속 2.
    """

    def __init__(self, table):
        self.table = table

    def put(self, line: ChatHistoryLine, expires_at: int) -> None:
        item = {"session_id": line.session_id, "ts": line.ts, "role": line.role, "text": line.text, "expires_at": expires_at}
        if line.filters is not None:
            # 칸 모두. 날짜는 'YYYY-MM-DD', 빈 칸은 NULL. 현황 Agent 칸(#257)은 값이 있을 때만 (옛 줄과 같은 모양)
            filters = line.filters.model_dump(mode="json")
            item["filters"] = {k: v for k, v in filters.items() if v is not None or k not in AGENT_FILTER_KEYS}
        for name in ("count", "rule", "blocked", "block_reason"):
            value = getattr(line, name)
            if value is not None:
                item[name] = value
        self.table.put_item(Item=item)

    def recent(self, session_id: str, limit: int, now_s: int) -> list[ChatHistoryLine]:
        """ts가 가장 큰 limit줄에서 만료된 줄(expires_at ≤ now_s)을 빼고 오래된 순으로. Query 한 번(내림차순 + Limit) 뒤 뒤집는다.

        TTL은 만료 뒤 바로 지우지 않아서(며칠 안) 그 전에는 Query에 나온다. 그래서 여기서 뺀다.
        """
        from boto3.dynamodb.conditions import Key

        page = self.table.query(
            KeyConditionExpression=Key("session_id").eq(session_id), ScanIndexForward=False, Limit=limit
        )
        return [_history_line(item) for item in reversed(page.get("Items", [])) if not _expired(item, now_s)]


def _expired(item: dict, now_s: int) -> bool:
    """expires_at이 지금 초 이하면 만료. expires_at이 없는 줄(손으로 넣은 줄 등)은 만료로 보지 않는다."""
    expires_at = item.get("expires_at")
    return expires_at is not None and expires_at <= now_s


def _history_line(item: dict) -> ChatHistoryLine:
    """team06-chat 한 줄 → ChatHistoryLine. 없는 칸은 null, count는 int, filters는 ChatFilters. 맞지 않으면 예외 (GET 502)."""
    return ChatHistoryLine(
        session_id=item["session_id"], ts=item["ts"], role=item["role"], text=item["text"],
        filters=item.get("filters"), count=_whole(item.get("count")), rule=item.get("rule"),
        blocked=item.get("blocked"), block_reason=item.get("block_reason"),
    )


def _whole(value) -> int | None:
    """DynamoDB 숫자(Decimal) → int. 소수가 있거나 숫자가 아니면 ValueError."""
    if value is None:
        return None
    if isinstance(value, bool) or value != int(value):
        raise ValueError(f"count가 정수가 아닙니다: {value!r}")
    return int(value)


AGENT_FILTER_KEYS = ("and_status", "consignee", "item", "bl_no")  # 현황 Agent만 쓰는 조회 칸 (#257)
CHAT_DB_TIMEOUT_S = 2  # 대화 기록 연결·읽기 타임아웃. 기록은 답 뒤에 붙는 부가 일이라 짧게 (API Gateway 30초)
CHAT_DB_ATTEMPTS = 2  # 재시도 1회 (team.md)
CHAT_PUT_WORST_S = 2 * CHAT_DB_TIMEOUT_S * CHAT_DB_ATTEMPTS  # put_item 한 번이 가장 오래 걸리는 시간 (8초)


@cache
def _chat_store() -> DynamoChatHistory:
    """대화 기록 저장소 (POST /chat 기록, GET /chat/{session_id} 조회).

    받는 것: 환경 변수 CHAT_TABLE(team06-chat). 반환: DynamoChatHistory.
    CHAT_TABLE이 없으면 boto3를 만들기 전에 KeyError를 낸다 (@cache는 예외를 저장하지 않아 다음 요청에 다시 시도한다).
    타임아웃은 CHAT_DB_TIMEOUT_S초, 재시도 1회. import할 때는 아무것도 만들지 않는다.
    """
    name = os.environ["CHAT_TABLE"]  # 먼저 읽는다. 없으면 boto3를 만들기 전에 KeyError
    import boto3
    from botocore.config import Config

    config = Config(
        connect_timeout=CHAT_DB_TIMEOUT_S, read_timeout=CHAT_DB_TIMEOUT_S, retries={"max_attempts": CHAT_DB_ATTEMPTS}
    )
    return DynamoChatHistory(boto3.resource("dynamodb", config=config).Table(name))


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
def _pdf_response(data: bytes, filename: str) -> dict:
    """PDF 바이트 응답. API Gateway HTTP API는 이진 본문을 base64 글자로 받는다 (isBase64Encoded)."""
    return {
        "statusCode": 200,
        "isBase64Encoded": True,
        "headers": {
            "content-type": "application/pdf",
            "content-disposition": f'attachment; filename="{filename}"',
            "cache-control": "no-store",
        },
        "body": base64.b64encode(data).decode("ascii"),
    }


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


OVERRIDE_REASON_MAX = 200  # 불일치 예외 승인 사유 길이 상한


def _validate_override_reason(body) -> tuple[str | None, str | None]:
    """POST /jobs/{id}/approve의 override_reason 검사. 없거나 null이면 (None, None). 공백을 한 칸으로 줄인다. (사유, 오류 메시지)"""
    reason = body.get("override_reason") if isinstance(body, dict) else None
    if reason is None:
        return None, None
    if not isinstance(reason, str) or not reason.strip():
        return None, "override_reason(판독 오류로 넘기는 사유)는 비어 있지 않은 글자여야 합니다"
    reason = " ".join(reason.split())
    if len(reason) > OVERRIDE_REASON_MAX:
        return None, f"override_reason은 {OVERRIDE_REASON_MAX}자까지입니다"
    return reason, None


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
    # 작업 화면 맨 위 '다음 할 일' (FB22 #178). 저장하지 않고 응답 때마다 결과로 정한다
    job = job.model_copy(update={"next_action": wms.next_action(job)})
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
      불일치가 남은 건은 검수자가 원본을 보고 판독 오류로 판단해 사유(override_reason)를 적었을 때만 등록한다.
    받는 것: {"approver", "override_reason"?}: 승인자 이름(공백만이면 안 되고 50자까지), 불일치 예외 사유(200자까지, 없으면 생략).
      둘 다 단계 기록에 남기고, 사유는 result.wms.override_reason에도 남는다 (검수 완료서가 찍는다).
    반환: 200 {"wms": {"status", "wms_id"}} / 400 요청 형식 / 404 없는 작업
      / 409 {"error"}: 불일치가 남았는데 사유가 없음, 승인 대기 중이 아님, 서류 기록이 없음, B/L 번호·수하인이 없어 기록을 못 만듦,
        같은 B/L이 다른 작업으로 이미 등록됨(#176. 이때만 단계 기록에 이유를 한 줄 남긴다. 같은 이유면 다시 남기지 않는다)
      / 502 가상 WMS 저장 실패 (작업은 그대로라 다시 승인하면 된다).
    이미 등록된 작업이면 다시 등록하지 않고 그 상태를 돌려준다. WMS 쪽도 멱등 키라 재시도해도 한 번만 들어간다.
    저장: result.wms = {등록됨, human, wms_id, approver, approved_at(한국 시간)}, status = done, steps에 push_to_wms 한 줄과 mark_registered 한 줄(E3).
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
    override_reason, problem = _validate_override_reason(body)
    if problem:
        return _error(400, problem)
    job = Job.model_validate_json(item["data"])
    if job.result is not None and job.result.wms is not None and job.result.wms.status == "등록됨":
        return _response(200, _wms_body(job.result.wms))
    if job.status != "waiting_approval" or job.result is None:
        return _error(409, f"승인은 승인 대기 중인 작업에서만 할 수 있습니다 (지금: {job.status})")
    try:
        wms.approve(job.result, "human", override_reason)
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
    # 검수자 이름과 승인 시각(한국 시간)을 칸으로 남긴다. 검수 완료서가 읽는다 (X1 #258). Lambda 시계는 UTC라 +09:00으로 고쳐 적는다
    # 불일치가 없으면 사유는 남기지 않는다 (예외로 넘긴 것이 없으므로)
    mismatch = [i for i in job.result.issues if i.grade == "불일치"]
    kept_reason = override_reason if mismatch else None
    state = state.model_copy(
        update={
            "approver": approver,
            "approved_at": datetime.now(KST_OFFSET).isoformat(timespec="seconds"),
            "override_reason": kept_reason,
        }
    )
    job.result.wms = state
    job.status = "done"
    summary = f"사람 승인({approver})으로 WMS 등록: {state.wms_id}"
    if kept_reason:
        rules = ", ".join(dict.fromkeys(i.rule_id for i in mismatch))
        summary += f" (불일치 {len(mismatch)}건({rules})을 판독 오류로 확인, 사유: {kept_reason})"
    job.steps.append(Step(tool="push_to_wms", summary=summary, ok=True))
    job.steps.append(_mark_registered(job_id, record.bl_no))
    save_job(job, keep=item)
    return _response(200, _wms_body(state))


def job_certificate(job_id: str) -> dict:
    """GET /jobs/{id}/certificate. 사람이 승인해 등록한 작업의 검수 완료서(PDF)를 만들어 돌려준다 (X1 #258).
    언제: 화면의 '검수 완료서 받기'. 파일은 저장하지 않고 부를 때마다 저장된 작업에서 만든다. 모델·S3 호출 없음.
    반환: 200 application/pdf(attachment, certificate-<작업 ID>.pdf) / 404 없는 작업
      / 409 {"error"}: 승인 대기·자동 등록·등록 전, 검수자 이름이 없는 옛 작업
      / 500 {"error"} PDF를 만들지 못함 (WMS 등록 상태는 바뀌지 않는다).
    """
    if not JOB_ID.match(job_id):
        return _error(404, "작업을 찾을 수 없습니다")
    item = _load_item(job_id)
    if item is None:
        return _error(404, "작업을 찾을 수 없습니다")
    job = Job.model_validate_json(item["data"])
    try:
        certificate.check_issuable(job)
    except certificate.NotIssuable as exc:
        return _error(409, str(exc))
    context = load_job_docs(item)
    docs, importer = context if context is not None else ([], None)
    try:
        data = certificate.make_certificate(job, docs, importer=importer)
    except Exception as exc:
        print(f"[error] 검수 완료서 만들기 실패 job={job_id} {type(exc).__name__}: {exc}")
        return _error(500, "검수 완료서를 만들지 못했습니다")
    return _pdf_response(data, f"certificate-{job_id}.pdf")
def job_hs_request(job_id: str) -> dict:
    """GET /jobs/{id}/hs-request. HS를 사람이 확인해야 하는 품목을 담은 HS 확인 요청서(PDF)를 돌려준다 (X2 #260).
    언제: 화면의 'HS 확인 요청서 받기'. 관세사에게 전달할 문서다. 파일은 저장하지 않고 부를 때마다 저장된 작업에서 만든다. 모델·S3 호출 없음.
    반환: 200 application/pdf(attachment, hs-request-<작업 ID>.pdf) / 404 없는 작업
      / 409 {"error"}: 사람이 확인해야 하는 HS 품목이 없음 (확정됐거나 아직 처리 전)
      / 500 {"error"} PDF를 만들지 못함 (작업은 바뀌지 않는다).
    서류 기록이 없으면 서류 값 칸은 비워 두고 작업 결과의 품명·서류 HS·후보만 담는다.
    """
    if not JOB_ID.match(job_id):
        return _error(404, "작업을 찾을 수 없습니다")
    item = _load_item(job_id)
    if item is None:
        return _error(404, "작업을 찾을 수 없습니다")
    job = Job.model_validate_json(item["data"])
    try:
        hs_request.check_requestable(job)
    except hs_request.NothingToRequest as exc:
        return _error(409, str(exc))
    context = load_job_docs(item)
    docs, importer = context if context is not None else ([], None)
    try:
        data = hs_request.make_hs_request(job, docs, importer=importer)
    except Exception as exc:
        print(f"[error] HS 확인 요청서 만들기 실패 job={job_id} {type(exc).__name__}: {exc}")
        return _error(500, "HS 확인 요청서를 만들지 못했습니다")
    return _pdf_response(data, f"hs-request-{job_id}.pdf")
MAX_QUESTION = 500  # 현황 질문 길이 한도
# fullmatch로 쓴다('$'는 끝 줄바꿈 앞에서도 맞는다). 첫 글자는 영문·숫자: '-' 하나는 answer·로그의 익명 표시다
SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,63}")
SESSION_ID_ERROR = "session_id는 영문·숫자로 시작하고 영문·숫자·-로 64자까지입니다"
HISTORY_LIMIT = 50  # GET /chat/{session_id}가 읽는 줄 수 (Turn이 아니라 줄)
HISTORY_ERROR = "대화 기록을 불러오지 못했습니다"
CHAT_TTL_SECONDS = 7 * 24 * 60 * 60  # 604800. team06-chat expires_at (infra/create.sh가 TTL을 켰다)
# 요청을 받은 뒤 이 초가 지나기 전에 기록을 끝낼 수 없으면 쓰지 않는다. API Gateway는 30초에 끊는다
CHAT_DEADLINE_S = 25

KST_OFFSET = timezone(timedelta(hours=9))  # 한국 시간. 1988년 뒤 서머타임이 없어 고정 +9 (ts 글자 순서 = 시간 순서)
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
TS_MS_MAX = 253_402_268_400_000  # 한국 시간 10000-01-01 00:00. 이보다 작아야 연도가 네 자리


def kst_stamp(ms: int) -> str:
    """UTC 유닉스 밀리초(0 ≤ ms < TS_MS_MAX) → 한국 시간 'YYYYMMDDHHMMSSmmm' 17자리 (infra/README.md team06-chat ts).

    datetime.fromtimestamp는 Windows에서 3000년 뒤 값에 OSError를 내서 epoch에 더해 계산한다.
    """
    t = (_EPOCH + timedelta(milliseconds=ms)).astimezone(KST_OFFSET)
    return t.strftime("%Y%m%d%H%M%S") + f"{ms % 1000:03d}"


def history_ts(ms: int, tag: str, order: int) -> str:
    """기록 줄 정렬 키 '<kst_stamp(ms)>#<tag>#<order>'. tag: 16진수 8자리, order: 0 질문 · 1 답."""
    return f"{kst_stamp(ms)}#{tag}#{order}"


def _now_ms() -> int:
    """지금 UTC 유닉스 밀리초. 테스트가 바꿔 끼운다."""
    return time.time_ns() // 1_000_000


def _request_tag() -> str:
    """요청마다 새 16진수 8자리. 같은 밀리초의 두 요청이 같은 ts로 덮어쓰지 않게 한다."""
    return uuid.uuid4().hex[:8]


def _monotonic() -> float:
    """요청이 얼마나 걸렸는지 잴 때 쓰는 초 (time.monotonic). 테스트가 바꿔 끼운다."""
    return time.monotonic()


def chat(body) -> dict:
    """POST /chat. 현황 질문에 답하고, session_id가 있으면 질문·답 한 줄씩 7일 남긴다 (E5·E6 #157). 형식: docs/schema.md 약속 2

    받는 것: {"session_id", "message"}. message는 비지 않은 글자 500자까지.
      session_id는 영문·숫자로 시작하고 영문·숫자·-로 1~64자. 칸이 없거나 null이면 답만 하고 기록은 남기지 않는다
      (Query_Agent에는 '-').
    반환: 200 ChatResponse / 400 요청 형식. 기록 저장이 실패해도 본문은 같은 200이다 ([warn] chat-history 로그만).
      답이 늦어 CHAT_DEADLINE_S 안에 기록을 끝낼 수 없으면 기록을 건너뛴다 (API Gateway 30초 안에 답한다).
      가드레일(E7 #152)은 answer 안에서 돈다. 막힌 답(ChatResponse.blocked)은 blocked true와 그 이유로 남긴다.
      현황 Agent(#257, 환경 변수 QUERY_AGENT=1)를 켜면 같은 세션의 앞 대화 HISTORY_TURN_LINES줄과 작업·서류 읽기(HandlerJobs)를 넘긴다.
      앞 대화를 못 읽으면 앞 대화 없이 답한다.
    """
    started = _monotonic()
    message = body.get("message") if isinstance(body, dict) else None
    session_id = body.get("session_id") if isinstance(body, dict) else None
    if not isinstance(message, str) or not message.strip():
        return _error(400, "message가 비어 있습니다")
    if len(message) > MAX_QUESTION:
        return _error(400, f"message는 {MAX_QUESTION}자까지입니다")
    if session_id is not None and not _session_ok(session_id):
        return _error(400, SESSION_ID_ERROR)
    from agent.query_agent import answer
    from tools.query import dynamo_shipments

    question = message.strip()
    ms, tag = _now_ms(), _request_tag()
    agent_on = os.environ.get("QUERY_AGENT") == "1"  # 현황 Agent (#257). 켰을 때만 앞 대화를 읽어 넘긴다
    history = _recent_turns(session_id, ms) if agent_on and session_id is not None else None
    res = answer(question, session_id or "-", store=dynamo_shipments(), jobs=HandlerJobs() if agent_on else None, history=history)
    if session_id is not None:
        _save_turn(session_id, ms, tag, question, res, started)
    return _response(200, res.model_dump(mode="json", by_alias=True))


HISTORY_TURN_LINES = 6  # 현황 Agent에 넘기는 앞 대화 줄 수 (질문·답 3턴, #257)


def _recent_turns(session_id: str, ms: int) -> list[ChatHistoryLine]:
    """현황 Agent에 넘길 같은 세션의 앞 대화 (오래된 순). 읽기 실패는 빈 목록 ([warn] 로그만, 답은 계속한다)."""
    try:
        return _chat_store().recent(session_id, HISTORY_TURN_LINES, ms // 1000)
    except Exception as exc:
        print(f"[warn] chat-history session={session_id} 앞 대화 못 읽음 {type(exc).__name__}: {exc}")
        return []


class HandlerJobs:
    """현황 Agent의 작업·서류 읽기 (#257, tools.query.JobSource). GET /jobs/{id}·GET /jobs·GET /documents와 같은 코드. 읽기만 한다.

    작업 줄 Scan은 질문 하나에 한 번만 한다 (find_jobs·list_documents가 함께 써도). 깨진 줄은 건너뛴다.
    """

    def __init__(self):
        self._items: list[dict] | None = None

    def _all(self) -> list[dict]:
        if self._items is None:
            self._items = sorted(
                _scan_jobs(), key=lambda i: int(i.get("created_at") or i.get("updated_at") or 0), reverse=True
            )
        return self._items

    def job(self, job_id: str) -> Job | None:
        return load_job(job_id) if JOB_ID.match(job_id) else None

    def jobs(self) -> list[JobSummary]:
        rows = []
        for item in self._all():
            try:
                rows.append(job_summary(item))
            except Exception as exc:
                print(f"[warn] chat jobs job={item.get('job_id')} 건너뜀: {type(exc).__name__}: {exc}")
        return rows

    def documents(self) -> list[DocumentRecord]:
        records = []
        for item in self._all():
            try:
                records += job_documents(item)
            except Exception as exc:
                print(f"[warn] chat documents job={item.get('job_id')} 건너뜀: {type(exc).__name__}: {exc}")
        return records


def _session_ok(value) -> bool:
    """POST /chat·GET /chat/{session_id}의 session_id 검사. 받는 것: 아무 값. 반환: 문자열이고 SESSION_ID 형식이면 True."""
    return isinstance(value, str) and SESSION_ID.fullmatch(value) is not None


def _queried(filters: ChatFilters) -> bool:
    """answer가 실제로 화물 기록을 조회했는지 응답 조건으로 가린다 (agent/query_agent.py answer의 분기와 같다).

    조회하지 않는 답: 못 담는 조건(unsupported)이 있음, 조건(상태·기간, #257의 그중 상태·수입자·품명·B/L)이 모두 없음(되묻기·조건을 못 만듦),
    상태가 화물 기록 값 목록에 없음. 조회했으면 응답 상태는 값 목록의 표기로 맞춰져 있다.
    """
    from agent.query_agent import STATUSES

    conditions = (filters.status, filters.period, filters.and_status, filters.consignee, filters.item, filters.bl_no)
    if filters.unsupported or not any(conditions):
        return False
    return all(s is None or s in (*STATUSES, DELAY_STATUS) for s in (filters.status, filters.and_status))


def _reply_fields(res: ChatResponse) -> dict:
    """답 줄의 filters·count·rule·blocked·block_reason.

    막힌 답이면 이유만. 막지 않은 답은 조건을 남기고, 실제로 조회했을 때만 건수(rows 수)와 규칙 문장을 남긴다.
    조회하지 않은 답(되묻기·읽기 실패 등)의 count를 0으로 쓰면 0건 조회와 구분할 수 없다.
    """
    if res.blocked is not None:  # E7: 막으면 모델·조회 없이 정해 둔 답과 이유를 준다
        return {"blocked": True, "block_reason": res.blocked}
    if not _queried(res.filters):
        return {"filters": res.filters, "blocked": False}
    rule = DELAY_RULE if DELAY_STATUS in (res.filters.status, res.filters.and_status) else None
    return {"filters": res.filters, "count": len(res.rows), "rule": rule, "blocked": False}


def _save_turn(session_id: str, ms: int, tag: str, question: str, res: ChatResponse, started: float) -> None:
    """한 Turn의 질문 줄(#0)과 답 줄(#1)을 같은 expires_at(요청 초 + 7일)으로 남긴다. 예외를 내지 않는다 (기록은 부가 기능).

    받는 것: started = 요청을 받은 _monotonic() 초. put 한 번이 가장 오래 걸려도(CHAT_PUT_WORST_S)
      CHAT_DEADLINE_S 안에 끝나지 않으면 그 줄부터 쓰지 않는다 (API Gateway 30초 안에 답하려고).
    저장소를 못 만들거나 줄을 못 만들면 둘 다 건너뛴다. 질문 줄 쓰기가 실패해도 답 줄은 쓴다.
    """
    expires_at = ms // 1000 + CHAT_TTL_SECONDS
    try:
        store = _chat_store()
        lines = [
            ChatHistoryLine(session_id=session_id, ts=history_ts(ms, tag, 0), role="user", text=question),
            ChatHistoryLine(
                session_id=session_id, ts=history_ts(ms, tag, 1), role="assistant", text=res.answer, **_reply_fields(res)
            ),
        ]
    except Exception as exc:
        print(f"[warn] chat-history session={session_id} 기록 못 함 {type(exc).__name__}: {exc}")
        return
    for line in lines:
        elapsed = _monotonic() - started
        if elapsed + CHAT_PUT_WORST_S > CHAT_DEADLINE_S:
            print(f"[warn] chat-history session={session_id} role={line.role} 시간 부족으로 건너뜀 ({elapsed:.1f}초 지남)")
            return
        try:
            store.put(line, expires_at)
        except Exception as exc:
            print(f"[warn] chat-history session={session_id} role={line.role} 저장 실패 {type(exc).__name__}: {exc}")


def get_chat_history(session_id) -> dict:
    """GET /chat/{session_id}. 그 세션의 최근 HISTORY_LIMIT줄에서 만료된 줄을 빼고 오래된 순으로 (E6 #157). 형식: docs/examples/chat_history.json

    반환: 200 ChatHistoryResponse (expires_at 없음) / 400 session_id 형식 (테이블을 읽지 않는다) / 502 읽기 실패.
      저장소를 못 만들거나(CHAT_TABLE 없음) 저장된 줄이 모델과 맞지 않아도 502다.
    """
    if not _session_ok(session_id):
        return _error(400, SESSION_ID_ERROR)
    try:
        lines = _chat_store().recent(session_id, HISTORY_LIMIT, _now_ms() // 1000)
    except Exception as exc:
        print(f"[error] chat-history session={session_id} {type(exc).__name__}: {exc}")
        return _error(502, HISTORY_ERROR)
    print(f"[api] chat-history session={session_id} lines={len(lines)}")
    return _response(200, ChatHistoryResponse(messages=lines).model_dump(mode="json"))


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
# 다음 할 일별 작업 수 (#252). 'none'(끝남)은 세지 않는다
NEXT_KINDS = ("fix_docs", "choose_hs", "approve", "reupload", "wait")
AUTO_RULE = "불일치·확인 필요가 없고 모든 품목의 HS가 정해진 작업만 사람 손 없이 WMS에 등록합니다"
JOB_LIST_MAX = 50


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
            if issue.grade == "참고":  # 참고는 할 일이 아니라 순위에서 뺀다 (#252)
                continue
            entry = rules.setdefault(issue.rule_id, {"count": 0, "grades": {}, "example": issue.evidence})
            entry["count"] += 1
            entry["grades"][issue.grade] = entry["grades"].get(issue.grade, 0) + 1
    top = sorted(rules.items(), key=lambda kv: (-kv[1]["count"], kv[0]))[:TOP_RULES]
    # 다음 할 일별 작업 수 (#252). 작업 하나는 정확히 한 칸 (wms.next_action, GET /jobs/{id}와 같은 규칙)
    kinds = {k: 0 for k in NEXT_KINDS}
    for job in jobs:
        kind = wms.next_action(job).kind
        if kind in kinds:
            kinds[kind] += 1
    return StatsResponse(
        today=today,
        todo=TodoCounts(
            waiting_approval=len(waiting),
            mismatch_jobs=sum(1 for j in waiting if any(i.grade == "불일치" for i in j.result.issues)),
            hs_pending=sum(1 for j in waiting for h in j.result.hs if h.status == "사람 확인 필요"),
            unclassified=docs_by_type["unknown"],
            delayed=len(delayed),
            **kinds,
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
            rule=AUTO_RULE,
        ),
        top_rules=[_rule_count(rule_id, e) for rule_id, e in top],
    )


def _rule_count(rule_id: str, e: dict) -> RuleCount:
    """센 규칙 하나 → RuleCount. 가장 많이 나온 등급의 사람 말 이름(rules.csv description)을 붙인다."""
    from tools.validate import load_rules

    grade = max(e["grades"], key=lambda g: (e["grades"][g], -GRADES.index(g)))
    row = load_rules().get((rule_id, grade))
    return RuleCount(rule_id=rule_id, grade=grade, count=e["count"], example=e["example"], name=row["description"] if row else None)


ISSUE_BRIEF_MAX = 3  # 작업 내역 카드에 보일 문제 줄 수 (#281)


def job_summary(item: dict, *, detail: bool = False) -> JobSummary:
    """작업 한 줄 → 목록 한 줄 (#252). B/L·수입자는 저장된 읽은 서류에서, 다음 할 일은 GET /jobs/{id}와 같은 규칙.

    언제: GET /jobs. 받는 것: team06-jobs의 한 줄. 서류 기록이 없는 작업(처리 중·옛 작업)은 B/L·수입자가 null.
    detail=True(작업 내역, #281)면 올린 서류와 분류 결과(docs), 걸러낸 문제 앞 몇 건(issues)도 채운다.
    """
    job = Job.model_validate_json(item["data"])
    loaded = load_job_docs(item)
    docs, importer = loaded if loaded else ([], None)
    bl = next((d for d in docs if d.doc_type == "bill_of_lading"), None)
    invoice = next((d for d in docs if d.doc_type == "commercial_invoice"), None)
    result = job.result
    return JobSummary(
        job_id=job.job_id,
        status=job.status,
        bl_no=_raw(bl.doc_no) if bl else None,
        consignee=importer or (_raw(invoice.consignee_name) if invoice else None),
        created_at=_kst_minute(int(item.get("created_at") or item.get("updated_at") or 0)),
        next_action=wms.next_action(job),
        mismatch=sum(1 for i in result.issues if i.grade == "불일치") if result else 0,
        hs_pending=sum(1 for h in result.hs if h.status == "사람 확인 필요") if result else 0,
        check=sum(1 for i in result.issues if i.grade == "확인 필요") if result else 0,
        docs=(
            [JobDocBrief(file_name=r.file_name, doc_type=r.doc_type, classified_by=r.classified_by) for r in job_documents(item)]
            if detail else []
        ),
        issues=(
            [
                IssueBrief(grade=i.grade, rule_id=i.rule_id, evidence=i.evidence)
                for i in result.issues if i.grade in ("불일치", "확인 필요")
            ][:ISSUE_BRIEF_MAX]
            if detail and result else []
        ),
    )


def list_jobs(query) -> dict:
    """GET /jobs?next_action=<kind>. 다음 할 일이 같은 작업 목록 (#252, 대시보드 카드를 누르면 그 자리에 펼친다).

    받는 것: next_action(fix_docs·choose_hs·approve·reupload·wait 중 하나, 없으면 끝난 작업을 뺀 전부).
      작업 내역(#281): all=1이면 끝난 작업도 넣고, 줄마다 올린 서류·걸러낸 문제(docs·check·issues)와 전체 수(total)를 채운다.
      all=1일 때 거르기(선택): job_status, grade, rule_id, hs=pending (GET /documents와 같은 규칙), type(그 종류의 서류가 있는 작업).
    반환: 200 JobListResponse (최근 작업 먼저, JOB_LIST_MAX건) / 400 next_action·거르기 값 / 502 읽기 실패.
      개수는 GET /stats의 todo 같은 칸과 같은 규칙이다. 깨진 작업 줄은 건너뛴다.
    """
    query = query or {}
    kind = query.get("next_action")
    if kind is not None and kind not in NEXT_KINDS:
        return _error(400, f"next_action은 {', '.join(NEXT_KINDS)} 중 하나입니다")
    every = query.get("all") == "1"
    filters, problem = _document_filters(query) if every else ({}, None)
    if problem:
        return _error(400, problem)
    doc_type = query.get("type") if every else None
    if doc_type is not None and doc_type not in LIST_DOC_TYPES:
        return _error(400, f"type은 {', '.join(LIST_DOC_TYPES)} 중 하나입니다")
    try:
        items = _scan_jobs()
    except Exception as exc:
        print(f"[error] list_jobs {type(exc).__name__}: {exc}")
        return _error(502, "작업 목록을 읽지 못했습니다")
    rows: list[tuple[int, JobSummary]] = []
    for item in items:
        try:
            if filters and not job_matches(Job.model_validate_json(item["data"]), filters):
                continue
            row = job_summary(item, detail=every)
        except Exception as exc:  # 깨진 줄 하나 때문에 목록 전체가 실패하지 않게 한다
            print(f"[warn] list_jobs job={item.get('job_id')} 건너뜀: {type(exc).__name__}: {exc}")
            continue
        if (row.next_action.kind == "none" and not every) or (kind and row.next_action.kind != kind):
            continue
        if doc_type and not any(d.doc_type == doc_type for d in row.docs):
            continue
        rows.append((int(item.get("created_at") or item.get("updated_at") or 0), row))
    rows.sort(key=lambda r: (r[0], r[1].job_id), reverse=True)
    print(f"[api] jobs next_action={kind} all={every} 거르기={filters} type={doc_type} {len(rows)}건")
    body = JobListResponse(items=[r for _, r in rows[:JOB_LIST_MAX]], total=len(rows) if every else None)
    return _response(200, body.model_dump(mode="json"))


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
    "marks": "화인", "packages": "포장 수", "seal_no": "봉인 번호", "size_type": "규격", "cbm": "용적(CBM)",
}
_CONTAINER_LABELS = {"container_no": "번호"}  # "1번 컨테이너 컨테이너 번호"가 되지 않게 컨테이너 줄에서만 바꾼다
_LINE_INDEX = re.compile(r"\[\d+\]")


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
    """읽은 서류를 칸 한 줄씩 펼친다. 칸 경로는 IssueCell.field와 같아 화면이 불일치 칸을 바로 짚는다. 비어 있는 칸은 뺀다.

    받는 것: 읽은 서류(없으면 빈 목록). 반환: 서류 전체 칸 → 품목 줄(items[i]) → B/L 컨테이너 줄(containers[i]) 순서의 ReadField.
    site는 경로에서 줄 번호([숫자])를 뺀 이름이 그 서류 종류의 SITE_FIELDS에 있으면 true다 (F12 #230). 관리자 칸도 빠짐없이 나간다.
    """
    if doc is None:
        return []
    site_fields = SITE_FIELDS.get(doc.doc_type, frozenset())
    out: list[ReadField] = []

    def add(path: str, label: str, cell) -> None:
        if isinstance(cell, Cell) and (cell.raw is not None or cell.unreadable is not None):
            out.append(ReadField(
                field=path, label=label, raw=cell.raw, value=cell.value, unit=cell.unit, unreadable=cell.unreadable,
                site=_LINE_INDEX.sub("", path) in site_fields,
            ))

    for name in ExtractedDocument.model_fields:
        add(name, _LABELS.get(name, name), getattr(doc, name))
    for i, item in enumerate(doc.items):
        for name in ExtractedItem.model_fields:
            add(f"items[{i}].{name}", f"{item.line}행 {_LABELS.get(name, name)}", getattr(item, name))
    for i, box in enumerate(doc.containers):
        for name in ExtractedContainer.model_fields:
            label = _CONTAINER_LABELS.get(name) or _LABELS.get(name, name)
            add(f"containers[{i}].{name}", f"{box.line}번 컨테이너 {label}", getattr(box, name))
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


# ---------------------------------------------------------------------------
# 불일치 통지 문서 내려받기 (F9 #155). 문서는 C7(#158) tools.validate.notice_document가 코드로 만든다
# ---------------------------------------------------------------------------
NOTICE_FORMATS = {"md": ("text/markdown; charset=utf-8", "markdown"), "html": ("text/html; charset=utf-8", "html")}


def _notice_name(subject: str, job_id: str, ext: str) -> str:
    """내려받을 파일 이름. 제목의 B/L 번호(영문·숫자)를 쓰고, 없으면 작업 ID. 헤더에 넣으므로 영문·숫자·-·_만 남긴다."""
    match = re.search(r"B/L\s+([A-Za-z0-9-]+)", subject)
    stem = re.sub(r"[^A-Za-z0-9_-]", "", match.group(1) if match else job_id)[:60] or job_id
    return f"notice-{stem}.{ext}"


def job_notice(job_id: str, query: dict | None) -> dict:
    """GET /jobs/{id}/notice?format=md|html. 불일치 통지 문서를 파일로 내려받는다 (F9 #155). 모델 호출 없음.

    언제: 위변조 확인 화면(G12)의 '관리자에게 보낼 문서 받기'. 보내기 전에 사람이 검토한다 (메일 보내기는 하지 않는다).
    받는 것: format(md 또는 html, 없으면 html).
    반환: 200 파일(content-disposition: attachment) / 400 형식 / 404 없는 작업 / 409 처리 중이거나 서류 기록이 없음.
    """
    from tools.validate import notice_document

    fmt = (query or {}).get("format") or "html"
    if fmt not in NOTICE_FORMATS:
        return _error(400, f"format은 {', '.join(NOTICE_FORMATS)} 중 하나입니다")
    if not JOB_ID.match(job_id):
        return _error(404, "작업을 찾을 수 없습니다")
    item = _load_item(job_id)
    if item is None:
        return _error(404, "작업을 찾을 수 없습니다")
    job = Job.model_validate_json(item["data"])
    if job.status in ("queued", "running") or job.result is None:
        return _error(409, f"처리가 끝난 작업에서만 문서를 만들 수 있습니다 (지금: {job.status})")
    context = load_job_docs(item)
    if context is None:
        return _error(409, "이 작업에는 저장된 서류 기록이 없어 문서를 만들 수 없습니다")
    docs, _ = context
    notice = notice_document(job_id, docs, job.result.issues)
    content_type, attr = NOTICE_FORMATS[fmt]
    name = _notice_name(notice.subject, job_id, fmt)
    print(f"[api] notice job={job_id} format={fmt} 불일치 {notice.mismatch_count} 확인 필요 {notice.check_count}")
    return {
        "statusCode": 200,
        "headers": {"content-type": content_type, "content-disposition": f'attachment; filename="{name}"'},
        "body": getattr(notice, attr),
    }


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
            return _response(200, {"ok": True, "version": os.environ.get("GIT_SHA") or UNKNOWN_VERSION})
        if method == "POST" and path == "/uploads":
            return create_uploads(_body(event))
        if method == "POST" and path == "/jobs":
            return create_job(_body(event))
        if method == "GET" and path == "/jobs":
            return list_jobs(event.get("queryStringParameters"))
        if method == "GET" and path.startswith("/jobs/") and path.count("/") == 2:
            return get_job(path.split("/")[2])
        parts = path.split("/")
        if method == "GET" and len(parts) == 3 and parts[1] == "chat":
            return get_chat_history(parts[2])
        if method == "GET" and len(parts) == 4 and parts[1] == "jobs" and parts[3] == "files":
            return job_files(parts[2])
        if method == "GET" and len(parts) == 4 and parts[1] == "jobs" and parts[3] == "notice":
            return job_notice(parts[2], event.get("queryStringParameters"))
        if method == "GET" and len(parts) == 4 and parts[1] == "jobs" and parts[3] == "certificate":
            return job_certificate(parts[2])
        if method == "GET" and len(parts) == 4 and parts[1] == "jobs" and parts[3] == "hs-request":
            return job_hs_request(parts[2])
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
