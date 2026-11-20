"""처리 Lambda team06-worker 진입점. 담당: 서버. 형식: docs/schema.md 약속 2, 이벤트 약속: 이슈 #36

API Lambda(api/handler.py의 POST /jobs)가 작업을 queued로 저장한 뒤 이 함수를 비동기로(InvocationType=Event) 부른다.
    받는 이벤트: {"job_id": "job-xxxxxxxx", "files": [{"key", "doc_type"}]}
    하는 일: running으로 바꾸고 run_job을 돌린다. 단계가 늘 때마다 저장해 화면 진행 단계에 보이고,
            끝나면 waiting_approval · done · failed로 저장한다.
            HS는 recommend_hs(C1·C2)로 품목마다 추천한다 (모델 없이 품명 검색, 확정 이력은 team06-hs-history).
            마지막 저장 때 읽은 서류(docs)와 수입자(importer)를 같은 줄에 넣는다. HS 선택(C3)·승인(D3)이 읽는다 (#122).
            waiting_approval·done이고 읽은 서류가 있으면 마지막 저장 직전에 차례로 한다 (#154):
              1. 신고서 초안을 채운다 (C5 draft_declaration). 문제가 남은 칸과 확정 안 된 HS 칸은 비운다
              2. done이면 가상 WMS에 자동 등록한다 (D2, by=auto). 못 하면 waiting_approval로 바꿔 사람이 승인한다 (D3)
              3. 화물 기록(team06-shipments)에 한 줄을 쓴다 (E3, #31). 2에서 등록됐으면 처음부터 '수입신고'다
            waiting_approval이면 result.wms를 '승인 대기'로 채워 저장한다. 화면이 승인 입력을 그린다 (#159).
제한 시간 300초. 환경 변수: JOBS_TABLE, DOCS_BUCKET, MODEL_ID, HS_HISTORY_TABLE, SHIPMENTS_TABLE, WMS_TABLE

비동기 호출은 함수가 오류·시간 초과로 끝나면 Lambda가 같은 이벤트를 다시 보낸다. 그래서 저장된 상태를 보고 한 번만 처리한다.
    queued   → 처리한다
    running  → 앞선 실행이 끝을 못 냈다(시간 초과 등). 다시 돌리면 같은 이유로 멈추고 모델 호출만 늘어서 failed로 끝낸다
    그 밖    → 이미 끝난 작업이다. 아무것도 하지 않는다
"""

import time
from functools import cache

from api import handler
from tools import declaration, hs, report
from tools.models import ExtractedDocument, HSResult, Job, Step, WmsState
from tools.query import dynamo_shipments

INTERRUPTED = "처리가 중간에 멈췄습니다 (시간 초과 등). 서류를 다시 올려 주세요"
# done인데 자동 등록 조건을 못 채웠을 때 단계 기록에 남기는 이유 (register_if_ready는 조건 미달에 이유를 붙이지 않는다)
NOT_READY = "자동 등록 조건(남은 문제 없음, 모든 품목 HS 확정)을 채우지 못했습니다. 승인하면 등록합니다"


def _save(job: Job, item: dict) -> None:
    """작업을 저장한다. item(team06-jobs 한 줄)의 다른 칸은 그대로 둔다."""
    handler.save_job(job, keep=item)


def importer_of(docs: list[ExtractedDocument]) -> str | None:
    """수입자 = 상업송장의 consignee_name raw (docs/schema.md 신고서 '수입자' 출처). 앞뒤 공백만 뗀다.

    언제: HS 이력을 찾을 때, 마지막 저장 때 importer 칸을 채울 때.
    받는 것: 읽은 서류 목록. 상업송장이 여럿이면 값이 있는 첫 서류를 쓴다.
    반환: 수입자 글자. 상업송장이 없거나 그 칸을 못 읽었으면 None.
      consignee_name 칸은 #110(B2 P1)이 약속 1에 더한다. 그 전에는 칸이 없어 늘 None이다.
    """
    for doc in docs:
        if doc.doc_type != "commercial_invoice":
            continue
        cell = getattr(doc, "consignee_name", None)  # #110 전에는 칸이 없다
        raw = (cell.raw or "").strip() if cell is not None else ""
        if raw:
            return raw
    return None


class _NoHistory:
    """수입자를 모를 때 쓰는 빈 확정 이력 (tools.hs.HSHistory 모양).

    DynamoDB 키에 빈 글자를 넣을 수 없고, 다른 수입자의 이력과 섞이면 안 되어서 찾지도 쓰지도 않는다.
    """

    def get(self, importer: str, item_key: str) -> str | None:
        return None

    def put(self, importer: str, item_key: str, hs: str, job_id: str) -> None:
        return None


@cache
def _hs_table() -> hs.CsvHSTable:
    """HS부호 표(data/hs/hs_codes.csv). Lambda 실행 환경마다 처음 한 번만 읽는다."""
    return hs.load_hs_table()


def recommend_line(docs: list[ExtractedDocument], line: int) -> HSResult:
    """run_job에 넘기는 hs_recommender. 품목 한 행의 HS를 recommend_hs로 추천한다.

    언제: run_job이 품목 행마다 부른다. 모델(terms_reader·picker)은 넘기지 않아 품명 검색만 한다.
    받는 것: docs(읽은 서류, files 순서), line(품목 행).
    반환: HSResult. 수입자를 알면 그 수입자의 확정 이력(team06-hs-history)을 쓰고, 모르면 빈 이력으로 부른다.
    """
    importer = importer_of(docs)
    history = handler._hs_history() if importer else _NoHistory()
    return hs.recommend_hs(docs, line, importer or "", history=history, table=_hs_table())


def _docs_columns(docs: list[ExtractedDocument]) -> dict:
    """마지막 저장 때 같은 줄에 더할 칸. docs는 handler._DOCS 모양(load_job_docs가 읽는다).

    읽은 서류가 없으면 빈 dict. 수입자를 모르면 importer 칸은 쓰지 않는다.
    """
    if not docs:
        return {}
    columns = {"docs": handler._DOCS.dump_json(docs).decode("utf-8")}
    importer = importer_of(docs)
    if importer:
        columns["importer"] = importer
    return columns


def _draft(job: Job, docs: list[ExtractedDocument]) -> None:
    """처리 직후 신고서 초안을 채우고 단계 한 줄을 더한다 (C8 #154, tools/declaration.draft_declaration).

    언제: 마지막 저장 직전, 작업이 waiting_approval·done이고 읽은 서류가 있을 때. 자동 등록(_register)보다 먼저.
    받는 것: run_job이 돌려준 Job(그 자리에서 고친다), docs(읽은 서류). 모델은 부르지 않는다.
    남은 문제(불일치·확인 필요)가 짚은 칸과 확정 안 된 HS 칸은 비우고 blank_fields에 적는다 (agent-design.md 7번).
    run_job이 초안을 이미 채웠으면 그대로 둔다. 사람이 HS를 고르면 POST /jobs/{id}/hs가 다시 채운다.
    예외를 내지 않는다. 못 만들면 ok=False 한 줄만 남기고 작업은 그대로 끝난다 (running으로 남지 않게).
    """
    if job.result is None or job.result.declaration_draft is not None:
        return
    try:
        draft = declaration.draft_declaration(docs, job.result.issues, job.result.hs)
    except Exception as exc:
        print(f"[error] draft_declaration job={job.job_id} {type(exc).__name__}: {exc}")
        job.steps.append(Step(tool="draft_declaration", summary=f"신고서 초안을 만들지 못함: {type(exc).__name__}", ok=False))
        return
    job.result.declaration_draft = draft
    job.steps.append(handler.draft_step(draft))


def _register(job: Job, docs: list[ExtractedDocument]) -> bool:
    """done으로 끝난 작업을 사람 손 없이 바로 가상 WMS에 등록한다 (D2 자동 등록 #154, handler.auto_register).

    언제: 마지막 저장 직전, 초안 뒤·화물 기록 앞. 작업이 done이고 읽은 서류가 있을 때.
    받는 것: run_job이 돌려준 Job(그 자리에서 고친다), docs(읽은 서류). 수입자는 importer_of(docs).
    반환: WMS에 등록된 상태면 True. 화물 기록을 처음부터 '수입신고'로 쓰는 데 쓴다 (E3).
      done이 아니면 아무것도 하지 않고 False (승인 대기는 _mark_waiting, HS를 고른 뒤 재검사는 choose_hs가 한다).
    등록하지 못하면(HS 결과 없음, B/L·수입자 없음, 가상 WMS 오류) waiting_approval로 바꾸고 result.wms = 승인 대기.
      승인(D3)은 승인 대기 작업만 받아서, done으로 두면 아무도 등록할 수 없다. 이유는 push_to_wms ok=False 한 줄.
    저장보다 등록을 먼저 한다. 화면은 waiting_approval·done을 받으면 새로 고침을 멈춰서, 승인 대기로 먼저 저장하면
      등록된 뒤에도 승인 대기로 보인다. 등록 뒤 마지막 저장이 실패하면 Lambda가 다시 보낸 이벤트에서 failed로 끝나고,
      WMS에는 그 작업 ID의 기록이 남는다 (멱등 키 "B/L#작업 ID"라 같은 작업은 두 번 들어가지 않는다).
    """
    if job.status != "done" or job.result is None:
        return False
    steps = len(job.steps)
    handler.auto_register(job, docs, importer_of(docs))
    wms_state = job.result.wms
    print(f"[worker] job={job.job_id} 자동 등록 wms={wms_state.status} wms_id={wms_state.wms_id}")
    if wms_state.status == "등록됨":
        return True
    job.status = "waiting_approval"
    if len(job.steps) == steps:  # 조건 미달이라 이유가 붙지 않았다. 왜 사람이 봐야 하는지 남긴다
        job.steps.append(Step(tool="push_to_wms", summary=f"WMS 자동 등록 못 함: {NOT_READY}", ok=False))
    return False


def _record_shipment(job_id: str, docs: list[ExtractedDocument], *, registered: bool = False) -> Step:
    """작업이 끝나면 화물 기록에 한 줄을 쓰고 그 단계 한 줄을 돌려준다 (E3, tools/report.record_shipment).

    언제: 마지막 저장 직전, 작업이 waiting_approval·done이고 읽은 서류가 있을 때. 자동 등록(_register) 뒤.
    받는 것: job_id, docs(읽은 서류), registered(방금 WMS에 자동 등록됐으면 True. 그러면 처음부터 '수입신고'로 쓴다).
    반환: Step. 예외를 내지 않는다. 저장소를 못 만들어도(SHIPMENTS_TABLE 없음 등) ok=False 한 줄만 남기고,
      작업은 그대로 끝난다 (여기서 예외가 나면 마지막 저장을 못 해 running으로 남는다).
    """
    try:
        store = dynamo_shipments()
    except Exception as exc:
        print(f"[error] {report.RECORD_TOOL} job={job_id} {type(exc).__name__}: {exc}")
        return Step(tool=report.RECORD_TOOL, summary=f"화물 기록을 쓰지 못함: {type(exc).__name__}", ok=False)
    return report.record_shipment(job_id, docs, store, registered=registered)


def _mark_waiting(job: Job) -> None:
    """승인 대기로 끝난 작업에 result.wms = 승인 대기를 넣는다 (#159).

    언제: 마지막 저장 직전. 화면은 result.wms.status가 '승인 대기'일 때만 승인 입력을 그린다(WmsPanel).
    받는 것: run_job이 돌려준 Job. 그 자리에서 고친다.
    waiting_approval이 아니거나 wms가 이미 있으면(등록됨 등) 그대로 둔다. done의 자동 등록은 _register가 한다 (#154).
    """
    if job.status != "waiting_approval" or job.result is None or job.result.wms is not None:
        return
    job.result.wms = WmsState(status="승인 대기")


def lambda_handler(event, context):
    """작업 하나를 처리한다.

    언제: API Lambda가 POST /jobs에서 비동기로 부를 때. 직접 부를 일은 없다 (aws lambda invoke로 시험할 때만).
    받는 것: event {"job_id", "files"}. context는 쓰지 않는다.
    반환: {"job_id", "status"} (로그와 시험용. 비동기 호출에서는 아무도 받지 않는다).
      이벤트가 틀렸거나 작업이 없으면 status는 null이고 아무것도 저장하지 않는다.
    """
    job_id = event.get("job_id") if isinstance(event, dict) else None
    if not isinstance(job_id, str) or not handler.JOB_ID.match(job_id):
        print(f"[error] worker 이벤트에 job_id가 없거나 형식이 다릅니다: {str(job_id)[:40]!r}")
        return {"job_id": None, "status": None}
    item = handler._load_item(job_id)
    if item is None:
        print(f"[error] worker job={job_id} 작업이 테이블에 없습니다")
        return {"job_id": job_id, "status": None}
    job = Job.model_validate_json(item["data"])
    if job.status == "running":
        print(f"[warn] worker job={job_id} 이미 running. 앞선 실행이 멈춘 것으로 보고 failed로 끝낸다")
        _save(Job(job_id=job_id, status="failed", steps=job.steps, error=INTERRUPTED), item)
        return {"job_id": job_id, "status": "failed"}
    if job.status != "queued":
        print(f"[worker] job={job_id} 이미 {job.status}. 다시 처리하지 않는다")
        return {"job_id": job_id, "status": job.status}

    files, problem = handler._validate_files({"files": event.get("files")})
    if problem:  # API가 검사한 값이라 여기 올 일은 없다. 그래도 queued로 두지 않는다
        print(f"[error] worker job={job_id} files: {problem}")
        _save(Job(job_id=job_id, status="failed", error=f"요청한 서류 목록이 잘못됐습니다: {problem}"), item)
        return {"job_id": job_id, "status": "failed"}

    from agent.document_agent import run_job

    _save(Job(job_id=job_id, status="running"), item)
    print(f"[worker] job={job_id} 시작 files={len(files)}")
    latest = Job(job_id=job_id, status="running")  # 마지막으로 저장한 진행 상태. 실패해도 단계 기록을 남기려고 둔다
    read: list[ExtractedDocument] = []  # run_job이 on_docs로 한 번 넘긴다 (실패해도 그때까지 읽은 서류)

    def on_step(progress: Job) -> None:
        nonlocal latest
        latest = progress
        _save(progress, item)

    started = time.perf_counter()
    try:
        result = run_job(
            job_id, files, handler.fetch_object, on_step=on_step, hs_recommender=recommend_line, on_docs=read.extend
        )
    except Exception as exc:  # 예상 못 한 오류도 작업 상태로 남긴다 (Lambda가 다시 돌리지 않게 여기서 끝낸다)
        print(f"[error] worker job={job_id} {type(exc).__name__}: {exc}")
        result = Job(job_id=job_id, status="failed", steps=latest.steps, error=f"{type(exc).__name__}: {exc}")
    print(f"[job] {job_id} status={result.status} {time.perf_counter() - started:.1f}초")
    if result.status in ("waiting_approval", "done") and read:  # 실패한 작업은 초안·등록·화물 기록을 하지 않는다
        _draft(result, read)
        registered = _register(result, read)
        result.steps.append(_record_shipment(job_id, read, registered=registered))
    _mark_waiting(result)
    columns = _docs_columns(read)
    print(f"[worker] job={job_id} 서류 기록 docs={len(read)} importer={'있음' if 'importer' in columns else '없음'}")
    _save(result, {**item, **columns})
    return {"job_id": job_id, "status": result.status}
