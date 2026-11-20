"""처리 Lambda team06-worker 진입점. 담당: 서버. 형식: docs/schema.md 약속 2, 이벤트 약속: 이슈 #36

API Lambda(api/handler.py의 POST /jobs)가 작업을 queued로 저장한 뒤 이 함수를 비동기로(InvocationType=Event) 부른다.
    받는 이벤트: {"job_id": "job-xxxxxxxx", "files": [{"key", "doc_type"}]}
    하는 일: running으로 바꾸고 run_job을 돌린다. 단계가 늘 때마다 저장해 화면 진행 단계에 보이고,
            끝나면 waiting_approval · done · failed로 저장한다.
제한 시간 300초. 환경 변수: JOBS_TABLE, DOCS_BUCKET, MODEL_ID (도구에 따라 HS_HISTORY_TABLE, WMS_TABLE)

비동기 호출은 함수가 오류·시간 초과로 끝나면 Lambda가 같은 이벤트를 다시 보낸다. 그래서 저장된 상태를 보고 한 번만 처리한다.
    queued   → 처리한다
    running  → 앞선 실행이 끝을 못 냈다(시간 초과 등). 다시 돌리면 같은 이유로 멈추고 모델 호출만 늘어서 failed로 끝낸다
    그 밖    → 이미 끝난 작업이다. 아무것도 하지 않는다
"""

import time

from api import handler
from tools.models import Job

INTERRUPTED = "처리가 중간에 멈췄습니다 (시간 초과 등). 서류를 다시 올려 주세요"


def _save(job: Job, item: dict) -> None:
    """작업을 저장한다. item(team06-jobs 한 줄)의 다른 칸은 그대로 둔다."""
    handler.save_job(job, keep=item)


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

    def on_step(progress: Job) -> None:
        nonlocal latest
        latest = progress
        _save(progress, item)

    started = time.perf_counter()
    try:
        result = run_job(job_id, files, handler.fetch_object, on_step=on_step)
    except Exception as exc:  # 예상 못 한 오류도 작업 상태로 남긴다 (Lambda가 다시 돌리지 않게 여기서 끝낸다)
        print(f"[error] worker job={job_id} {type(exc).__name__}: {exc}")
        result = Job(job_id=job_id, status="failed", steps=latest.steps, error=f"{type(exc).__name__}: {exc}")
    print(f"[job] {job_id} status={result.status} {time.perf_counter() - started:.1f}초")
    _save(result, item)
    return {"job_id": job_id, "status": result.status}
