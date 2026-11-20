"""10회 반복 측정 (H4). 담당: 판독. 규칙: .kiro/steering/agent-design.md 11번

같은 세트를 캐시를 끄고(NO_CACHE=1, READ_CACHE_BUCKET 뺌) 확정 이력을 비운 채 N번 run_job으로 돌려 판정이 매번 같은지 본다.
판정 = 작업 상태 + 문제(rule_id, 등급, 짚은 칸) + 서류 종류 + HS 결과(행, 상태, 코드). 근거 문장·시간은 비교하지 않는다.
HS는 매번 빈 이력과 HS부호 표로 recommend_hs를 붙인다 (모델 없이 이력·표 후보만 돈다).

    MODEL_ID=... uv run python -m eval.repeat [--only D003 D005] [--times 10] [--out build/repeat_dev.json]
    uv run python -m eval.repeat --rescore build/repeat_dev.json    # 저장한 판정으로 다시 요약 (모델 호출 없음)
"""

import argparse
import csv
import json
import os
import time
from collections import Counter
from pathlib import Path

from eval.score import EVAL_DIR
from tools.models import ExtractedDocument, Job

ROOT = EVAL_DIR.parent
DEV = ROOT / "samples" / "dev"
READ_TYPES = ("commercial_invoice", "packing_list")
DEFAULT_SETS = ["D003", "D007", "D005", "D020"]  # 심은 오류 PDF · 심은 오류 스캔본 · 정상 · 정상(송장 번호 표기만 다름)


class EmptyHistory:
    """빈 확정 이력. 반복마다 새로 만들어 앞 실행의 확정이 다음 실행에 섞이지 않게 한다."""

    def __init__(self):
        self.saved: dict[tuple[str, str], str] = {}

    def get(self, importer: str, item_key: str) -> str | None:
        return self.saved.get((importer, item_key))

    def put(self, importer: str, item_key: str, hs: str, job_id: str) -> None:
        self.saved[(importer, item_key)] = hs


def load_sets(only: list[str]) -> dict[str, dict]:
    """세트 → {"files": [(경로, 정답 종류)], "consignee"}. 상업송장·포장명세서만 (P0)."""
    found: dict[str, dict] = {}
    with (EVAL_DIR / "sets.csv").open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            sid = r["set_id"]
            if r["split"] != "dev" or sid not in only or sid in found:
                continue
            kv = dict(part.split("=", 1) for part in r["docs"].split(";"))
            files = []
            for slot in "abcd":
                if kv.get(f"doc_{slot}") in READ_TYPES:
                    [path] = sorted((DEV / sid).glob(f"doc_{slot}.*"))
                    files.append((str(path.relative_to(ROOT)), kv[f"doc_{slot}"]))
            found[sid] = {"files": files, "consignee": r["consignee"]}
    missing = [s for s in only if s not in found]
    if missing:
        raise SystemExit(f"개발용 세트가 아닙니다: {missing}")
    return found


def verdict(job: Job, doc_types: dict[str, str]) -> dict:
    """비교할 판정만 뽑는다. 순서가 바뀌어도 같게 정렬한다."""
    result = job.result
    issues = sorted(
        [i.rule_id, i.grade, sorted(f"{c.doc}:{c.field}" for c in i.cells)] for i in (result.issues if result else [])
    )
    hs = sorted([h.line, h.status, h.hs_code] for h in (result.hs if result else []))
    return {"status": job.status, "doc_types": doc_types, "issues": issues, "hs": hs, "error": job.error}


def run_once(sid: str, spec: dict, n: int) -> dict:
    from agent.document_agent import run_job
    from tools.hs import load_hs_table, recommend_hs

    history, table = EmptyHistory(), load_hs_table()  # 반복마다 이력을 비운다

    def hs_recommender(docs: list[ExtractedDocument], line: int):
        return recommend_hs(docs, line, spec["consignee"], history=history, table=table)

    files = [{"key": key, "doc_type": None} for key, _ in spec["files"]]
    started = time.perf_counter()
    job = run_job(f"job-{sid.lower()}-{n}", files, lambda key: (ROOT / key).read_bytes(), hs_recommender=hs_recommender)
    seconds = round(time.perf_counter() - started, 1)
    doc_types = {}
    for step in job.steps:  # 분류 결과는 단계 기록에만 있다: "doc_a.pdf → 상업송장 (...)"
        if step.tool == "classify_document":
            name, _, rest = step.summary.partition(" → ")
            doc_types[name] = rest.split(" (")[0] or "?"
    return {"seconds": seconds, "verdict": verdict(job, doc_types)}


def summarize(runs: dict[str, list[dict]]) -> list[str]:
    lines = []
    for sid, rs in runs.items():
        seen = Counter(json.dumps(r["verdict"], ensure_ascii=False, sort_keys=True) for r in rs)
        top, count = seen.most_common(1)[0]
        secs = sorted(r["seconds"] for r in rs)
        v = json.loads(top)
        issues = ", ".join(f"{rule}({grade})" for rule, grade, _ in v["issues"]) or "문제 없음"
        lines.append(
            f"- {sid}: {len(rs)}번 중 {count}번 같은 판정, 판정 {len(seen)}가지 · 가장 많은 판정 = {v['status']}, {issues}, "
            f"HS {len(v['hs'])}행 · {secs[0]}~{secs[-1]}초"
        )
        if len(seen) > 1:
            for other, c in seen.most_common()[1:]:
                lines.append(f"    다른 판정 {c}번: {other[:300]}")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description="10회 반복 측정 (H4, 개발용만)")
    parser.add_argument("--only", nargs="+", default=DEFAULT_SETS, help=f"세트 ID (기본 {' '.join(DEFAULT_SETS)})")
    parser.add_argument("--times", type=int, default=10)
    parser.add_argument("--out", default=str(ROOT / "build" / "repeat_dev.json"))
    parser.add_argument("--rescore", help="저장한 판정으로 다시 요약 (모델 호출 없음)")
    args = parser.parse_args()

    if args.rescore:
        runs = json.loads(Path(args.rescore).read_text(encoding="utf-8"))
    else:
        os.environ["NO_CACHE"] = "1"  # 판독 캐시를 끈다 (B3). 버킷도 빼서 어떤 경우에도 캐시를 보지 않게 한다
        os.environ.pop("READ_CACHE_BUCKET", None)
        sets = load_sets(args.only)
        runs: dict[str, list[dict]] = {}
        for sid, spec in sets.items():
            runs[sid] = []
            for n in range(1, args.times + 1):
                r = run_once(sid, spec, n)
                runs[sid].append(r)
                print(f"[repeat] {sid} {n}/{args.times} {r['verdict']['status']} {r['seconds']}초")
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(runs, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[repeat] 판정 저장: {out}")
    print()
    print("10회 반복 (캐시 끔, 확정 이력 비움, doc_type 비워 분류부터)")
    print("\n".join(summarize(runs)))


if __name__ == "__main__":
    main()
