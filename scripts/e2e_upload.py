"""배포된 주소로 화면과 같은 순서를 끝까지 한 번 돌린다. 담당: PM (F6 배포 점검)

순서: POST /api/uploads → 받은 URL로 S3에 PUT → POST /api/jobs (doc_type null, 자동 분류) → GET /api/jobs/{id}를 끝날 때까지.
AWS 자격 증명을 쓰지 않고 공개 주소(CloudFront)만 부른다. 화면이 하는 일과 같다.

실행: uv run python -m scripts.e2e_upload https://<CloudFront 주소> samples/dev/D003/doc_a.pdf samples/dev/D003/doc_b.pdf
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


def main() -> None:
    base, paths = sys.argv[1].rstrip("/"), [Path(p) for p in sys.argv[2:]]
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


if __name__ == "__main__":
    main()
