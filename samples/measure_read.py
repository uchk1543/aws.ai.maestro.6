"""읽기 정확도 측정 (B2). 담당: 판독. 규칙: .kiro/steering/agent-design.md 11번 '읽기: eval/fields.csv 로 잰 칸별 판독 정답 수'

개발용 상업송장·포장명세서(P0)를 read_document로 읽어 eval/fields.csv 의 정답과 맞춘다. 서류 종류는 정답(eval/sets.csv)을 준다.
P0 칸: invoice_no(약속 1의 doc_no), total_qty, total_gross_kg. 합계가 찍히지 않은 서류는 줄 값을 더해 맞춘다
(대조 코드와 같은 방식, docs/schema.md 약속 3). 발표용(samples/test, eval/test)은 열지 않는다.

실행:
    export MODEL_ID=<global 추론 프로필 ID>
    uv run python -m samples.measure_read                    # 개발용 상업송장·포장명세서 전체 (150장)
    uv run python -m samples.measure_read --only D001 D002   # 일부 세트만

출력: 칸별·형식별·스타일별 정답 수, 틀린 칸 목록, 호출 실패, 시간. 서류별 결과는 --out (기본 tmp/, git 제외).
"""

import argparse
import csv
import json
import os
import statistics
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from samples.measure_classify import ROOT, load_docs
from tools.extract import ReadError, read_document
from tools.models import ExtractedDocument

FIELDS_CSV = ROOT / "eval" / "fields.csv"
P0_DOCS = ("commercial_invoice", "packing_list")
P0_FIELDS = ("invoice_no", "total_qty", "total_gross_kg")
LINE_OF = {"total_qty": "qty", "total_gross_kg": "gross_kg"}


def load_answers() -> dict[tuple[str, str], dict[str, str]]:
    """(세트, 서류 종류) → {칸: 정답}. P0 칸만."""
    answers: dict[tuple[str, str], dict[str, str]] = defaultdict(dict)
    with FIELDS_CSV.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if r["doc"] in P0_DOCS and r["field"] in P0_FIELDS:
                answers[(r["set_id"], r["doc"])][r["field"]] = r["answer"]
    return answers


def read_value(doc: ExtractedDocument, field: str) -> tuple[object, str | None]:
    """서류에서 칸 값과 근거 raw. 합계 칸이 비었으면 줄 값을 모두 읽었을 때만 더한다."""
    if field == "invoice_no":
        cell = doc.doc_no
        return (cell.value, cell.raw) if cell else (None, None)
    cell = getattr(doc, field)
    if cell is not None and cell.value is not None:
        return cell.value, cell.raw
    lines = [getattr(item, LINE_OF[field]) for item in doc.items]
    if lines and all(c is not None and c.value is not None for c in lines):
        return round(sum(float(c.value) for c in lines), 3), "줄 합: " + " + ".join(str(c.raw) for c in lines)
    return None, cell.raw if cell else None


def same(field: str, got: object, answer: str) -> bool:
    if got is None:
        return False
    if field == "invoice_no":
        return str(got).strip() == answer.strip()
    return abs(float(got) - float(answer)) < 0.005


def read_one(row: dict) -> dict:
    started = time.perf_counter()
    try:
        doc = read_document(str(row["path"].relative_to(ROOT)), row["path"].read_bytes(), row["expected"])
        return {**row, "doc": doc, "error": "", "seconds": round(time.perf_counter() - started, 1)}
    except ReadError as exc:
        return {**row, "doc": None, "error": str(exc), "seconds": round(time.perf_counter() - started, 1)}


def score(results: list[dict], answers: dict) -> list[dict]:
    """서류마다 P0 칸 세 개를 맞춘다. 칸 한 줄씩."""
    cells = []
    for r in results:
        for field in P0_FIELDS:
            answer = answers[(r["set_id"], r["expected"])][field]
            got, raw = read_value(r["doc"], field) if r["doc"] else (None, None)
            cells.append({"set_id": r["set_id"], "slot": r["slot"], "doc_type": r["expected"], "style": r["style"],
                          "fmt": r["fmt"], "field": field, "answer": answer, "got": got, "raw": raw,
                          "ok": same(field, got, answer), "error": r["error"]})
    return cells


def _line(label: str, part: list[dict]) -> str:
    docs = defaultdict(list)
    for c in part:
        docs[(c["set_id"], c["slot"])].append(c["ok"])
    whole = sum(all(v) for v in docs.values())
    return f"  {label:28} 칸 {sum(c['ok'] for c in part)}/{len(part)} · 서류 전체 맞음 {whole}/{len(docs)}"


def report(results: list[dict], cells: list[dict], wall: float, workers: int) -> None:
    print(f"\n== 읽기 정확도 (개발용 상업송장·포장명세서 {len(results)}장, MODEL_ID={os.environ.get('MODEL_ID')}) ==")
    print(_line("전체", cells))
    print("\n칸별")
    for field in P0_FIELDS:
        print(_line(field, [c for c in cells if c["field"] == field]))
    print("\n형식별")
    for fmt in ("pdf", "png", "scan"):
        if part := [c for c in cells if c["fmt"] == fmt]:
            print(_line(fmt, part))
    print("\n서류·스타일별")
    for doc_type in P0_DOCS:
        for style in ("1", "2"):
            if part := [c for c in cells if c["doc_type"] == doc_type and c["style"] == style]:
                print(_line(f"{doc_type} 스타일{style}", part))
    wrong = [c for c in cells if not c["ok"] and not c["error"]]
    if wrong:
        print("\n틀린 칸 (정답 → 읽은 값, raw)")
        for c in wrong:
            print(f"  {c['set_id']} {c['slot']} {c['doc_type'][:4]}{c['style']} {c['fmt']:4} {c['field']:15} "
                  f"{c['answer']} → {c['got']}  raw={c['raw']!r}")
    failed = [r for r in results if r["error"]]
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
    ap.add_argument("--out", type=Path, default=ROOT / "tmp" / "read_dev", help="결과 파일 앞부분 (.csv 칸별, .jsonl 읽은 결과)")
    args = ap.parse_args()

    docs = [d for d in load_docs(set(args.only) if args.only else None) if d["expected"] in P0_DOCS][: args.limit]
    answers = load_answers()
    print(f"서류 {len(docs)}장, 동시 {args.workers}개")
    started = time.perf_counter()
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(read_one, d) for d in docs]
        for i, fut in enumerate(as_completed(futures), 1):
            r = fut.result()
            results.append(r)
            mark = "실패" if r["error"] else " ".join(
                f"{f}:{'O' if c['ok'] else 'X'}" for f, c in zip(P0_FIELDS, score([r], answers)))
            print(f"[{i}/{len(docs)}] {r['set_id']} {r['slot']} {r['expected'][:4]}{r['style']} {r['fmt']} {mark} ({r['seconds']}초)")
    results.sort(key=lambda r: (r["set_id"], r["slot"]))
    cells = score(results, answers)

    out = args.out if args.out.is_absolute() else ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.with_suffix(".csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(cells[0]))
        w.writeheader()
        w.writerows(cells)
    with out.with_suffix(".jsonl").open("w", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps({"set_id": r["set_id"], "slot": r["slot"], "error": r["error"],
                                 "doc": r["doc"].model_dump() if r["doc"] else None}, ensure_ascii=False) + "\n")
    report(results, cells, time.perf_counter() - started, args.workers)
    print(f"결과: {out.with_suffix('.csv')}, {out.with_suffix('.jsonl')}")


if __name__ == "__main__":
    main()
