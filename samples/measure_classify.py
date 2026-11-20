"""분류 정확도 측정 (B1). 담당: 판독. 규칙: .kiro/steering/agent-design.md 11번 '분류: 서류 종류 정답 수'

개발용 서류(samples/dev)를 classify_document로 분류해 eval/sets.csv 의 docs 칸(정답)과 맞춰 본다.
발표용(samples/test, eval/test)은 열지 않는다. Bedrock을 서류 한 장에 한 번 부른다.

실행:
    export MODEL_ID=<global 추론 프로필 ID>
    uv run python -m samples.measure_classify                 # 개발용 전체 (288장)
    uv run python -m samples.measure_classify --limit 8       # 앞에서 8장만
    uv run python -m samples.measure_classify --only D001 D002 --workers 2

출력: 형식별(pdf·png·scan)·종류별 정답 수, 틀린 것 목록, 호출 실패, 걸린 시간. 서류별 결과 CSV는 --out (기본 tmp/, git 제외).
"""

import argparse
import csv
import os
import statistics
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from tools.extract import ReadError, classify_document

ROOT = Path(__file__).resolve().parent.parent
DEV = ROOT / "samples" / "dev"
SETS = ROOT / "eval" / "sets.csv"
FORMATS = ("pdf", "png", "scan")
TYPES = ("commercial_invoice", "packing_list", "bill_of_lading", "certificate_of_origin")


def load_docs(only: set[str] | None) -> list[dict]:
    """eval/sets.csv 의 docs 칸에서 개발용 서류마다 세트, 자리, 정답 종류, 형식, 파일을 꺼낸다."""
    rows, seen = [], set()
    with SETS.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            sid = r["set_id"]
            if r["split"] != "dev" or sid in seen or (only and sid not in only):
                continue
            seen.add(sid)
            kv = dict(part.split("=", 1) for part in r["docs"].split(";"))
            for slot in "abcd":
                expected = kv.get(f"doc_{slot}")
                if not expected:
                    continue
                files = sorted((DEV / sid).glob(f"doc_{slot}.*"))
                if len(files) != 1:
                    raise SystemExit(f"{sid} doc_{slot}: 파일이 {len(files)}개입니다")
                rows.append({"set_id": sid, "slot": f"doc_{slot}", "fmt": kv[f"fmt_{slot}"],
                             "expected": expected, "style": kv.get("style", ""), "path": files[0]})
    return rows


def classify_one(row: dict) -> dict:
    started = time.perf_counter()
    try:
        result = classify_document(str(row["path"].relative_to(ROOT)), row["path"].read_bytes())
        got, reason, error = result.doc_type, result.reason, ""
    except ReadError as exc:
        got, reason, error = "", "", str(exc)
    return {**row, "got": got, "reason": reason, "error": error, "seconds": round(time.perf_counter() - started, 1)}


def report(results: list[dict], wall: float, workers: int) -> None:
    ok = [r for r in results if r["got"] == r["expected"]]
    unknown = [r for r in results if r["got"] == "unknown"]
    wrong = [r for r in results if r["got"] and r["got"] not in (r["expected"], "unknown")]
    failed = [r for r in results if r["error"]]
    n = len(results)
    print(f"\n== 분류 정확도 (개발용 {n}장, MODEL_ID={os.environ.get('MODEL_ID')}) ==")
    print(f"맞음 {len(ok)}/{n} · 다른 종류로 틀림 {len(wrong)} · unknown(사람에게) {len(unknown)} · 호출 실패 {len(failed)}")
    print("\n형식별 (맞음/전체)")
    for fmt in FORMATS:
        part = [r for r in results if r["fmt"] == fmt]
        if part:
            print(f"  {fmt:5} {sum(r['got'] == r['expected'] for r in part)}/{len(part)}")
    print("\n종류별 (맞음/전체)")
    for t in TYPES:
        part = [r for r in results if r["expected"] == t]
        if part:
            print(f"  {t:22} {sum(r['got'] == r['expected'] for r in part)}/{len(part)}")
    confusion = Counter((r["expected"], r["got"] or "실패") for r in results if r["got"] != r["expected"])
    if confusion:
        print("\n틀린 짝 (정답 → 고른 것: 건수)")
        for (exp, got), c in confusion.most_common():
            print(f"  {exp} → {got}: {c}")
    if wrong or unknown:
        print("\n틀린 것 목록")
        for r in sorted(wrong + unknown, key=lambda r: (r["set_id"], r["slot"])):
            print(f"  {r['set_id']} {r['slot']} {r['fmt']:4} {r['expected']} → {r['got']}  근거: {r['reason']}")
    if failed:
        print("\n호출 실패 (오류 전문)")
        for r in failed:
            print(f"  {r['set_id']} {r['slot']} {r['fmt']}: {r['error']}")
    secs = [r["seconds"] for r in results]
    print(f"\n시간: 한 장 평균 {statistics.mean(secs):.1f}초, 중간 {statistics.median(secs):.1f}초, "
          f"최대 {max(secs):.1f}초 / 전체 {wall:.0f}초 (동시 {workers}개)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", nargs="*", help="이 세트만 (예: D001 D002)")
    ap.add_argument("--limit", type=int, help="앞에서 이 장수만")
    ap.add_argument("--workers", type=int, default=3, help="동시 호출 수 (Bedrock 분당 한도 때문에 작게, 기본 3)")
    ap.add_argument("--out", type=Path, default=ROOT / "tmp" / "classify_dev.csv", help="서류별 결과 CSV")
    args = ap.parse_args()

    docs = load_docs(set(args.only) if args.only else None)[: args.limit]
    print(f"서류 {len(docs)}장, 동시 {args.workers}개")
    started = time.perf_counter()
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(classify_one, d) for d in docs]
        for i, fut in enumerate(as_completed(futures), 1):
            r = fut.result()
            results.append(r)
            mark = "O" if r["got"] == r["expected"] else ("실패" if r["error"] else "X")
            print(f"[{i}/{len(docs)}] {mark} {r['set_id']} {r['slot']} {r['fmt']} → {r['got'] or r['error'][:80]} ({r['seconds']}초)")
    results.sort(key=lambda r: (r["set_id"], r["slot"]))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as fh:
        cols = ["set_id", "slot", "fmt", "expected", "got", "reason", "error", "seconds"]
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(results)
    report(results, time.perf_counter() - started, args.workers)
    print(f"서류별 결과: {args.out}")


if __name__ == "__main__":
    main()
