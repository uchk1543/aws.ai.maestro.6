"""Lambda 진입점 (Function URL, 이벤트 형식 2.0). 담당: 서버. 형식: docs/schema.md 약속 2

뼈대 경로
    GET  /               → {"ok": true}            (S4 배포 확인)
    POST /jobs           → {"job_id"}              (S5, 안에서 끝까지 처리)
    GET  /jobs/{id}      → Job                     (S5)
    POST /jobs/{id}/hs   → {"declaration_draft"}   (C3, 사람이 고른 HS 반영)
    POST /jobs/{id}/approve → {"wms"}              (D3, 사람 승인으로 WMS 등록. 불일치가 남았으면 409)
나머지 경로(/uploads, /chat)는 501을 돌려준다. Spec 2·3에서 채운다.

환경 변수: JOBS_TABLE(team06-jobs), DOCS_BUCKET(team06-docs-...), MODEL_ID, HS_HISTORY_TABLE(team06-hs-history),
WMS_TABLE(team06-wms)
"""

import base64
import json
import os
import re
import time
import uuid
from functools import cache

from botocore.exceptions import BotoCoreError, ClientError
from pydantic import TypeAdapter

from tools import declaration, hs, wms
from tools.models import ExtractedDocument, Job, Step, WmsState

ALLOWED_DOC_TYPES = {"commercial_invoice", "packing_list"}  # 뼈대 범위 (S2)
JOB_ID = re.compile(r"^job-[0-9a-f]{8}$")
HS_CODE = re.compile(r"^[0-9]{10}$")  # 10자리 HSK
APPROVER_MAX = 50  # 승인자 이름 길이. 화면 입력칸(WmsPanel maxLength)과 같다
KEY_PREFIX = "uploads/"
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

    return boto3.client("s3", config=Config(connect_timeout=5, read_timeout=5, retries={"max_attempts": 2}))


def fetch_object(key: str) -> bytes:
    """DOCS_BUCKET에서 파일을 받는다."""
    print(f"[tool] s3_get key={key}")
    return _s3().get_object(Bucket=os.environ["DOCS_BUCKET"], Key=key)["Body"].read()


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


def load_job_docs(item: dict) -> tuple[list[ExtractedDocument], str] | None:
    """HS를 다시 반영할 때 쓸 읽은 서류와 수입자. 없으면 None.

    언제: POST /jobs/{id}/hs. 모델을 다시 부르지 않으려고 저장해 둔 값을 쓴다 (agent-design.md 6번).
    받는 것: team06-jobs의 한 줄. docs 칸(ExtractedDocument 목록 JSON)과 importer 칸(수입자)을 읽는다.
    반환: (서류 목록, 수입자). 두 칸 중 하나라도 없으면 None.
    아직 이 두 칸을 쓰는 쪽이 없다: run_job(1번)은 Job만 돌려주고, 수입자는 약속 1에 칸이 없다.
    """
    raw_docs, importer = item.get("docs"), item.get("importer")
    if not raw_docs or not importer:
        return None
    return _DOCS.validate_json(raw_docs), importer


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


@cache
def _hs_history() -> DynamoHSHistory:
    import boto3
    from botocore.config import Config

    config = Config(connect_timeout=5, read_timeout=5, retries={"max_attempts": 2})
    return DynamoHSHistory(boto3.resource("dynamodb", config=config).Table(os.environ["HS_HISTORY_TABLE"]))


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
        if doc_type is None:
            return None, "뼈대에서는 doc_type이 필요합니다 (자동 분류는 Spec 1)"
        if doc_type not in ALLOWED_DOC_TYPES:
            return None, f"doc_type은 {sorted(ALLOWED_DOC_TYPES)} 중 하나입니다"
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
def create_job(body) -> dict:
    files, problem = _validate_files(body)
    if problem:
        return _error(400, problem)
    from agent.document_agent import run_job

    job_id = f"job-{uuid.uuid4().hex[:8]}"
    save_job(Job(job_id=job_id, status="running"))
    started = time.perf_counter()
    try:
        job = run_job(job_id, files, fetch_object)
    except Exception as exc:  # 예상 못 한 오류도 작업 상태로 남긴다
        print(f"[error] job={job_id} {type(exc).__name__}: {exc}")
        job = Job(job_id=job_id, status="failed", error=f"{type(exc).__name__}: {exc}")
    print(f"[job] {job_id} status={job.status} {time.perf_counter() - started:.1f}초")
    save_job(job)
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

    언제: 화면에서 '사람 확인 필요' 품목의 HS를 고른 뒤 (agent-design.md 6번). 모델 호출 없음.
    받는 것: {"choices": [{"line", "hs"}]}. line은 이 작업의 HS 결과에 있는 행, hs는 10자리.
    반환: 200 {"declaration_draft"} / 400 요청 형식 / 404 없는 작업 / 409 처리 중이거나 서류 기록이 없음.
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
    context = load_job_docs(item)
    if context is None:
        return _error(409, "이 작업에는 저장된 서류 기록이 없어 신고서 초안을 다시 채울 수 없습니다")
    docs, importer = context
    line_docs = {line: _line_doc(docs, line) for line in picked}
    missing = sorted(line for line, doc in line_docs.items() if doc is None)
    if missing:
        return _error(409, f"서류 기록에 {missing}행이 없습니다")

    # 모두 검사한 뒤에 이력을 쓴다 (요청이 틀렸는데 이력만 남는 일을 막는다)
    history = _hs_history()
    for line, code in picked.items():
        print(f"[api] confirm_by_human job={job_id} line={line} hs={code}")
        key = hs.item_key(line_docs[line], line)
        results[line] = hs.confirm_by_human(results[line], code, importer, key, job_id, history=history)
    job.result.hs = [results[r.line] for r in job.result.hs]
    draft = declaration.draft_declaration(docs, job.result.issues, job.result.hs)
    job.result.declaration_draft = draft
    chosen = ", ".join(f"{line}행 {code}" for line, code in picked.items())
    job.steps.append(Step(tool="confirm_by_human", summary=f"사람 확정: {chosen}", ok=True))
    job.steps.append(
        Step(tool="draft_declaration", summary=f"신고서 초안 {len(draft.fields)}칸, 비운 칸 {len(draft.blank_fields)}개", ok=True)
    )
    save_job(job, keep=item)
    return _response(200, {"declaration_draft": draft.model_dump(mode="json")})


def _wms_body(state: WmsState) -> dict:
    """승인 응답 (약속 2). by는 넣지 않는다. 화면은 GET /jobs/{id}의 result.wms에서 by를 읽는다."""
    return {"wms": {"status": state.status, "wms_id": state.wms_id}}


def approve_job(job_id: str, body) -> dict:
    """POST /jobs/{id}/approve. 사람이 승인하면 가상 WMS에 등록하고(by=human) 작업을 끝낸다.

    언제: '확인 필요'가 남은 건을 사람이 화면에서 보고 승인할 때 (agent-design.md 8번 예외). 모델 호출 없음.
    받는 것: {"approver"}: 승인자 이름. 공백만이면 안 되고 50자까지. 단계 기록에 남긴다.
    반환: 200 {"wms": {"status", "wms_id"}} / 400 요청 형식 / 404 없는 작업
      / 409 {"error"}: 불일치가 남음, 승인 대기 중이 아님, 서류 기록이 없음, B/L 번호·수하인이 없어 기록을 못 만듦
      / 502 가상 WMS 저장 실패 (작업은 그대로라 다시 승인하면 된다).
    이미 등록된 작업이면 다시 등록하지 않고 그 상태를 돌려준다. WMS 쪽도 멱등 키라 재시도해도 한 번만 들어간다.
    저장: result.wms = {등록됨, human, wms_id}, status = done, steps에 push_to_wms 한 줄.
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
    try:
        record = wms.make_record(job_id, docs, job.result.hs, importer, "human")
    except wms.RecordNotReady as exc:
        return _error(409, str(exc))

    print(f"[api] approve job={job_id}")
    try:
        state = wms.push_to_wms(record, adapter=wms.dynamo_wms())
    except (BotoCoreError, ClientError) as exc:
        print(f"[error] WMS 등록 실패 job={job_id} {type(exc).__name__}: {exc}")
        return _error(502, "가상 WMS에 등록하지 못했습니다. 잠시 뒤 다시 승인해 주세요 (같은 건은 한 번만 들어갑니다)")
    job.result.wms = state
    job.status = "done"
    job.steps.append(Step(tool="push_to_wms", summary=f"사람 승인({approver})으로 WMS 등록: {state.wms_id}", ok=True))
    save_job(job, keep=item)
    return _response(200, _wms_body(state))


# 약속 2에 있지만 아직 없는 경로 → 작업 ID (e2e-plan.md). 만들면 여기서 지운다.
_PLANNED = {
    ("POST", "/uploads"): "F2",
    ("POST", "/chat"): "E5",
}


def _planned_route(method: str, path: str) -> str | None:
    parts = path.split("/")
    if len(parts) == 4 and parts[1] == "jobs":
        path = f"/jobs/{{id}}/{parts[3]}"
    return _PLANNED.get((method, path))


def lambda_handler(event, context):
    """Function URL 요청을 경로별로 나눈다."""
    http = event.get("requestContext", {}).get("http", {})
    method, path = http.get("method", "GET"), event.get("rawPath", "/").rstrip("/") or "/"
    print(f"[api] {method} {path}")
    try:
        if method == "GET" and path == "/":
            return _response(200, {"ok": True})
        if method == "POST" and path == "/jobs":
            return create_job(_body(event))
        if method == "GET" and path.startswith("/jobs/") and path.count("/") == 2:
            return get_job(path.split("/")[2])
        parts = path.split("/")
        if method == "POST" and len(parts) == 4 and parts[1] == "jobs" and parts[3] == "hs":
            return choose_hs(parts[2], _body(event))
        if method == "POST" and len(parts) == 4 and parts[1] == "jobs" and parts[3] == "approve":
            return approve_job(parts[2], _body(event))
        planned = _planned_route(method, path)
        if planned:
            return _error(501, f"아직 만들지 않은 경로입니다 ({planned}). 형식은 docs/schema.md 약속 2")
        return _error(404, "없는 경로입니다")
    except json.JSONDecodeError:
        return _error(400, "본문이 JSON이 아닙니다")
    except Exception as exc:
        print(f"[error] {type(exc).__name__}: {exc}")
        return _error(500, "서버 오류")
