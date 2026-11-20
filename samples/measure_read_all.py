"""4종 읽기 정확도 측정 (B2 P1). 담당: 판독. 규칙: .kiro/steering/agent-design.md 11번

개발용 서류 4종(상업송장·포장명세서·B/L·원산지증명서)을 read_document로 읽어 eval/fields.csv의 모든 칸과 맞춘다.
서류 종류는 정답(eval/sets.csv)을 준다. 발표용(samples/test, eval/test)은 열지 않는다.
맞춤 기준: 숫자는 값이 같으면, 날짜는 'YYYY-MM-DD'가 같으면, HS는 숫자만 같으면, 글자는 대문자·띄어쓰기를 맞춰 같으면.
합계가 찍히지 않은 서류의 total_qty·total_gross_kg는 줄 값을 더해 맞춘다 (대조 코드와 같은 방식).

    MODEL_ID=... uv run python -m samples.measure_read_all [--only D001 D002] [--types bill_of_lading]
결과 파일: --out (기본 tmp/read_all_dev.jsonl, git 제외). 한 장 읽을 때마다 한 줄씩 쓰고, 다시 실행하면 이미 읽은 장은 건너뛴다
(멈춰도 읽은 결과가 남는다). --rescore는 모델을 부르지 않고 그 파일로만 채점한다.
"""

import argparse
import csv
import json
import os
import re
import time
from collections import defaultdict
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from samples.measure_classify import ROOT, load_docs
from tools.extract import ReadError, read_document
from tools.models import ExtractedDocument

FIELDS_CSV = ROOT / "eval" / "fields.csv"
TYPES = ("commercial_invoice", "packing_list", "bill_of_lading", "certificate_of_origin")
ALIAS = {"invoice_no": "doc_no", "bl_no": "doc_no"}
LINE_OF = {"total_qty": "qty", "total_gross_kg": "gross_kg"}
_ITEM = re.compile(r"items\[(\d+)\]\.(\w+)")


def load_answers() -> dict[tuple[str, str], dict[str, str]]:
    answers: dict[tuple[str, str], dict[str, str]] = defaultdict(dict)
    with FIELDS_CSV.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            answers[(r["set_id"], r["doc"])][r["field"]] = r["answer"]
    return answers


def value_of(doc: ExtractedDocument, field: str):
    """칸 값과 raw. 합계가 비었으면 줄 값을 더한다."""
    if m := _ITEM.fullmatch(field):
        i, name = int(m[1]), m[2]
        cell = getattr(doc.items[i], name, None) if i < len(doc.items) else None
    else:
        cell = getattr(doc, ALIAS.get(field, field), None)
        if (cell is None or cell.value is None) and field in LINE_OF and doc.items:
            parts = [getattr(it, LINE_OF[field]) for it in doc.items]
            if parts and all(p is not None and isinstance(p.value, (int, float)) for p in parts):
                return sum(p.value for p in parts), "+".join(p.raw for p in parts)
    return (cell.value, cell.raw) if cell is not None else (None, None)


def _norm(text) -> str:
    return " ".join(str(text).upper().split())


def same(field: str, got, answer: str) -> bool:
    if answer == "":
        return got in (None, "")
    if got is None:
        return False
    if field.endswith("hs_code"):
        return re.sub(r"\D", "", str(got)) == re.sub(r"\D", "", answer)
    if isinstance(got, (int, float)):
        try:
            return abs(float(got) - float(answer.replace(",", ""))) < 0.005
        except ValueError:
            return False
    return _norm(got) == _norm(answer)


def read_one(row: dict) -> dict:
    started = time.perf_counter()
    try:
        doc = read_document(str(row["path"].relative_to(ROOT)), row["path"].read_bytes(), row["expected"])
        return {**row, "doc": doc, "error": "", "seconds": round(time.perf_counter() - started, 1)}
    except ReadError as exc:
        return {**row, "doc": None, "error": str(exc), "seconds": round(time.perf_counter() - started, 1)}


def score(results: list[dict], answers: dict) -> list[dict]:
    cells = []
    for r in results:
        for field, answer in answers.get((r["set_id"], r["expected"]), {}).items():
            got, raw = value_of(r["doc"], field) if r["doc"] else (None, None)
            cells.append({"set_id": r["set_id"], "slot": r["slot"], "doc_type": r["expected"], "fmt": r["fmt"],
                          "field": field, "answer": answer, "got": got, "raw": raw,
                          "ok": same(field, got, answer), "error": r["error"]})
    return cells


def report(results: list[dict], cells: list[dict]) -> None:
    print(f"\n== 4종 읽기 (개발용 {len(results)}장, MODEL_ID={os.environ.get('MODEL_ID')}) ==")
    for doc_type in TYPES:
        part = [c for c in cells if c["doc_type"] == doc_type]
        if not part:
            continue
        docs = defaultdict(list)
        for c in part:
            docs[(c["set_id"], c["slot"])].append(c["ok"])
        print(f"\n{doc_type}: 칸 {sum(c['ok'] for c in part)}/{len(part)} · 서류 전체 맞음 {sum(all(v) for v in docs.values())}/{len(docs)}")
        fields = sorted({re.sub(r"\[\d+\]", "[*]", c["field"]) for c in part})
        for f in fields:
            fp = [c for c in part if re.sub(r"\[\d+\]", "[*]", c["field"]) == f]
            print(f"  {f:28} {sum(c['ok'] for c in fp)}/{len(fp)}")
    wrong = [c for c in cells if not c["ok"] and not c["error"]]
    if wrong:
        print("\n틀린 칸 (정답 → 읽은 값, raw)")
        for c in wrong:
            print(f"  {c['set_id']} {c['slot']} {c['doc_type'][:6]} {c['fmt']:4} {c['field']:26} {c['answer']!r} → {c['got']!r}  raw={c['raw']!r}")
    failed = [r for r in results if r["error"]]
    if failed:
        print("\n호출 실패 (오류 전문)")
        for r in failed:
            print(f"  {r['set_id']} {r['slot']} {r['fmt']}: {r['error']}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", nargs="*", help="이 세트만 (예: D001 D002)")
    ap.add_argument("--types", nargs="*", default=list(TYPES), choices=TYPES)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", type=Path, default=ROOT / "tmp" / "read_all_dev.jsonl")
    ap.add_argument("--rescore", action="store_true", help="모델을 부르지 않고 --out 파일로만 채점")
    args = ap.parse_args()

    docs = [d for d in load_docs(set(args.only) if args.only else None) if d["expected"] in args.types]
    saved = _load_saved(args.out)
    todo = [] if args.rescore else [d for d in docs if (d["set_id"], d["slot"]) not in saved]
    print(f"서류 {len(docs)}장 중 이미 읽음 {len(docs) - len(todo) if not args.rescore else len(saved)}장, 이번에 {len(todo)}장 (동시 {args.workers}개)")
    started = time.perf_counter()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for fut in as_completed([pool.submit(read_one, d) for d in todo]):
            r = fut.result()
            with lock, args.out.open("a", encoding="utf-8") as fh:  # 한 장씩 바로 쓴다
                fh.write(json.dumps({"set_id": r["set_id"], "slot": r["slot"], "error": r["error"], "seconds": r["seconds"],
                                     "doc": r["doc"].model_dump(mode="json") if r["doc"] else None}, ensure_ascii=False) + "\n")
    saved = _load_saved(args.out)
    results = [{**d, **saved[(d["set_id"], d["slot"])]} for d in docs if (d["set_id"], d["slot"]) in saved]
    cells = score(results, load_answers())
    report(results, cells)
    secs = sorted(r["seconds"] for r in results)
    if secs:
        print(f"\n시간: 한 장 중간 {secs[len(secs) // 2]}초, 최대 {secs[-1]}초 / 이번 실행 {time.perf_counter() - started:.0f}초")
    print(f"읽은 결과: {args.out}")


def _load_saved(path: Path) -> dict[tuple[str, str], dict]:
    """저장한 판독 (세트, 자리) → {"doc", "error", "seconds"}. 같은 장이 여러 번 있으면 마지막 줄."""
    if not path.exists():
        return {}
    saved = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            doc = ExtractedDocument.model_validate(r["doc"]) if r["doc"] else None
            saved[(r["set_id"], r["slot"])] = {"doc": doc, "error": r["error"], "seconds": r.get("seconds", 0.0)}
    return saved


if __name__ == "__main__":
    main()
