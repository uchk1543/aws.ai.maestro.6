"""run_job 끝까지 돌려 보기 (B9). 담당: 판독. 규칙: .kiro/steering/agent-design.md 1·11번

개발용 세트의 상업송장·포장명세서를 doc_type null로 run_job에 넣어 분류 → 읽기 → 대조 → finish_report까지 돌린다.
분류가 맞았는지, 정답지(eval/answers.csv)의 P0 심은 오류를 같은 규칙·서류로 짚었는지, 걸린 시간과 단계를 본다.
점수 계산 자체는 2번의 eval/score.py(H1) 몫이고, 여기서는 Agent가 끝까지 도는지 확인하는 용도다.
발표용(samples/test, eval/test)은 열지 않는다. 세트 하나에 모델 호출 4번(분류 2 + 읽기 2), --agent면 루프 차례만큼 더.

실행:
    export MODEL_ID=<global 추론 프로필 ID>
    uv run python -m samples.measure_run_job --only D002 D003 D005 D006 D010            # 고정 순서
    uv run python -m samples.measure_run_job --only D002 D003 D005 D006 D010 --agent    # 에이전트 루프
"""

import argparse
import csv
import statistics
import time
from collections import Counter
from pathlib import Path

from agent.document_agent import READ_TYPES, run_job
from tools.models import DOC_TYPE_KO

ROOT = Path(__file__).resolve().parent.parent
DEV = ROOT / "samples" / "dev"
SETS = ROOT / "eval" / "sets.csv"
ANSWERS = ROOT / "eval" / "answers.csv"


def load_sets(only: list[str]) -> dict[str, list[tuple[str, str]]]:
    """세트 → [(파일 키, 정답 종류)]. run_job이 읽는 종류(READ_TYPES)만."""
    found: dict[str, list[tuple[str, str]]] = {}
    with SETS.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            sid = r["set_id"]
            if r["split"] != "dev" or sid not in only or sid in found:
                continue
            kv = dict(part.split("=", 1) for part in r["docs"].split(";"))
            docs = []
            for slot in "abcd":
                expected = kv.get(f"doc_{slot}")
                if expected in READ_TYPES:
                    [path] = sorted((DEV / sid).glob(f"doc_{slot}.*"))
                    docs.append((str(path.relative_to(ROOT)), expected))
            found[sid] = docs
    missing = [s for s in only if s not in found]
    if missing:
        raise SystemExit(f"개발용 세트가 아닙니다: {missing}")
    return found


def field_group(field: str) -> str:
    """issues의 칸 경로를 정답지의 서류 전체 값 이름으로 묶는다 (docs/schema.md 약속 3). 예: items[0].gross_kg → total_gross_kg"""
    if field in ("doc_no", "invoice_no"):
        return "invoice_no"
    if field.endswith("gross_kg"):
        return "total_gross_kg"
    if field.endswith("qty"):
        return "total_qty"
    return field


def load_planted() -> dict[str, list[dict]]:
    """세트 → P0 심은 오류 줄 (개발용만)."""
    planted: dict[str, list[dict]] = {}
    with ANSWERS.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if r["split"] == "dev" and r["phase"] == "P0":
                planted.setdefault(r["set_id"], []).append(r)
    return planted


def main() -> None:
    parser = argparse.ArgumentParser(description="run_job 끝까지 돌려 보기 (개발용)")
    parser.add_argument("--only", nargs="+", required=True, help="세트 ID. 예: D002 D003")
    parser.add_argument("--agent", action="store_true", help="에이전트 루프로 돈다 (MODEL_ID의 모델이 도구를 고른다)")
    args = parser.parse_args()

    agent_model = None
    if args.agent:
        from agent import make_model

        agent_model = make_model()
    sets, planted = load_sets(args.only), load_planted()
    times, classified, statuses = [], Counter(), Counter()
    detected = expected_total = false_alarm = 0
    for sid, docs in sets.items():
        files = [{"key": key, "doc_type": None} for key, _ in docs]
        started = time.perf_counter()
        job = run_job(f"job-{sid.lower()}", files, lambda key: (ROOT / key).read_bytes(), agent_model=agent_model)
        took = time.perf_counter() - started
        times.append(took)
        statuses[job.status] += 1

        print(f"\n== {sid} status={job.status} {took:.1f}초")
        for s in job.steps:
            print(f"  {'✔' if s.ok else '✖'} {s.tool:18} {s.summary}")
        for i in job.result.issues:
            cells = ", ".join(f"{c.doc}.{c.field}={c.raw}" for c in i.cells)
            print(f"  - {i.grade} {i.rule_id}: {i.evidence} [{cells}]")

        # 분류: 단계 기록의 '이름 → 종류'를 정답과 맞춘다
        got = {s.summary.split(" → ")[0]: s.summary for s in job.steps if s.tool == "classify_document" and s.ok}
        for key, expected in docs:
            name = key.rsplit("/", 1)[-1]
            ok = name in got and f"→ {DOC_KO[expected]} (" in got[name]
            classified["맞음" if ok else "틀림"] += 1

        # 판정: 심은 칸(서류, 칸)을 불일치로 짚었는지 (agent-design.md 11번. 규칙 ID는 달라도 칸이 같으면 탐지)
        mismatches = [i for i in job.result.issues if i.grade == "불일치"]
        rows = planted.get(sid, [])
        if not rows and mismatches:
            false_alarm += len(mismatches)
        for row in rows:
            expected_total += 1
            hits = [
                i.rule_id for i in mismatches
                if any(c.doc == row["doc"] and field_group(c.field) == row["field"] for c in i.cells)
            ]
            detected += bool(hits)
            print(f"  * 심은 오류 {row['doc']}.{row['field']} {row['original_value']}→{row['planted_value']} "
                  f"(정답지 규칙 {row['expected_rule_id']}): {'짚음 ' + ','.join(hits) if hits else '못 짚음'}")

    print(f"\n세트 {len(sets)}개 ({'에이전트 루프' if args.agent else '고정 순서'}, 한 번 측정)")
    print(f"  분류: 맞음 {classified['맞음']} / {sum(classified.values())}")
    print(f"  상태: {dict(statuses)}")
    print(f"  P0 심은 오류: {expected_total}건 중 {detected}건 짚음, 오류 없는 세트의 불일치 {false_alarm}건")
    print(f"  시간: 평균 {statistics.mean(times):.1f}초, 최대 {max(times):.1f}초 (세트 하나, 서류 {len(docs)}장)")


DOC_KO = DOC_TYPE_KO  # 단계 기록의 서류 이름 (4종, B2 P1)

if __name__ == "__main__":
    main()
