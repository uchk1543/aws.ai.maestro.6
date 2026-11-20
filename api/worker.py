"""처리 Lambda team06-worker 진입점. 담당: 서버. 형식: docs/schema.md 약속 2, 이벤트 약속: 이슈 #36

API Lambda(api/handler.py의 POST /jobs)가 작업을 queued로 저장한 뒤 이 함수를 비동기로(InvocationType=Event) 부른다.
    받는 이벤트: {"job_id": "job-xxxxxxxx", "files": [{"key", "doc_type"}]}
    하는 일: running으로 바꾸고 run_job을 돌린다. 단계가 늘 때마다 저장해 화면 진행 단계에 보이고,
            끝나면 waiting_approval · done · failed로 저장한다.
            HS는 recommend_hs(C1·C2)로 품목마다 추천한다 (모델 없이 품명 검색, 확정 이력은 team06-hs-history).
            마지막 저장 때 읽은 서류(docs)와 수입자(importer)를 같은 줄에 넣는다. HS 선택(C3)·승인(D3)이 읽는다 (#122).
            waiting_approval·done이고 읽은 서류가 있으면 마지막 저장 직전에 차례로 한다 (#154):
              1. 신고서 초안을 채운다 (C5 draft_declaration). 문제가 남은 칸과 확정 안 된 HS 칸은 비운다
              2. done이면 가상 WMS에 자동 등록한다 (D2, by=auto). 못 하면 waiting_approval로 바꿔 사람이 승인한다 (D3)
              3. 화물 기록(team06-shipments)에 한 줄을 쓴다 (E3, #31). 2에서 등록됐으면 처음부터 '수입신고'다
            waiting_approval이면 result.wms를 '승인 대기'로 채워 저장한다. 화면이 승인 입력을 그린다 (#159).
            서류마다 Textract OCR을 매번 돌린다 (F10 #188). run_job과 동시에 돌리고, 다시 확인(reread_field)의 두 번째 근거로
            넘긴다. PDF는 쪽 그림(JPEG)을 그려 S3(uploads/…)에 두고 그 그림을 OCR 한다. OCR 결과(ocr 칸)와 쪽 그림 목록(pages 칸)은
            같은 줄에 저장해 서류 보기(GET /jobs/{id}/files)의 쪽 그림·칸 위치에 쓴다.
            ocr 칸은 OCR_MAX_LINES 에서 자른다. 자르지 않은 결과는 S3 cache/ocr/<ocr_cache_key(파일)>.json 에 두고, 같은 파일이면
            그것을 써서 Textract 를 다시 부르지 않는다 (B4-L0, l0). NO_CACHE=1 이면 저장·재사용하지 않는다.
            OCR은 처리 시작부터 OCR_WAIT_SECONDS까지만 기다린다. 넘으면 그 서류는 OCR 없이 진행한다 (Lambda 300초 안에 끝나게).
            CLASSIFY_BY_OCR=1 이면 서류 종류를 Textract 글자의 제목 줄로 고르고, 못 정하면 Bedrock 으로 분류한다 (비용 줄이기, 기본은 끔).
제한 시간 300초. 환경 변수: JOBS_TABLE, DOCS_BUCKET, MODEL_ID, HS_HISTORY_TABLE, SHIPMENTS_TABLE, WMS_TABLE, CLASSIFY_BY_OCR(선택)

비동기 호출은 함수가 오류·시간 초과로 끝나면 Lambda가 같은 이벤트를 다시 보낸다. 그래서 저장된 상태를 보고 한 번만 처리한다.
    queued   → 처리한다
    running  → 앞선 실행이 끝을 못 냈다(시간 초과 등). 다시 돌리면 같은 이유로 멈추고 모델 호출만 늘어서 failed로 끝낸다
    그 밖    → 이미 끝난 작업이다. 아무것도 하지 않는다
"""

import hashlib
import json
import os
import time
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from functools import cache

from api import handler
from tools import declaration, hs, report
from tools.models import Classification, ExtractedDocument, HSResult, Job, OcrResult, RereadResult, Step, WmsState
from tools.extract import _strands_classifier, content_blocks
from tools.ocr import classify_from_ocr, default_ocr_cache, is_pdf, ocr_cached, ocr_document, render_pages, upright_image
from tools.query import dynamo_shipments
from tools.reread import reread_field

INTERRUPTED = "처리가 중간에 멈췄습니다 (시간 초과 등). 서류를 다시 올려 주세요"
# done인데 자동 등록 조건을 못 채웠을 때 단계 기록에 남기는 이유 (register_if_ready는 조건 미달에 이유를 붙이지 않는다)
NOT_READY = "자동 등록 조건(남은 문제 없음, 모든 품목 HS 확정)을 채우지 못했습니다. 승인하면 등록합니다"
OCR_WORKERS = 4  # 서류 OCR 을 동시에 몇 장까지
OCR_MAX_LINES = 600  # 서류 한 장에 저장할 OCR 줄 수 상한 (DynamoDB 한 줄 400KB)
# OCR 을 기다리는 상한(처리 시작부터, 초). 서류 10장 × 5쪽 × Textract(5초 × 2회)가 겹쳐도 Lambda 300초 안에 끝나게 (#194 리뷰)
OCR_WAIT_SECONDS = 100


def _save(job: Job, item: dict) -> None:
    """작업을 저장한다. item(team06-jobs 한 줄)의 다른 칸은 그대로 둔다."""
    handler.save_job(job, keep=item)


def importer_of(docs: list[ExtractedDocument]) -> str | None:
    """수입자 = 상업송장의 consignee_name raw (docs/schema.md 신고서 '수입자' 출처). 앞뒤 공백만 뗀다.

    언제: HS 이력을 찾을 때, 마지막 저장 때 importer 칸을 채울 때.
    받는 것: 읽은 서류 목록. 상업송장이 여럿이면 값이 있는 첫 서류를 쓴다.
    반환: 수입자 글자. 상업송장이 없거나 그 칸을 못 읽었으면 None.
      consignee_name 칸은 #110(B2 P1)이 약속 1에 더한다. 그 전에는 칸이 없어 늘 None이다.
    """
    for doc in docs:
        if doc.doc_type != "commercial_invoice":
            continue
        cell = getattr(doc, "consignee_name", None)  # #110 전에는 칸이 없다
        raw = (cell.raw or "").strip() if cell is not None else ""
        if raw:
            return raw
    return None


class _NoHistory:
    """수입자를 모를 때 쓰는 빈 확정 이력 (tools.hs.HSHistory 모양).

    DynamoDB 키에 빈 글자를 넣을 수 없고, 다른 수입자의 이력과 섞이면 안 되어서 찾지도 쓰지도 않는다.
    """

    def get(self, importer: str, item_key: str) -> str | None:
        return None

    def put(self, importer: str, item_key: str, hs: str, job_id: str) -> None:
        return None


@cache
def _hs_table() -> hs.CsvHSTable:
    """HS부호 표(data/hs/hs_codes.csv). Lambda 실행 환경마다 처음 한 번만 읽는다."""
    return hs.load_hs_table()


def recommend_line(docs: list[ExtractedDocument], line: int) -> HSResult:
    """run_job에 넘기는 hs_recommender. 품목 한 행의 HS를 recommend_hs로 추천한다.

    언제: run_job이 품목 행마다 부른다. 모델(terms_reader·picker)은 넘기지 않아 품명 검색만 한다.
    받는 것: docs(읽은 서류, files 순서), line(품목 행).
    반환: HSResult. 수입자를 알면 그 수입자의 확정 이력(team06-hs-history)을 쓰고, 모르면 빈 이력으로 부른다.
    """
    importer = importer_of(docs)
    history = handler._hs_history() if importer else _NoHistory()
    return hs.recommend_hs(docs, line, importer or "", history=history, table=_hs_table())


def _docs_columns(docs: list[ExtractedDocument]) -> dict:
    """마지막 저장 때 같은 줄에 더할 칸. docs는 handler._DOCS 모양(load_job_docs가 읽는다).

    읽은 서류가 없으면 빈 dict. 수입자를 모르면 importer 칸은 쓰지 않는다.
    """
    if not docs:
        return {}
    columns = {"docs": handler._DOCS.dump_json(docs).decode("utf-8")}
    importer = importer_of(docs)
    if importer:
        columns["importer"] = importer
    return columns


def page_key(key: str, number: int) -> str:
    """PDF 쪽 그림을 둘 S3 키. 원본 옆 uploads/ 아래 (처리 Lambda 권한이 uploads/* 쓰기까지다)."""
    return f"{key}.p{number}.jpg"


def ocr_cache():
    """OCR 원본 저장소 (B4-L0). DOCS_BUCKET 의 cache/ocr/, NO_CACHE=1 이면 None. 테스트는 메모리판으로 바꾼다."""
    return default_ocr_cache()


def ocr_one(key: str) -> tuple[OcrResult | None, list[dict]]:
    """서류 한 장: PDF면 쪽 그림을 그려 S3 에 두고, 그 그림(이미지는 원본)을 Textract 로 OCR 한다 (F10 #188).
    EXIF 회전이 있는 사진은 똑바로 세운 그림을 쪽 그림으로 두고 그것을 OCR 한다 (화면의 박스 방향과 맞추려고).

    반환: (OcrResult 또는 실패면 None, 쪽 그림 목록 [{"key", "width", "height"}]). 예외를 내지 않는다 (그 서류만 OCR 없이 진행).
    """
    pages: list[dict] = []
    try:
        data = handler.fetch_object(key)
        images = None
        if is_pdf(key):
            rendered = render_pages(data)
            for number, page in enumerate(rendered, start=1):
                handler.store_object(page_key(key, number), page.data, "image/jpeg")
                pages.append({"key": page_key(key, number), "width": page.width, "height": page.height})
            images = [p.data for p in rendered]
        elif (upright := upright_image(data)) is not None:  # EXIF 회전이 있는 사진은 세운 그림을 OCR·화면에 쓴다
            handler.store_object(page_key(key, 1), upright.data, "image/jpeg")
            pages.append({"key": page_key(key, 1), "width": upright.width, "height": upright.height})
            images = [upright.data]
        # 같은 파일이면 저장해 둔 OCR 을 쓰고, 아니면 Textract 로 OCR 해서 자르지 않고 S3 cache/ocr/ 에 둔다 (B4-L0)
        return ocr_cached(key, data, pages=images, cache=ocr_cache(), run=ocr_document), pages
    except Exception as exc:  # 깨진 PDF·크기·권한·타임아웃. 작업은 계속한다
        print(f"[warn] ocr key={key} {type(exc).__name__}: {exc}")
        return None, pages


class OcrRun:
    """서류마다 ocr_one 을 따로 돌린다 (F10 #188). 처리를 시작하자마자 run_job 과 동시에 시작한다.

    서류별 future 라 다시 확인(reread_field)은 그 서류의 OCR 만 기다린다. 기다리는 시간은 처리 시작부터 OCR_WAIT_SECONDS 까지다.
    넘으면 그 서류는 OCR 없이 진행한다 (#194 리뷰: 최악이면 Lambda 300초를 넘겨 running 으로 남는 것을 막는다).
    """

    def __init__(self, keys: list[str], wait_seconds: float | None = None):
        self.wait_seconds = OCR_WAIT_SECONDS if wait_seconds is None else wait_seconds
        self.deadline = time.monotonic() + self.wait_seconds
        self.pool = ThreadPoolExecutor(max_workers=OCR_WORKERS)
        self.futures: dict[str, Future] = {key: self.pool.submit(ocr_one, key) for key in keys}
        self.timed_out: list[str] = []

    def get(self, key: str) -> tuple[OcrResult | None, list[dict]]:
        """그 서류의 (OCR, 쪽 그림). 상한까지 못 끝났거나 없는 서류면 (None, [])."""
        future = self.futures.get(key)
        if future is None:
            return None, []
        try:
            return future.result(timeout=max(0.0, self.deadline - time.monotonic()))
        except FutureTimeout:
            if key not in self.timed_out:
                print(f"[warn] ocr key={key} {self.wait_seconds}초 안에 끝나지 않아 OCR 없이 진행")
                self.timed_out.append(key)
            return None, []

    def finish(self) -> dict[str, tuple[OcrResult | None, list[dict]]]:
        """모든 서류의 결과를 모은다 (상한까지만 기다림). 남은 OCR 은 기다리지 않는다."""
        results = {key: self.get(key) for key in self.futures}
        self.pool.shutdown(wait=False, cancel_futures=True)
        return results


def _ocr_step(results: dict[str, tuple[OcrResult | None, list[dict]]], timed_out: list[str] = ()) -> Step:
    done = [r for r, _ in results.values() if r is not None]
    lines = sum(len(r.lines) for r in done)
    late = f", {len(timed_out)}장은 OCR 대기 상한 안에 끝나지 않아 OCR 없이 진행" if timed_out else ""
    return Step(tool="ocr_document", summary=f"Textract OCR {len(done)}/{len(results)}장, 글자 줄 {lines}개{late}", ok=len(done) == len(results))


def _ocr_columns(results: dict[str, tuple[OcrResult | None, list[dict]]]) -> dict:
    """마지막 저장 때 같은 줄에 더할 칸: ocr(S3 키 → OcrResult, 줄 수 상한), pages(S3 키 → PDF 쪽 그림 목록)."""
    ocr = {
        key: res.model_copy(update={"lines": res.lines[:OCR_MAX_LINES], "tables": []}).model_dump(mode="json")
        for key, (res, _) in results.items() if res is not None
    }
    pages = {key: p for key, (_, p) in results.items() if p}
    columns = {}
    if ocr:
        columns["ocr"] = json.dumps(ocr, ensure_ascii=False)
    if pages:
        columns["pages"] = json.dumps(pages)
    return columns


def _rereader_with(ocr: OcrRun):
    """다시 확인에 그 서류의 OCR 을 넘긴다 (agent-design.md 4번: 스캔본·사진은 Textract 글자와 대조). 그 서류의 OCR 만 기다린다."""
    def rereader(doc: ExtractedDocument, field: str, data: bytes) -> RereadResult:
        res, _ = ocr.get(doc.file)
        return reread_field(doc, field, data, ocr=res)
    return rereader


# Bedrock 분류 (Textract 로 못 정했을 때). 테스트는 가짜로 바꾼다
_model_classifier = _strands_classifier


def _blocks_hash(blocks: list[dict]) -> str | None:
    """content_blocks 결과(첫 블록의 바이트)의 해시. 분류기가 받은 블록이 어느 파일인지 찾는 데 쓴다."""
    try:
        block = blocks[0]
        return hashlib.sha256((block.get("document") or block.get("image"))["source"]["bytes"]).hexdigest()
    except (IndexError, KeyError, TypeError):
        return None


def _ocr_classifying(ocr: OcrRun):
    """CLASSIFY_BY_OCR=1 일 때 run_job 에 넘길 (fetch, classifier).

    fetch 는 받은 파일의 content_blocks 해시 → S3 키를 적어 두고, classifier 는 그 파일의 Textract 글자에서
    제목 줄로 종류를 고른다 (tools.ocr.classify_from_ocr). 확신이 없거나 OCR 이 없으면 Bedrock 으로 분류한다.
    분류는 OCR 을 기다리므로(서류마다, OCR_WAIT_SECONDS 까지) 분류 단계가 그만큼 늦어질 수 있다.
    """
    keys: dict[str, str] = {}

    def fetch(key: str) -> bytes:
        data = handler.fetch_object(key)
        try:
            digest = _blocks_hash(content_blocks(key, data))
            if digest:
                keys[digest] = key
        except Exception as exc:  # 지원하지 않는 형식 등: 분류 때 모델로 넘어간다
            print(f"[warn] classify_by_ocr key={key} 블록 해시 실패: {type(exc).__name__}")
        return data

    def classifier(blocks: list[dict], prompt: str) -> Classification:
        key = keys.get(_blocks_hash(blocks) or "")
        got = classify_from_ocr(ocr.get(key)[0] if key else None)
        if got is not None:
            print(f"[tool] classify_from_ocr key={key} → {got.doc_type} ({got.reason})")
            return got
        print(f"[classify] key={key} Textract 제목으로 못 정함: 모델로 분류")
        return _model_classifier(blocks, prompt)

    return fetch, classifier


def _draft(job: Job, docs: list[ExtractedDocument]) -> None:
    """처리 직후 신고서 초안을 채우고 단계 한 줄을 더한다 (C8 #154, tools/declaration.draft_declaration).

    언제: 마지막 저장 직전, 작업이 waiting_approval·done이고 읽은 서류가 있을 때. 자동 등록(_register)보다 먼저.
    받는 것: run_job이 돌려준 Job(그 자리에서 고친다), docs(읽은 서류). 모델은 부르지 않는다.
    남은 문제(불일치·확인 필요)가 짚은 칸과 확정 안 된 HS 칸은 비우고 blank_fields에 적는다 (agent-design.md 7번).
    run_job이 초안을 이미 채웠으면 그대로 둔다. 사람이 HS를 고르면 POST /jobs/{id}/hs가 다시 채운다.
    예외를 내지 않는다. 못 만들면 ok=False 한 줄만 남기고 작업은 그대로 끝난다 (running으로 남지 않게).
    """
    if job.result is None or job.result.declaration_draft is not None:
        return
    try:
        draft = declaration.draft_declaration(docs, job.result.issues, job.result.hs)
    except Exception as exc:
        print(f"[error] draft_declaration job={job.job_id} {type(exc).__name__}: {exc}")
        job.steps.append(Step(tool="draft_declaration", summary=f"신고서 초안을 만들지 못함: {type(exc).__name__}", ok=False))
        return
    job.result.declaration_draft = draft
    job.steps.append(handler.draft_step(draft))


def _register(job: Job, docs: list[ExtractedDocument]) -> bool:
    """done으로 끝난 작업을 사람 손 없이 바로 가상 WMS에 등록한다 (D2 자동 등록 #154, handler.auto_register).

    언제: 마지막 저장 직전, 초안 뒤·화물 기록 앞. 작업이 done이고 읽은 서류가 있을 때.
    받는 것: run_job이 돌려준 Job(그 자리에서 고친다), docs(읽은 서류). 수입자는 importer_of(docs).
    반환: WMS에 등록된 상태면 True. 화물 기록을 처음부터 '수입신고'로 쓰는 데 쓴다 (E3).
      done이 아니면 아무것도 하지 않고 False (승인 대기는 _mark_waiting, HS를 고른 뒤 재검사는 choose_hs가 한다).
    등록하지 못하면(HS 결과 없음, B/L·수입자 없음, 가상 WMS 오류) waiting_approval로 바꾸고 result.wms = 승인 대기.
      승인(D3)은 승인 대기 작업만 받아서, done으로 두면 아무도 등록할 수 없다. 이유는 push_to_wms ok=False 한 줄.
    저장보다 등록을 먼저 한다. 화면은 waiting_approval·done을 받으면 새로 고침을 멈춰서, 승인 대기로 먼저 저장하면
      등록된 뒤에도 승인 대기로 보인다. 등록 뒤 마지막 저장이 실패하면 Lambda가 다시 보낸 이벤트에서 failed로 끝나고,
      WMS에는 그 작업 ID의 기록이 남는다 (멱등 키 "B/L#작업 ID"라 같은 작업은 두 번 들어가지 않는다).
    """
    if job.status != "done" or job.result is None:
        return False
    steps = len(job.steps)
    handler.auto_register(job, docs, importer_of(docs))
    wms_state = job.result.wms
    print(f"[worker] job={job.job_id} 자동 등록 wms={wms_state.status} wms_id={wms_state.wms_id}")
    if wms_state.status == "등록됨":
        return True
    job.status = "waiting_approval"
    if len(job.steps) == steps:  # 조건 미달이라 이유가 붙지 않았다. 왜 사람이 봐야 하는지 남긴다
        job.steps.append(Step(tool="push_to_wms", summary=f"WMS 자동 등록 못 함: {NOT_READY}", ok=False))
    return False


def _record_shipment(job_id: str, docs: list[ExtractedDocument], *, registered: bool = False) -> Step:
    """작업이 끝나면 화물 기록에 한 줄을 쓰고 그 단계 한 줄을 돌려준다 (E3, tools/report.record_shipment).

    언제: 마지막 저장 직전, 작업이 waiting_approval·done이고 읽은 서류가 있을 때. 자동 등록(_register) 뒤.
    받는 것: job_id, docs(읽은 서류), registered(방금 WMS에 자동 등록됐으면 True. 그러면 처음부터 '수입신고'로 쓴다).
    반환: Step. 예외를 내지 않는다. 저장소를 못 만들어도(SHIPMENTS_TABLE 없음 등) ok=False 한 줄만 남기고,
      작업은 그대로 끝난다 (여기서 예외가 나면 마지막 저장을 못 해 running으로 남는다).
    """
    try:
        store = dynamo_shipments()
    except Exception as exc:
        print(f"[error] {report.RECORD_TOOL} job={job_id} {type(exc).__name__}: {exc}")
        return Step(tool=report.RECORD_TOOL, summary=f"화물 기록을 쓰지 못함: {type(exc).__name__}", ok=False)
    return report.record_shipment(job_id, docs, store, registered=registered)


def _mark_waiting(job: Job) -> None:
    """승인 대기로 끝난 작업에 result.wms = 승인 대기를 넣는다 (#159).

    언제: 마지막 저장 직전. 화면은 result.wms.status가 '승인 대기'일 때만 승인 입력을 그린다(WmsPanel).
    받는 것: run_job이 돌려준 Job. 그 자리에서 고친다.
    waiting_approval이 아니거나 wms가 이미 있으면(등록됨 등) 그대로 둔다. done의 자동 등록은 _register가 한다 (#154).
    """
    if job.status != "waiting_approval" or job.result is None or job.result.wms is not None:
        return
    job.result.wms = WmsState(status="승인 대기")


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
    read: list[ExtractedDocument] = []  # run_job이 on_docs로 한 번 넘긴다 (실패해도 그때까지 읽은 서류)

    def on_step(progress: Job) -> None:
        nonlocal latest
        latest = progress
        _save(progress, item)

    started = time.perf_counter()
    ocr_run = OcrRun([f["key"] for f in files])  # run_job 과 동시에 돈다 (F10 #188)
    fetch, classifier = handler.fetch_object, None
    if os.environ.get("CLASSIFY_BY_OCR") == "1":  # 분류를 Textract 글자로 (서류마다 Bedrock 분류 호출 하나를 줄인다)
        fetch, classifier = _ocr_classifying(ocr_run)
    try:
        result = run_job(
            job_id, files, fetch, on_step=on_step, hs_recommender=recommend_line, on_docs=read.extend,
            rereader=_rereader_with(ocr_run), classifier=classifier,
        )
    except Exception as exc:  # 예상 못 한 오류도 작업 상태로 남긴다 (Lambda가 다시 돌리지 않게 여기서 끝낸다)
        print(f"[error] worker job={job_id} {type(exc).__name__}: {exc}")
        result = Job(job_id=job_id, status="failed", steps=latest.steps, error=f"{type(exc).__name__}: {exc}")
    ocr = ocr_run.finish()
    result.steps.append(_ocr_step(ocr, ocr_run.timed_out))
    print(f"[job] {job_id} status={result.status} {time.perf_counter() - started:.1f}초")
    if result.status in ("waiting_approval", "done") and read:  # 실패한 작업은 초안·등록·화물 기록을 하지 않는다
        _draft(result, read)
        registered = _register(result, read)
        result.steps.append(_record_shipment(job_id, read, registered=registered))
    _mark_waiting(result)
    columns = {**_docs_columns(read), **_ocr_columns(ocr)}
    print(f"[worker] job={job_id} 서류 기록 docs={len(read)} importer={'있음' if 'importer' in columns else '없음'}")
    _save(result, {**item, **columns})
    return {"job_id": job_id, "status": result.status}
