"""recommend_hs. 담당: 검증. 규칙: .kiro/steering/agent-design.md 6번, 형식: docs/schema.md

작업: e2e-plan.md C1·C2 (P1). HS부호 표는 data/hs/, 확정 이력 테이블(team06-hs-history)은 4번이 infra/ PR로 정의하고 PM이 만든다.
"""

from collections.abc import Callable
from typing import Protocol

from tools.models import ExtractedDocument, HSCandidate, HSPick, HSResult, HSSearchTerms


class HSHistory(Protocol):
    """확정 이력. 키는 수입자 + 품목 키(item_key). 구현: api/ (DynamoDB), 테스트: 메모리 dict."""

    def get(self, importer: str, item_key: str) -> str | None: ...

    def put(self, importer: str, item_key: str, hs: str, job_id: str) -> None: ...


class HSTable(Protocol):
    """관세청 HS부호 표 (data/hs/ CSV를 읽어 메모리에 둔다)."""

    def search(self, terms: list[str], limit: int = 30) -> list[HSCandidate]: ...

    def under(self, prefix6: str) -> list[HSCandidate]: ...

    def exists(self, hs: str) -> bool: ...


# 모델 호출 두 가지. 테스트에서는 가짜로 바꾼다.
TermsReader = Callable[[str], HSSearchTerms]  # 품명·재질·용도 글자 → 검색어
Picker = Callable[[str, list[HSCandidate]], HSPick]  # 품명 글자, 후보 → 고른 것


def item_key(doc: ExtractedDocument, line: int) -> str:
    """확정 이력 키의 품목 부분. 품목 코드가 있으면 그것, 없으면 정규화한 품명."""
    raise NotImplementedError("C2: 품목 키 (검증 담당)")


def recommend_hs(
    docs: list[ExtractedDocument],
    line: int,
    importer: str,
    *,
    history: HSHistory,
    table: HSTable,
    terms_reader: TermsReader | None = None,
    picker: Picker | None = None,
) -> HSResult:
    """품목 한 행의 HS를 확정하거나 후보 3개를 낸다.

    언제: 대조와 다시 확인이 끝난 뒤, 품목마다.
    받는 것: docs(읽은 서류 전체), line(품목 행), importer(수입자), history·table(의존성), terms_reader·picker(테스트용 가짜 모델).
    반환: HSResult. 이력이 있으면 자동 확정(history), 6번 조건을 모두 채우면 자동 확정(auto_match), 아니면 사람 확인 필요.
    """
    print(f"[tool] recommend_hs line={line} importer={importer}")
    raise NotImplementedError("C1·C2: HS 추천과 확정 (검증 담당)")


def confirm_by_human(result: HSResult, hs: str, importer: str, key: str, job_id: str, *, history: HSHistory) -> HSResult:
    """사람이 고른 HS로 확정하고 이력에 저장한다. 모델 호출 없음.

    API 경로 POST /jobs/{id}/hs(C3, 서버 담당)가 이 함수를 부른다. 이 함수 자체는 C2(검증 담당) 몫이다.
    """
    raise NotImplementedError("C2: 사람 확정과 이력 저장 (검증 담당)")
