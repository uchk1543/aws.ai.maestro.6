"""배포된 주소로 화면과 같은 순서를 끝까지 한 번 돌린다. 담당: PM (F6 배포 점검)

순서: POST /api/uploads → 받은 URL로 S3에 PUT → POST /api/jobs (doc_type null, 자동 분류) → GET /api/jobs/{id}를 끝날 때까지.
AWS 자격 증명을 쓰지 않고 공개 주소(CloudFront)만 부른다. 화면이 하는 일과 같다.

실행: uv run python -m scripts.e2e_upload https://<CloudFront 주소> samples/dev/D003/doc_a.pdf samples/dev/D003/doc_b.pdf
  --choose            사람 확인 필요 HS 행마다 정답지(eval/sets.csv)의 정답 HS를 사람이 고른 것처럼 POST /api/jobs/{id}/hs.
                      정답을 모르는 행(세트 폴더가 아닌 파일)은 고르지 않는다. 고른 HS는 확정 이력에 남는다 (#160)
                      시험 뒤에는 infra/reset_demo.py --job <job_id> 로 지운다
  --approve <이름>    이어서 POST /api/jobs/{id}/approve (WMS 등록)
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

CONTENT_TYPES = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
TIMEOUT = 30  # 요청 하나의 시간 한도(초). API Gateway 한도와 같다
WAIT_SECONDS = 300  # 처리 Lambda 제한 시간과 같다


def _call(method: str, url: str, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
            return res.status, json.loads(res.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def _put(url: str, data: bytes, content_type: str) -> int:
    req = urllib.request.Request(url, data=data, method="PUT", headers={"content-type": content_type})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
        return res.status


SETS_CSV = Path(__file__).resolve().parents[1] / "eval" / "sets.csv"


def answer_hs(set_id: str | None, sets_csv: Path = SETS_CSV) -> dict[int, str]:
    """정답지의 품목별 HS (eval/sets.csv hs_answer). 세트를 모르면 빈 dict.

    --choose는 이 값만 고른다. 후보 1순위를 고르면 틀린 HS가 확정 이력에 남아 다음 자동 확정이 틀린다 (#160).
    """
    import csv

    if not set_id or not sets_csv.exists():
        return {}
    with sets_csv.open(encoding="utf-8", newline="") as fh:
        return {int(r["line"]): r["hs_answer"] for r in csv.DictReader(fh) if r["set_id"] == set_id and r["hs_answer"]}


def choices(hs: list[dict], answers: dict[int, str]) -> tuple[list[dict], list[int]]:
    """사람 확인 필요 행 중 정답 HS를 아는 행만 고른다. 반환: (고를 것, 정답을 몰라 건너뛴 행)."""
    waiting = [h["line"] for h in hs if h["status"] == "사람 확인 필요"]
    return [{"line": n, "hs": answers[n]} for n in waiting if n in answers], [n for n in waiting if n not in answers]


def _after(base: str, job: dict, choose: bool, approver: str | None, set_id: str | None = None) -> None:
    """HS 고르기(C3)와 승인(D3)을 화면처럼 부른다."""
    job_id, hs = job["job_id"], (job.get("result") or {}).get("hs", [])
    if choose:
        picks, skipped = choices(hs, answer_hs(set_id))
        if skipped:
            print(f"[e2e] 정답 HS를 몰라 고르지 않은 행 {skipped} (세트 {set_id or '모름'}). 확정 이력을 더럽히지 않으려고 1순위를 고르지 않는다")
        if picks:
            status, body = _call("POST", f"{base}/api/jobs/{job_id}/hs", {"choices": picks})
            filled = len((body.get("declaration_draft") or {}).get("fields", []))
            print(f"[e2e] POST /hs {picks} → {status} {body.get('error') or f'신고서 초안 {filled}칸'}")
    if approver:
        status, body = _call("POST", f"{base}/api/jobs/{job_id}/approve", {"approver": approver})
        print(f"[e2e] POST /approve → {status} {body.get('error') or body.get('wms')}")
        print(f"[e2e] 작업 상태 → {_call('GET', f'{base}/api/jobs/{job_id}')[1].get('status')}")


def main() -> None:
    args = sys.argv[1:]
    choose = "--choose" in args
    approver = args[args.index("--approve") + 1] if "--approve" in args else None
    args = [a for a in args if a not in ("--choose", "--approve", approver)]
    base, paths = args[0].rstrip("/"), [Path(p) for p in args[1:]]
    files = [{"name": p.name, "content_type": CONTENT_TYPES[p.suffix.lower()]} for p in paths]
    status, body = _call("POST", f"{base}/api/uploads", {"files": files})
    print(f"[e2e] POST /api/uploads → {status}")
    if status != 200:
        raise SystemExit(f"업로드 URL을 받지 못함: {body}")
    for path, f, up in zip(paths, files, body["uploads"]):
        print(f"[e2e] PUT {up['key']} → {_put(up['url'], path.read_bytes(), f['content_type'])}")
    keys = [{"key": up["key"], "doc_type": None} for up in body["uploads"]]
    status, body = _call("POST", f"{base}/api/jobs", {"files": keys})
    print(f"[e2e] POST /api/jobs → {status} {body}")
    if status != 200:
        raise SystemExit("작업을 만들지 못함")
    job_id, started, last = body["job_id"], time.monotonic(), None
    while time.monotonic() - started < WAIT_SECONDS:
        status, job = _call("GET", f"{base}/api/jobs/{job_id}")
        if job.get("status") != last:
            last = job.get("status")
            print(f"[e2e] {time.monotonic() - started:5.1f}초 status={last} 단계 {len(job.get('steps') or [])}개")
        if last in ("waiting_approval", "done", "failed"):
            break
        time.sleep(2)
    for s in job.get("steps") or []:
        print(f"  - {s['tool']}: {s['summary']}{'' if s.get('ok', True) else ' (실패)'}")
    result = job.get("result") or {}
    for i in result.get("issues", []):
        print(f"  [문제] {i['grade']} {i['rule_id']}: {i['evidence']}")
    for h in result.get("hs", []):
        print(f"  [HS] {h['line']}행 {h['status']} {h.get('hs_code') or [c['hs'] for c in h.get('candidates', [])]}")
    if job.get("error"):
        print(f"  [오류] {job['error']}")
    if last == "waiting_approval":
        set_id = paths[0].parent.name if paths and paths[0].parent.name.startswith("D") else None  # samples/dev/D005/…
        _after(base, job, choose, approver, set_id)


if __name__ == "__main__":
    main()
