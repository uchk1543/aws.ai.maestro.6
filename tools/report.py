"""finish_report. 담당: 판독. 규칙: .kiro/steering/agent-design.md 1·5번, 형식: docs/schema.md

작업: e2e-plan.md B9 (P0~P1). 조건 검사만 한다. 결과 저장 · 화물 기록(E3) · 자동 등록(D2)은 부른 쪽이 한다.
"""

from collections.abc import Collection

from tools.models import DOC_TYPE_KO, JobState, ReportCheck

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
