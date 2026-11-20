"""finish_report와 화물 기록. 담당: 판독. 규칙: .kiro/steering/agent-design.md 1·5·9번, 형식: docs/schema.md

작업: e2e-plan.md B9 (P0~P1) 조건 검사, E3 (P1) 화물 기록 쓰기·상태 고치기.
finish_report는 조건 검사만 한다. 결과 저장 · 자동 등록(D2)은 부른 쪽이 한다.
화물 기록은 부른 쪽(처리 Lambda·승인, 4번)이 record_shipment · mark_registered를 부른다. 둘 다 예외를 내지 않고
단계 기록(Step) 한 줄을 돌려준다. 화물 기록을 못 써도 작업 결과는 바뀌지 않는다.
"""

from collections.abc import Collection
from datetime import date

from tools.models import DOC_TYPE_KO, ExtractedDocument, JobState, ReportCheck, Shipment, Step
from tools.query import SeedRowExists, ShipmentWriter

# 조건마다 빠졌을 때 부를 도구. 메시지 끝에 (도구 이름)으로 붙여 에이전트가 바로 고르게 한다.
REREAD = "reread_field"
HS = "recommend_hs"


def hs_lines(state: JobState) -> list[int]:
    """HS를 돌려야 하는 품목 행. 상업송장의 행을 쓰고, 상업송장을 못 읽었으면 읽은 서류 전체의 행."""
    docs = list(state.docs.values())
    source = [d for d in docs if d.doc_type == "commercial_invoice"] or docs
    return sorted({item.line for doc in source for item in doc.items})


def finish_report(
    state: JobState, *, handed_over: Collection[str] = (), skip: Collection[str] = ()
) -> ReportCheck:
    """리포트를 마무리해도 되는지 코드로 검사한다.

    언제: 에이전트가 일을 다 했다고 판단할 때. 못 채우면 missing을 보고 빠진 도구를 다시 부른다.
    받는 것:
      - state: JobState.
      - handed_over: 분류나 읽기에 실패해 사람에게 넘긴 파일(S3 키). '모두 분류하고 읽었다'에서 뺀다.
      - skip: 아직 없는 도구 이름('reread_field', 'recommend_hs'). 그 조건은 검사하지 않는다 (P0에서 B8·C1·C2 전).
    반환: ReportCheck. 검사 조건 (agent-design.md 1번):
      - 올라온 서류를 모두 분류하고 읽었다 (unknown은 읽지 않고 사람에게 묻는다)
      - 마지막 읽기 뒤에 cross_check를 돌렸다 (check_seq == read_seq)
      - 불일치 칸을 모두 다시 확인했다 (rereads에 같은 서류·칸이 있다)
      - 모든 품목에 recommend_hs를 돌렸다 (확정 또는 사람 확인 필요)
    missing 한 줄은 '무엇이 빠졌나 (부를 도구)' 모양이다. 예: 'uploads/s1/pl.pdf 아직 안 읽음 (read_document)'.
    ok이면 부른 쪽이 작업을 저장하고, 화물 기록을 쓰고, 자동 등록 조건을 검사한다.
    """
    print(f"[tool] finish_report job={state.job_id} files={len(state.files)} skip={sorted(skip)}")
    handed = set(handed_over)
    missing: list[str] = []

    # 1. 모두 분류하고 읽었다
    for key in state.files:
        if key in handed:
            continue
        doc_type = state.doc_types.get(key)
        if doc_type is None:
            missing.append(f"{key} 아직 분류 안 함 (classify_document)")
        elif doc_type != "unknown" and key not in state.docs:
            missing.append(f"{key} 아직 안 읽음 (read_document)")

    # 2. 마지막 읽기 뒤에 cross_check
    if state.read_seq and state.check_seq != state.read_seq:
        missing.append("마지막 읽기 뒤에 대조 안 함 (cross_check)")

    # 3. 불일치 칸을 모두 다시 확인
    if REREAD not in skip:
        done = {(r.doc, r.field) for r in state.rereads}
        for issue in state.issues:
            if issue.grade != "불일치":
                continue
            for cell in issue.cells:
                if (cell.doc, cell.field) in done:
                    continue
                keys = [k for k in state.files if k in state.docs and state.docs[k].doc_type == cell.doc]
                where = ", ".join(keys) or DOC_TYPE_KO[cell.doc]
                missing.append(f"{where} {cell.field} 다시 확인 안 함 ({REREAD})")

    # 4. 모든 품목에 recommend_hs
    if HS not in skip:
        have = {h.line for h in state.hs}
        missing.extend(f"{line}행 HS 안 돌림 ({HS})" for line in hs_lines(state) if line not in have)

    missing = list(dict.fromkeys(missing))  # 같은 줄은 한 번만 (순서 유지)
    return ReportCheck(ok=not missing, missing=missing)


# ---------------------------------------------------------------------------
# 화물 기록 (E3). docs/schema.md '화물 기록'
# ---------------------------------------------------------------------------
RECORD_TOOL = "record_shipment"
REGISTER_TOOL = "mark_registered"
STATUS_ORDER = ("입항", "수입신고", "심사 중", "검사 중", "수리", "반출")  # docs/schema.md 진행 순서
NEW_STATUS = "입항"  # 작업이 끝나 처음 쓰는 상태. 서류에는 입항일이 없어서 입항일은 처리한 날(한국 시간)로 둔다
REGISTERED_STATUS = "수입신고"  # 가상 WMS에 등록되면 (D2 자동 · D3 사람 승인)
MAX_ITEM = 60  # 대표 품명 길이 (현황 답에 그대로 나온다)


def _today() -> date:
    from agent import today_kst  # agent → tools.report 순환을 피하려고 여기서 부른다

    return date.fromisoformat(today_kst())


def _text(cell) -> str | None:
    """칸의 raw를 한 줄로. 비었거나 못 읽었으면 None."""
    raw = getattr(cell, "raw", None) if cell is not None else None
    text = " ".join(raw.split()) if raw else ""
    return text or None


def _first(docs: list[ExtractedDocument], doc_type: str) -> ExtractedDocument | None:
    return next((d for d in docs if d.doc_type == doc_type), None)


def shipment_row(job_id: str, docs: list[ExtractedDocument], today: date) -> tuple[Shipment | None, str]:
    """작업 하나의 화물 기록 한 줄을 만든다. 쓰지 않는다.

    받는 것: job_id, 읽은 서류, today(처리한 날, 한국 시간).
    반환: (Shipment, '') 또는 (None, 못 만든 이유).
      bl_no: 선하증권 B/L No. (없으면 못 만든다. 테이블 키다)
      consignee: 상업송장 → 선하증권 → 포장명세서 순서로 처음 읽힌 consignee_name (없으면 못 만든다)
      item: 상업송장(없으면 포장명세서·원산지증명서) 첫 품목 품명. 품목이 여럿이면 '… 외 N개 품목'
      arrived_at·last_event_at: today, customs_status: '입항', job_id
    """
    bl = _first(docs, "bill_of_lading")
    bl_no = _text(bl.doc_no) if bl else None
    if not bl_no:
        return None, "선하증권 B/L 번호가 없어 화물 기록을 쓰지 않음 (선하증권을 함께 올리면 기록된다)"
    invoice, packing = _first(docs, "commercial_invoice"), _first(docs, "packing_list")
    consignee = next((v for d in (invoice, bl, packing) if d and (v := _text(d.consignee_name))), None)
    if not consignee:
        return None, f"B/L {bl_no}: 수하인(Consignee)을 읽지 못해 화물 기록을 쓰지 않음"
    source = invoice or packing or _first(docs, "certificate_of_origin")
    names = [n for it in (source.items if source else []) if (n := _text(it.name))]
    item = names[0][:MAX_ITEM] if names else "품명 없음"
    if len(names) > 1:
        item += f" 외 {len(names) - 1}개 품목"
    row = Shipment(
        bl_no=bl_no, consignee=consignee, item=item, arrived_at=today,
        customs_status=NEW_STATUS, last_event_at=today, job_id=job_id,
    )
    return row, ""


def record_shipment(
    job_id: str,
    docs: list[ExtractedDocument],
    store: ShipmentWriter,
    *,
    registered: bool = False,
    today: date | None = None,
) -> Step:
    """작업이 끝나면 화물 기록(team06-shipments)에 한 줄을 넣는다 (E3).

    언제: 처리 Lambda가 작업을 waiting_approval·done으로 저장할 때 (실패한 작업은 쓰지 않는다).
    받는 것: job_id, 읽은 서류(run_job의 on_docs), store(DynamoShipments), registered(이미 WMS에 자동 등록됐으면 True).
    반환: Step(tool='record_shipment'). 작업 steps에 붙이면 화면 진행 단계에 보인다.
      - 새 B/L: 입항일 = 처리한 날, 상태 '입항'(registered면 '수입신고')
      - 같은 B/L을 다시 처리: 입항일·상태는 그대로 두고 job_id·수하인·품명·마지막 변경일만 새로 쓴다
      - 미리 넣은 가상 기록(job_id 없음)과 B/L이 같으면 덮어쓰지 않는다
      - B/L 번호·수하인이 없으면 쓰지 않는다. 저장 오류는 ok=False로 남기고 예외를 내지 않는다
    """
    today = today or _today()
    row, why = shipment_row(job_id, docs, today)
    if row is None:
        print(f"[report] {RECORD_TOOL} job={job_id} {why}")
        return Step(tool=RECORD_TOOL, summary=why, ok=True)  # 쓸 것이 없을 뿐 도구 오류는 아니다
    if registered:
        row = row.model_copy(update={"customs_status": REGISTERED_STATUS})
    try:
        existing = store.get(row.bl_no)
        if existing is not None and existing.job_id is None:
            raise SeedRowExists(row.bl_no)
        if existing is not None:  # 같은 B/L을 다시 처리했다. 입항일과 진행한 상태는 지킨다
            status = existing.customs_status
            if registered and _before(status, REGISTERED_STATUS):
                status = REGISTERED_STATUS
            row = row.model_copy(update={"arrived_at": existing.arrived_at, "customs_status": status})
        store.put(row)
    except SeedRowExists:
        summary = f"B/L {row.bl_no}: 미리 넣은 화물 기록이 있어 덮어쓰지 않음"
        print(f"[report] {RECORD_TOOL} job={job_id} {summary}")
        return Step(tool=RECORD_TOOL, summary=summary, ok=True)
    except Exception as exc:  # DynamoDB 오류 등. 작업 결과는 그대로 두고 단계에만 남긴다
        print(f"[error] {RECORD_TOOL} job={job_id} {type(exc).__name__}: {exc}")
        return Step(tool=RECORD_TOOL, summary=f"화물 기록을 쓰지 못함: {type(exc).__name__}", ok=False)
    summary = f"화물 기록 B/L {row.bl_no}: {row.customs_status}, 입항일 {row.arrived_at.isoformat()}"
    print(f"[report] {RECORD_TOOL} job={job_id} {summary}")
    return Step(tool=RECORD_TOOL, summary=summary, ok=True)


def _before(status: str, target: str) -> bool:
    """status가 진행 순서에서 target보다 앞인지. 모르는 값이면 False (고치지 않는다)."""
    return status in STATUS_ORDER and STATUS_ORDER.index(status) < STATUS_ORDER.index(target)


def mark_registered(job_id: str, bl_no: str, store: ShipmentWriter, *, today: date | None = None) -> Step:
    """가상 WMS에 등록되면 그 작업의 화물 기록 상태를 '수입신고'로 고친다 (E3).

    언제: 사람 승인(D3, POST /jobs/{id}/approve)이나 자동 등록(D2)으로 WMS에 등록된 직후. bl_no는 WMS 기록의 B/L 번호.
    반환: Step(tool='mark_registered'). 이 작업이 쓴 줄만 고친다 (미리 넣은 기록·다른 작업의 기록은 그대로).
      이미 '수입신고'보다 뒤의 상태면 그대로 둔다. 저장 오류는 ok=False로 남기고 예외를 내지 않는다.
    """
    today = today or _today()
    try:
        row = store.get(bl_no)
        if row is None:
            summary, ok = f"B/L {bl_no}: 화물 기록이 없어 상태를 고치지 않음", True
        elif row.job_id != job_id:
            summary, ok = f"B/L {bl_no}: 이 작업이 쓴 화물 기록이 아니라 상태를 고치지 않음", True
        elif not _before(row.customs_status, REGISTERED_STATUS):
            summary, ok = f"B/L {bl_no}: 이미 {row.customs_status}라 상태를 그대로 둠", True
        else:
            store.put(row.model_copy(update={"customs_status": REGISTERED_STATUS, "last_event_at": today}))
            summary, ok = f"화물 기록 B/L {bl_no}: {row.customs_status} → {REGISTERED_STATUS}", True
    except Exception as exc:  # DynamoDB 오류 등
        print(f"[error] {REGISTER_TOOL} job={job_id} {type(exc).__name__}: {exc}")
        return Step(tool=REGISTER_TOOL, summary=f"화물 기록 상태를 고치지 못함: {type(exc).__name__}", ok=False)
    print(f"[report] {REGISTER_TOOL} job={job_id} {summary}")
    return Step(tool=REGISTER_TOOL, summary=summary, ok=ok)
