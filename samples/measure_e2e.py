"""끝까지 측정 (FB15 #172). 담당: 판독(실행·판독 결과 남기기). 형식별 채점 표는 검증(eval/score.py, 2번).

개발용 세트를 실제 판독으로 run_job 끝까지 돌린다. 처리 Lambda(api/worker.py)와 같은 조건이다:
doc_type을 비워 분류부터, 세트의 서류를 모두(상업송장·포장명세서·선하증권·원산지증명서) 올린다.
처리 Lambda의 부품을 그대로 쓴다 (like_worker):
  - 서류마다 Textract OCR을 run_job과 동시에 돌리고(OcrRun, F10 #188), 다시 확인에 그 OCR을 넘긴다(_rereader_with)
  - HS는 HsModelRun(모델 검색어·후보 고르기, #132). 확정 이력은 비운 상태(평가 전 초기화)
  - 배포본 저장소는 건드리지 않는다: 서류는 로컬 파일, 쪽 그림은 S3에 쓰지 않고, HS 이력은 DynamoDB를 읽지 않는다
  - 분류는 Bedrock(CLASSIFY_BY_OCR 기본 끔과 같다)
--no-ocr·--no-hs-model로 끌 수 있다(예전 방식: OCR 없음, HS 모델 없음).
발표용(samples/test, eval/test)은 열지 않는다.

- 세트마다 결과를 한 줄씩 바로 eval/results/e2e_dev.jsonl에 쓴다 (중간에 멈춰도 그때까지 남고, 다시 돌리면 이어서 한다).
  형식, 상태, 시간, 모델 호출 수, 분류, 읽은 서류(docs), 문제(issues), HS, 단계. 2번이 이 파일로 모델 호출 없이 다시 채점한다.
- 판독(read_document)은 로컬 판독 캐시(.cache/read/), OCR은 로컬 OCR 캐시(.cache/ocr/)에 남긴다(git 제외).
  규칙을 바꿔 다시 돌릴 때 읽기 호출과 Textract 호출을 아낀다. --no-cache면 둘 다 쓰지 않는다.
- --report: 파일만 읽어 형식(PDF·PNG·스캔)별 분류·읽기·탐지·오탐·HS·시간·토큰·어림 비용을 낸다 (모델 호출 없음).

세트 고르기 (--per-format N, 기본 10 → 30세트): 상업송장 형식(pdf·png·scan)마다 세트 번호 순으로
심은 P0 오류 4 · 정상 2 · 헷갈리지만 정상(변형) 2 · P1 오류 2를 고르고, 모자라면 같은 형식의 남은 세트로 채운다.
모델 호출은 세트당 약 14번 (분류 4 + 읽기 4 + HS 품목 줄마다 2 + 다시 확인 중 모델 다시 읽기, #162 측정),
Textract는 세트당 약 5쪽 (서류마다 PDF 쪽 수, 이미지는 1).

실행:
    export MODEL_ID=<global 추론 프로필 ID>
    uv run python -m samples.measure_e2e                 # 30세트, 이미 잰 세트는 건너뜀
    uv run python -m samples.measure_e2e --report        # 모델 호출 없이 표만
    uv run python -m samples.measure_e2e --sets D003 D005 --out /tmp/x.jsonl
"""

import argparse
import contextlib
import csv
import io
import json
import statistics
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEV = ROOT / "samples" / "dev"
EVAL = ROOT / "eval"
OUT = EVAL / "results" / "e2e_dev.jsonl"
SUMMARY = EVAL / "results" / "e2e_dev_summary.json"
CACHE = ROOT / ".cache" / "read"
OCR_CACHE = ROOT / ".cache" / "ocr"
FORMATS = ("pdf", "png", "scan")
QUOTA = (("P0", 4), ("정상", 2), ("변형", 2), ("P1", 2))  # 형식마다. 합이 기본 per_format(10)


# ---------------------------------------------------------------------------
# 세트 고르기
# ---------------------------------------------------------------------------
def dev_sets() -> dict[str, dict[str, str]]:
    """개발용 세트 → {서류 종류: 형식}. 세트의 첫 줄(eval/sets.csv)에서 읽는다."""
    sets: dict[str, dict[str, str]] = {}
    with (EVAL / "sets.csv").open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if r["split"] != "dev" or r["set_id"] in sets:
                continue
            kv = dict(part.split("=", 1) for part in r["docs"].split(";"))
            sets[r["set_id"]] = {kv[f"doc_{s}"]: kv[f"fmt_{s}"] for s in "abcd" if f"doc_{s}" in kv}
    return sets


def set_kind() -> dict[str, str]:
    """세트 → 갈래. P0 오류가 있으면 P0, 그다음 P1, 변형(헷갈리지만 정상), 정상 (eval/answers.csv)."""
    kinds: dict[str, set[str]] = defaultdict(set)
    with (EVAL / "answers.csv").open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if r["split"] != "dev":
                continue
            if r["error_type"] != "none":
                kinds[r["set_id"]].add(r["phase"] or "P1")
            else:
                kinds[r["set_id"]].add("변형" if r.get("variant") else "정상")
    order = ("P0", "P1", "변형", "정상")
    return {sid: next(k for k in order if k in ks) for sid, ks in kinds.items()}


def pick_sets(per_format: int = 10) -> list[str]:
    """상업송장 형식마다 per_format세트. 갈래 몫(QUOTA)을 세트 번호 순으로 채우고 모자라면 남은 세트로 채운다."""
    sets, kinds = dev_sets(), set_kind()
    picked: list[str] = []
    for fmt in FORMATS:
        pool = sorted(s for s, f in sets.items() if f.get("commercial_invoice") == fmt)
        chosen: list[str] = []
        scale = per_format / sum(n for _, n in QUOTA)
        for kind, n in QUOTA:
            chosen += [s for s in pool if kinds.get(s) == kind and s not in chosen][: round(n * scale)]
        chosen += [s for s in pool if s not in chosen][: per_format - len(chosen)]
        picked += sorted(chosen[:per_format])
    return picked


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------
class LocalReadCache:
    """판독 캐시(tools.extract.ReadCache)·OCR 캐시(tools.ocr.OcrCache)의 로컬 파일판. <키>.json 한 파일에 한 값."""

    def __init__(self, root: Path):
        self.root = root

    def get(self, key: str) -> str | None:
        path = self.root / f"{key}.json"
        return path.read_text(encoding="utf-8") if path.exists() else None

    def put(self, key: str, value: str) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / f"{key}.json").write_text(value, encoding="utf-8")


class _EmptyHistory:
    """빈 확정 이력 (평가는 이력을 비운 상태에서 시작한다, agent-design.md 11번)."""

    def get(self, importer: str, item_key: str) -> str | None:
        return None

    def put(self, importer: str, item_key: str, hs: str, job_id: str) -> None:
        return None


# Bedrock 응답 metadata.usage의 칸 → 이 파일의 칸 (토큰 수)
USAGE_KEYS = {
    "inputTokens": "tokens_in", "outputTokens": "tokens_out",
    "cacheReadInputTokens": "cache_read", "cacheWriteInputTokens": "cache_write",
}
# 어림 비용 단가 (미국 달러 / 100만 토큰). Anthropic 직접 요금의 Sonnet 5.5·Sonnet 5 값(2026-11)이다.
# Bedrock 요금은 다를 수 있어 --price-in·--price-out으로 바꾼다. 청구 화면(Cost Explorer)은 조직 정책으로 막혀 있어 토큰으로 어림한다
PRICE_IN, PRICE_OUT = 2.0, 10.0
# Textract DetectDocumentText 서울 리전 쪽당 (미국 달러). 4번이 AWS Pricing API로 확인한 값 (#223 .kiro/specs/b4-l0-ocr-cost/design.md)
PRICE_TEXTRACT = 0.0015


def count_model_usage() -> dict:
    """Bedrock 모델 호출 수와 토큰을 센다. 도구 안의 분류·읽기·다시 확인과 루프 차례가 모두 BedrockModel.stream을 지난다.

    반환: {"model", "tokens_in", "tokens_out", "cache_read", "cache_write"} 누적값 (호출이 끝날 때마다 는다).
    토큰은 응답 끝의 metadata.usage에서 읽는다. 재시도로 두 번 부르면 두 번 다 센다(실제로 쓴 값).
    """
    from strands.models import bedrock

    usage = {"model": 0, **{k: 0 for k in USAGE_KEYS.values()}}
    lock = threading.Lock()
    original = bedrock.BedrockModel.stream

    async def counting(self, *args, **kwargs):
        with lock:
            usage["model"] += 1
        async for event in original(self, *args, **kwargs):
            meta = event.get("metadata") if isinstance(event, dict) else None
            if meta and meta.get("usage"):
                with lock:
                    for src, dst in USAGE_KEYS.items():
                        usage[dst] += int(meta["usage"].get(src) or 0)
            yield event

    bedrock.BedrockModel.stream = counting
    return usage


def cost_usd(tokens_in: int, tokens_out: int, price_in: float = PRICE_IN, price_out: float = PRICE_OUT) -> float:
    """토큰 → 어림 비용(미국 달러). 캐시 토큰은 따로 적기만 하고 여기에 넣지 않는다(이 측정은 프롬프트 캐시를 쓰지 않는다)."""
    return round((tokens_in * price_in + tokens_out * price_out) / 1_000_000, 4)


def files_of(set_id: str) -> list[tuple[str, str]]:
    """세트 → [(파일 키, 정답 종류)]. 키는 저장소 기준 경로."""
    with (EVAL / "sets.csv").open(encoding="utf-8", newline="") as fh:
        row = next(r for r in csv.DictReader(fh) if r["set_id"] == set_id and r["split"] == "dev")
    kv = dict(part.split("=", 1) for part in row["docs"].split(";"))
    out = []
    for slot in "abcd":
        if f"doc_{slot}" in kv:
            [path] = sorted((DEV / set_id).glob(f"doc_{slot}.*"))
            out.append((str(path.relative_to(ROOT)), kv[f"doc_{slot}"]))
    return out


def like_worker(usage: dict, ocr_cache_dir: Path | None) -> None:
    """처리 Lambda(api/worker.py)의 OCR·HS 부품을 로컬에서 그대로 쓰게 한다. 배포본 저장소는 건드리지 않는다.

    - 서류 받기(handler.fetch_object): S3 대신 저장소의 로컬 파일 (키가 'samples/dev/…' 경로다)
    - 쪽 그림 저장(handler.store_object): 하지 않는다 (S3 uploads/에 쓰지 않음)
    - HS 확정 이력(handler._hs_history): 빈 이력 (DynamoDB를 읽지 않음. 평가는 이력을 비운 상태에서 시작)
    - OCR 저장소(worker.ocr_cache): ocr_cache_dir의 로컬 파일 (같은 파일은 Textract를 다시 부르지 않음). None이면 저장 안 함
    - Textract(worker.ocr_document): 그대로 부르고, 부른 쪽 수를 usage["textract_pages"]에 센다
    """
    from api import handler, worker

    handler.fetch_object = lambda key: (ROOT / key).read_bytes()
    handler.store_object = lambda *args, **kwargs: None
    handler._hs_history = lambda: _EmptyHistory()
    cache = LocalReadCache(ocr_cache_dir) if ocr_cache_dir is not None else None
    worker.ocr_cache = lambda: cache
    usage.setdefault("textract_pages", 0)
    original, lock = worker.ocr_document, threading.Lock()

    def counting(*args, **kwargs):
        pages = kwargs.get("pages")
        with lock:
            usage["textract_pages"] += len(pages) if pages else 1  # PDF는 쪽마다, 이미지는 1번
        return original(*args, **kwargs)

    worker.ocr_document = counting


def run_set(set_id: str, calls: dict, *, ocr: bool = True, hs_model: bool = True) -> dict:
    """세트 하나를 run_job으로 끝까지. 결과 한 줄(dict).

    ocr·hs_model이 켜져 있으면 처리 Lambda처럼 OcrRun(다시 확인에 OCR)·HsModelRun(HS 모델)을 쓴다. like_worker를 먼저 부른다.
    시간은 처리 Lambda처럼 OCR을 모두 받을 때까지(OcrRun.finish) 잰다.
    """
    from agent.document_agent import run_job
    from api import worker
    from tools import hs
    from tools.models import DOC_TYPE_KO

    table = hs.load_hs_table()
    files = files_of(set_id)
    read: list = []
    before, started = dict(calls), time.perf_counter()
    ocr_run = worker.OcrRun([k for k, _ in files]) if ocr else None  # run_job과 동시에 돈다
    hs_run = worker.HsModelRun() if hs_model else None
    if hs_run is not None:
        recommender = hs_run.recommend
    else:
        def recommender(docs, line):
            return hs.recommend_hs(docs, line, "", history=_EmptyHistory(), table=table)
    try:
        job = run_job(
            f"job-e2e-{set_id.lower()}", [{"key": k, "doc_type": None} for k, _ in files], lambda key: (ROOT / key).read_bytes(),
            hs_recommender=recommender, on_docs=read.extend,
            rereader=worker._rereader_with(ocr_run) if ocr_run is not None else None,
        )
        error = job.error
    except Exception as exc:  # 측정은 멈추지 않고 기록한다
        job, error = None, f"{type(exc).__name__}: {exc}"
    extra = []  # 처리 Lambda가 run_job 뒤에 남기는 단계 (OCR 결과, HS 모델 사용)
    if ocr_run is not None:
        extra.append(worker._ocr_step(ocr_run.finish(), ocr_run.timed_out))
    if hs_run is not None and (step := hs_run.step()) is not None:
        extra.append(step)
    seconds = round(time.perf_counter() - started, 1)
    steps = (job.steps if job else []) + extra
    got = {s.summary.split(" → ")[0]: s.summary for s in steps if s.tool == "classify_document" and s.ok}
    classified = []
    for key, expected in files:
        name = key.rsplit("/", 1)[-1]
        classified.append([name, expected, name in got and f"→ {DOC_TYPE_KO[expected]} (" in got[name]])
    result = job.result if job and job.result else None
    return {
        "set_id": set_id, "formats": dev_sets()[set_id], "status": job.status if job else None, "error": error,
        "seconds": seconds, "model_calls": calls["model"] - before["model"],
        **{k: calls[k] - before[k] for k in USAGE_KEYS.values()},  # 이 세트에서 쓴 토큰
        "textract_pages": calls.get("textract_pages", 0) - before.get("textract_pages", 0),
        "classified": classified,
        "docs": [d.model_dump(mode="json") for d in read],
        "issues": [i.model_dump(mode="json") for i in result.issues] if result else [],
        "hs": [h.model_dump(mode="json") for h in result.hs] if result else [],
        "steps": [s.model_dump(mode="json") for s in steps],
    }


def warnings_of(printed: str) -> list[str]:
    """숨긴 도구 출력에서 [warn]·[error] 줄만 (OCR·HS 모델을 못 쓴 이유)."""
    return [line for line in printed.splitlines() if line.startswith(("[warn]", "[error]"))]


def hs_answers() -> dict[tuple[str, int], str]:
    """(세트, 품목 줄) → 정답 HS (eval/sets.csv hs_answer, 개발용만)."""
    with (EVAL / "sets.csv").open(encoding="utf-8", newline="") as fh:
        return {(r["set_id"], int(r["line"])): r["hs_answer"] for r in csv.DictReader(fh)
                if r["split"] == "dev" and r["line"] and r["hs_answer"]}


def score_hs_rows(rows: list[dict]) -> dict:
    """측정 줄의 HS 결과를 정답과 맞춘다 (eval/score.py score_hs와 같은 칸 이름).

    자동 확정 중 틀린 것(wrong_auto, 0이어야 한다), 사람 확인 필요 중 정답이 보여 준 후보 3개 안에 든 것(human_in_top3).
    """
    answers = hs_answers()
    out = Counter(rows=0, no_answer=0, auto=0, wrong_auto=0, human=0, human_in_top3=0, human_no_candidates=0)
    wrong: list[str] = []
    for r in rows:
        for h in r["hs"]:
            out["rows"] += 1
            answer = answers.get((r["set_id"], int(h["line"])))
            if answer is None:
                out["no_answer"] += 1
                continue
            if h["status"] == "자동 확정":
                out["auto"] += 1
                if (h.get("hs_code") or "") != answer:
                    out["wrong_auto"] += 1
                    wrong.append(f"{r['set_id']} {h['line']}행 {h.get('hs_code')} (정답 {answer})")
                continue
            out["human"] += 1
            shown = [c["hs"] for c in (h.get("candidates") or [])][:3]
            out["human_in_top3"] += answer in shown
            out["human_no_candidates"] += not shown
    return {**out, "wrong_auto_rows": wrong}


def done_sets(out: Path) -> set[str]:
    if not out.exists():
        return set()
    return {json.loads(line)["set_id"] for line in out.read_text(encoding="utf-8").splitlines() if line.strip()}


def measure(
    set_ids: list[str], out: Path, cache: Path | None, *, ocr: bool = True, hs_model: bool = True,
    ocr_cache: Path | None = OCR_CACHE,
) -> None:
    from tools import extract

    if cache is not None:
        local = LocalReadCache(cache)
        extract._default_cache = lambda: local  # 처리 Lambda의 S3 판독 캐시 대신 로컬 (모델 ID·지시문 버전이 키에 들어간다)
    calls = count_model_usage()
    like_worker(calls, ocr_cache if cache is not None else None)  # --no-cache면 OCR 캐시도 쓰지 않는다
    print(f"[e2e] 조건: OCR {'켬' if ocr else '끔'} · HS 모델 {'켬' if hs_model else '끔'} · 캐시 {'켬' if cache else '끔'}")
    skip = done_sets(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    todo = [s for s in set_ids if s not in skip]
    print(f"[e2e] {len(set_ids)}세트 중 {len(todo)}세트를 잰다 (이미 잰 {len(set_ids) - len(todo)}세트는 건너뜀) → {out}")
    for n, set_id in enumerate(todo, 1):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):  # 도구의 [tool] 출력은 숨긴다
            row = run_set(set_id, calls, ocr=ocr, hs_model=hs_model)
        row["warnings"] = warnings_of(buf.getvalue())  # OCR 실패 이유 같은 [warn]·[error] 줄은 남긴다
        with out.open("a", encoding="utf-8") as fh:  # 한 건씩 바로 저장
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"[e2e] {n}/{len(todo)} {set_id} {row['status']} {row['seconds']}초 호출 {row['model_calls']}번 "
              f"토큰 입력 {row['tokens_in']:,}·출력 {row['tokens_out']:,} Textract {row['textract_pages']}쪽"
              + (f" 오류 {row['error']}" if row["error"] else "")
              + (f" 경고 {len(row['warnings'])}줄" if row["warnings"] else ""), flush=True)
    print(f"[e2e] 이번 실행 모델 호출 합계 {calls['model']}번, 토큰 입력 {calls['tokens_in']:,}·출력 {calls['tokens_out']:,}, "
          f"Textract {calls['textract_pages']}쪽, 어림 {cost_usd(calls['tokens_in'], calls['tokens_out'])}달러 + "
          f"{round(calls['textract_pages'] * PRICE_TEXTRACT, 4)}달러 (단가 {PRICE_IN}/{PRICE_OUT}달러 100만 토큰당, Textract {PRICE_TEXTRACT}달러 쪽당)")


# ---------------------------------------------------------------------------
# 표 (모델 호출 없음)
# ---------------------------------------------------------------------------
def summarize(
    rows: list[dict], price_in: float = PRICE_IN, price_out: float = PRICE_OUT, price_textract: float = PRICE_TEXTRACT,
) -> dict:
    """측정 줄들 → 형식별 숫자. 탐지·읽기 채점은 eval/score.py(2번)의 함수를 그대로 쓴다.

    토큰·어림 비용: 세트 합계와 세트당·서류당 평균. 토큰 칸이 없는 예전 줄은 0으로 본다.
    """
    from eval.score import load_answers, load_formats, score_detection, score_fields
    from tools.models import ExtractedDocument, Issue

    formats = load_formats()
    issues = {r["set_id"]: [Issue.model_validate(i) for i in r["issues"]] for r in rows if r["status"]}
    docs = {r["set_id"]: [ExtractedDocument.model_validate(d) for d in r["docs"]] for r in rows if r["status"]}
    detection = score_detection(load_answers(), issues, "dev", fmt_by_doc=formats)
    # P1(B/L·원산지증명서·총금액)까지 정답으로 본 채점. P0만 보면 P1 세트에서 바르게 찾은 것이 오탐으로 잡힌다
    detection_p1 = score_detection(load_answers(), issues, "dev", fmt_by_doc=formats, phases=("P0", "P1"))
    fields = score_fields(EVAL / "fields.csv", docs, fmt_by_doc=formats)
    by_fmt: dict[str, Counter] = defaultdict(Counter)
    seconds: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        fmt_ci = r["formats"].get("commercial_invoice", "?")
        seconds[fmt_ci].append(r["seconds"])
        for name, expected, ok in r["classified"]:
            fmt = r["formats"].get(expected, "?")
            by_fmt[fmt]["분류"] += 1
            by_fmt[fmt]["분류 맞음"] += ok
    hs = Counter(h["status"] for r in rows for h in r["hs"])
    tokens = {k: sum(r.get(k, 0) for r in rows) for k in USAGE_KEYS.values()}
    n_docs = sum(len(r["classified"]) for r in rows) or 1
    pages = sum(r.get("textract_pages", 0) for r in rows)
    model_cost = cost_usd(tokens["tokens_in"], tokens["tokens_out"], price_in, price_out)
    total = round(model_cost + pages * price_textract, 4)
    # 다시 확인의 근거 세기(agent-design.md 4번): 불일치·확인 필요 문제마다 두 번째 근거를 어디서 얻었나
    checked_by = Counter(i.get("checked_by", "none") for r in rows for i in r["issues"] if i["grade"] in ("불일치", "확인 필요"))
    return {
        "sets": len(rows), "status": dict(Counter(r["status"] for r in rows)),
        "model_calls": sum(r["model_calls"] for r in rows),
        "tokens": {**tokens, "per_set_in": round(tokens["tokens_in"] / len(rows)), "per_set_out": round(tokens["tokens_out"] / len(rows))},
        "textract_pages": pages,
        "cost_usd": {"total": total, "model": model_cost, "textract": round(pages * price_textract, 4),
                     "per_set": round(total / len(rows), 4), "per_doc": round(total / n_docs, 4),
                     "price": {"in_per_mtok": price_in, "out_per_mtok": price_out, "textract_per_page": price_textract},
                     "note": "토큰·쪽 수로 어림한 값. 모델은 Anthropic 직접 요금 기준이라 Bedrock 청구액과 다를 수 있다"},
        "checked_by": dict(checked_by),
        "classify_by_format": {f: dict(c) for f, c in sorted(by_fmt.items())},
        "detection": {k: detection[k] for k in ("planted", "detected", "flagged", "normal_sets", "false_positive_sets",
                                                "check_needed_sets", "wrong_cell_sets", "by_format", "by_error_type")},
        "false_positives": detection["false_positives"], "misses": detection["misses"],
        "detection_p0_p1": {k: detection_p1[k] for k in ("planted", "detected", "flagged", "normal_sets", "false_positive_sets",
                                                         "check_needed_sets", "wrong_cell_sets", "by_format", "by_error_type",
                                                         "false_positives", "misses")},
        "fields": {k: fields[k] for k in ("docs", "docs_correct", "cells", "cells_correct", "unread", "by_field", "by_format")},
        "hs": dict(hs), "hs_score": score_hs_rows(rows),
        "warnings": sum(len(r.get("warnings", [])) for r in rows),
        "seconds_by_ci_format": {f: {"mean": round(statistics.mean(v), 1), "max": max(v)} for f, v in sorted(seconds.items())},
        "seconds": {"mean": round(statistics.mean(r["seconds"] for r in rows), 1), "max": max(r["seconds"] for r in rows)},
    }


def report(
    out: Path, summary_path: Path | None, price_in: float = PRICE_IN, price_out: float = PRICE_OUT,
    price_textract: float = PRICE_TEXTRACT,
) -> dict:
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line.strip()]
    s = summarize(rows, price_in, price_out, price_textract)
    print(json.dumps(s, ensure_ascii=False, indent=1))
    if summary_path is not None:
        summary_path.write_text(json.dumps(s, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"[e2e] 표 → {summary_path}")
    return s


def main() -> None:
    parser = argparse.ArgumentParser(description="끝까지 측정 (개발용, FB15 #172)")
    parser.add_argument("--per-format", type=int, default=10, help="상업송장 형식마다 세트 수 (기본 10 → 30세트)")
    parser.add_argument("--sets", nargs="+", help="세트를 직접 고른다. 예: D003 D005")
    parser.add_argument("--out", type=Path, default=OUT, help=f"결과 JSONL (기본 {OUT.relative_to(ROOT)})")
    parser.add_argument("--no-cache", action="store_true", help="로컬 판독·OCR 캐시를 쓰지 않는다")
    parser.add_argument("--no-ocr", action="store_true", help="Textract OCR을 붙이지 않는다 (다시 확인이 OCR 없이 돈다)")
    parser.add_argument("--no-hs-model", action="store_true", help="HS를 모델 없이 (품명 검색만)")
    parser.add_argument("--report", action="store_true", help="모델 호출 없이 결과 파일로 표만 낸다")
    parser.add_argument("--price-in", type=float, default=PRICE_IN, help="어림 비용 입력 단가 (달러/100만 토큰)")
    parser.add_argument("--price-out", type=float, default=PRICE_OUT, help="어림 비용 출력 단가 (달러/100만 토큰)")
    parser.add_argument("--price-textract", type=float, default=PRICE_TEXTRACT, help="어림 비용 Textract 단가 (달러/쪽)")
    args = parser.parse_args()
    summary = SUMMARY if args.out == OUT else None
    prices = (args.price_in, args.price_out, args.price_textract)
    if args.report:
        report(args.out, summary, *prices)
        return
    set_ids = args.sets or pick_sets(args.per_format)
    measure(set_ids, args.out, None if args.no_cache else CACHE, ocr=not args.no_ocr, hs_model=not args.no_hs_model)
    report(args.out, summary, *prices)


if __name__ == "__main__":
    main()
