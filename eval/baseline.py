"""모델 단독 기준선 (H3). 담당: 판독. 규칙: .kiro/steering/agent-design.md 11번

같은 정답지(eval/answers.csv)로 "모델 혼자 vs 우리 방식"을 비교하려고, 세트의 상업송장·포장명세서를 모델에게 한 번에 주고
송장 번호·총수량·총중량 중 서로 맞지 않는 칸을 찾게 한다. 우리 방식(따로 읽기 → 코드 대조)과 범위(P0)가 같다.
채점은 eval/score.py의 score_detection을 그대로 쓴다. 모델이 짚은 칸은 '불일치'로 본다.

    MODEL_ID=... uv run python -m eval.baseline [--only D003 D005] [--out build/baseline_dev.json]
    uv run python -m eval.baseline --rescore build/baseline_dev.json     # 저장한 답으로 다시 채점 (모델 호출 없음)

세트마다 모델을 한 번 부른다 (형식 검증에 실패하면 한 번 더). 개발용(dev)만 돈다.
"""

import argparse
import csv
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from eval.score import EVAL_DIR, format_report, load_answers, load_formats, score_detection
from tools.models import Issue, IssueCell

ROOT = EVAL_DIR.parent
DEV = ROOT / "samples" / "dev"
DOCS = ("commercial_invoice", "packing_list")
DOC_LABEL = {"commercial_invoice": "Commercial Invoice", "packing_list": "Packing List"}
_FORMATS = {".pdf": "pdf", ".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg"}

PROMPT = """너는 수입 통관 서류를 확인하는 사람이다. 같은 화물의 상업송장(Commercial Invoice)과 포장명세서(Packing List)를 받는다.
두 서류에서 아래 세 가지가 서로 맞는지 확인하고, 맞지 않는 것을 모두 찾는다. 맞으면 findings를 빈 목록으로 둔다.
- invoice_no: 송장 번호 (포장명세서에도 송장 번호가 적혀 있다)
- total_qty: 총수량
- total_gross_kg: 총중량(Gross Weight)
찾은 것마다 두 서류에 적힌 값을 그대로 옮기고, 왜 다르다고 보는지 한 문장으로 적는다."""


class Finding(BaseModel):
    field: Literal["invoice_no", "total_qty", "total_gross_kg"] = Field(description="맞지 않는 칸")
    commercial_invoice_raw: str | None = Field(description="상업송장에 적힌 그대로의 값. 못 찾으면 null")
    packing_list_raw: str | None = Field(description="포장명세서에 적힌 그대로의 값. 못 찾으면 null")
    evidence: str = Field(description="왜 다르다고 보는지 한 문장")


class Answer(BaseModel):
    findings: list[Finding] = Field(description="맞지 않는 칸 목록. 모두 맞으면 빈 목록")


def load_dev_sets(only: list[str] | None = None) -> dict[str, dict[str, Path]]:
    """dev 세트 → {서류 종류: 파일 경로}. 상업송장·포장명세서가 둘 다 있는 세트만."""
    found: dict[str, dict[str, Path]] = {}
    with (EVAL_DIR / "sets.csv").open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            sid = r["set_id"]
            if r["split"] != "dev" or sid in found or (only and sid not in only):
                continue
            kv = dict(part.split("=", 1) for part in r["docs"].split(";"))
            paths = {}
            for slot in "abcd":
                doc_type = kv.get(f"doc_{slot}")
                if doc_type in DOCS:
                    [path] = sorted((DEV / sid).glob(f"doc_{slot}.*"))
                    paths[doc_type] = path
            if set(paths) == set(DOCS):
                found[sid] = paths
    return found


def blocks_for(paths: dict[str, Path]) -> list[dict]:
    """두 서류를 이름을 붙여 한 메시지에 넣는다 (Bedrock document 블록 이름은 메시지 안에서 달라야 한다)."""
    blocks: list[dict] = []
    for doc_type in DOCS:
        path = paths[doc_type]
        fmt = _FORMATS[path.suffix.lower()]
        blocks.append({"text": f"[{DOC_LABEL[doc_type]}]"})
        if fmt == "pdf":
            blocks.append({"document": {"format": "pdf", "name": DOC_LABEL[doc_type], "source": {"bytes": path.read_bytes()}}})
        else:
            blocks.append({"image": {"format": fmt, "source": {"bytes": path.read_bytes()}}})
    return blocks


def ask_model(blocks: list[dict]) -> Answer:
    """모델에게 한 번 묻는다. 형식이 틀리면 한 번 더 묻는다."""
    from strands import Agent

    from agent import make_model

    last: Exception | None = None
    for _ in range(2):
        agent = Agent(model=make_model(), system_prompt=PROMPT, callback_handler=None)
        try:
            result = agent([*blocks, {"text": "두 서류를 맞춰 보고 답한다."}], structured_output_model=Answer)
            return Answer.model_validate(result.structured_output.model_dump())
        except ValidationError as exc:
            last = exc
    raise RuntimeError(f"형식 검증 두 번 실패: {last}")


def to_issues(answer: Answer) -> list[Issue]:
    """모델이 짚은 칸을 '불일치' Issue로 바꾼다. 칸은 두 서류 모두에 건다 (cross_check와 같은 모양)."""
    return [
        Issue(
            rule_id=f"BASELINE-{f.field}",
            grade="불일치",
            cells=[
                IssueCell(doc="commercial_invoice", field=f.field, raw=f.commercial_invoice_raw),
                IssueCell(doc="packing_list", field=f.field, raw=f.packing_list_raw),
            ],
            evidence=f.evidence,
        )
        for f in answer.findings
    ]


def run(sets: dict[str, dict[str, Path]], workers: int = 4) -> dict[str, dict]:
    """세트마다 모델을 한 번 불러 {세트: {"answer" | "error", "seconds"}}를 돌려준다."""

    def one(item):
        sid, paths = item
        started = time.perf_counter()
        try:
            answer = ask_model(blocks_for(paths))
            out = {"answer": answer.model_dump()}
        except Exception as exc:  # 한 세트가 실패해도 나머지는 잰다. 실패한 세트는 채점에서 뺀다(not_run)
            out = {"error": f"{type(exc).__name__}: {exc}"}
        out["seconds"] = round(time.perf_counter() - started, 1)
        print(f"[baseline] {sid} {out['seconds']}초 " + (f"findings={len(out['answer']['findings'])}" if "answer" in out else out["error"][:120]))
        return sid, out

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return dict(pool.map(one, sorted(sets.items())))


def score(results: dict[str, dict]) -> dict:
    issues = {sid: to_issues(Answer.model_validate(r["answer"])) for sid, r in results.items() if "answer" in r}
    return score_detection(load_answers(), issues, "dev", fmt_by_doc=load_formats())


def main() -> None:
    parser = argparse.ArgumentParser(description="모델 단독 기준선 (H3, 개발용만)")
    parser.add_argument("--only", nargs="+", help="세트 ID. 없으면 dev 전체")
    parser.add_argument("--out", default=str(ROOT / "build" / "baseline_dev.json"), help="모델 답을 저장할 곳")
    parser.add_argument("--rescore", help="저장한 답으로 다시 채점 (모델 호출 없음)")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    if args.rescore:
        results = json.loads(Path(args.rescore).read_text(encoding="utf-8"))
    else:
        sets = load_dev_sets(args.only)
        print(f"[baseline] dev {len(sets)}세트, 세트마다 모델 한 번")
        results = run(sets, args.workers)
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[baseline] 답 저장: {out}")
    failed = [sid for sid, r in results.items() if "error" in r]
    seconds = [r["seconds"] for r in results.values() if "answer" in r]
    print()
    print("모델 단독 기준선 (상업송장·포장명세서를 한 번에 주고 송장 번호·총수량·총중량 불일치를 찾게 함)")
    print(f"- 돌린 세트 {len(results)}, 실패 {len(failed)}" + (f" {failed}" if failed else ""))
    if seconds:
        print(f"- 세트당 {min(seconds)}~{max(seconds)}초 (중앙 {sorted(seconds)[len(seconds) // 2]}초)")
    print(format_report(score(results)))


if __name__ == "__main__":
    main()
