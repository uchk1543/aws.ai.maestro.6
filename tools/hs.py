"""recommend_hs. 담당: 검증. 규칙: .kiro/steering/agent-design.md 6번, 형식: docs/schema.md

작업: e2e-plan.md C1·C2 (P1). HS부호 표는 data/hs/, 확정 이력 테이블(team06-hs-history)은 4번이 infra/ PR로 정의하고 PM이 만든다.
"""

import csv
import re
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple, Protocol

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


MAX_CANDIDATES = 30  # 후보 상한 (agent-design.md 6번 3단계)
MAX_PICKS = 3  # 모델이 고르는 수 상한 (6번 4단계)
DEFAULT_HS_CSV = Path(__file__).resolve().parent.parent / "data" / "hs" / "hs_codes.csv"
_STOPWORDS = frozenset({"other", "others", "the", "and", "for", "of", "or", "기타"})  # 검색어로 쓰면 너무 흔한 말
_TOKEN_SPLIT = re.compile(r"[^0-9a-z가-힣]+")


class _Row(NamedTuple):
    """HS부호 표 한 줄. 검색용 소문자 글자(text)를 함께 둔다."""

    hsk: str
    name_ko: str
    name_en: str
    text: str


def _norm(text: str) -> str:
    """검색용으로 소문자로 바꾸고 기호를 공백 하나로 맞춘다. 앞뒤에 공백을 붙여 단어 시작을 찾기 쉽게 한다."""
    return " " + " ".join(w for w in _TOKEN_SPLIT.split(text.lower()) if w) + " "


def _has(text: str, piece: str) -> bool:
    """text 안에 piece가 있는지 본다. 영문은 단어 앞부분에서만 맞춘다('ion'이 'lions'에 맞지 않게). 한글은 어디서든 맞춘다."""
    return (" " + piece if piece.isascii() else piece) in text


def _tokens(term: str) -> list[str]:
    """검색어를 단어로 쪼갠다. 한 글자와 너무 흔한 말은 뺀다."""
    words = _TOKEN_SPLIT.split(term.lower())
    return [w for w in words if len(w) >= 2 and w not in _STOPWORDS]


def _candidate(row: _Row, reason: str) -> HSCandidate:
    return HSCandidate(hs=row.hsk, name=f"{row.name_ko} ({row.name_en})", reason=reason)


class CsvHSTable:
    """data/hs/hs_codes.csv를 메모리에 올려 두고 찾는 HS부호 표 (HSTable 구현)."""

    def __init__(self, rows: list[_Row]) -> None:
        self._rows = sorted(rows, key=lambda r: r.hsk)
        self._by_code = {r.hsk: r for r in self._rows}

    def search(self, terms: list[str], limit: int = MAX_CANDIDATES) -> list[HSCandidate]:
        """검색어로 HS 후보를 찾는다. 언제: recommend_hs 3단계.
        받는 것: terms(모델이 뽑은 한글·영문 검색어), limit(상한, 30을 넘기지 않는다).
        반환: 점수 높은 순 후보. 구절이 통째로 들어 있으면 100점, 단어 하나가 들어 있으면 10점씩이고, 검색어마다 더한다.
        점수가 같으면 부호 순이다. 하나도 안 맞으면 빈 목록이다.
        """
        limit = max(0, min(limit, MAX_CANDIDATES))
        queries = []
        for term in terms:
            phrase = _norm(term).strip()
            toks = _tokens(term)
            if toks:
                queries.append((term.strip(), phrase, toks))
        scored: list[tuple[int, _Row, list[str]]] = []
        for row in self._rows:
            score, hit = 0, []
            for term, phrase, toks in queries:
                found = sum(1 for t in toks if _has(row.text, t))
                if not found:
                    continue
                score += (100 if _has(row.text, phrase) else 0) + 10 * found
                hit.append(term)
            if score:
                scored.append((score, row, hit))
        scored.sort(key=lambda s: (-s[0], s[1].hsk))
        return [_candidate(row, f"HS부호 표 품목명이 검색어와 맞음: {', '.join(hit)}") for _, row, hit in scored[:limit]]

    def under(self, prefix6: str) -> list[HSCandidate]:
        """서류에 적힌 HS 앞 6자리 아래의 10자리 코드를 모두 낸다. 언제: recommend_hs 3단계, 서류에 HS가 있을 때.
        받는 것: prefix6(점이 섞여 있어도 된다. 예: '8507.60'). 숫자가 4자리 미만이면 빈 목록이다.
        반환: 부호 순 후보.
        """
        digits = re.sub(r"\D", "", prefix6)
        if len(digits) < 4:
            return []
        return [_candidate(r, f"서류의 HS 앞 {len(digits)}자리({digits}) 아래 코드") for r in self._rows if r.hsk.startswith(digits)]

    def exists(self, hs: str) -> bool:
        """HS부호 표에 있는 10자리 코드인지 본다. 언제: 자동 확정 조건 확인(6번)."""
        return hs in self._by_code


def load_hs_table(path: Path = DEFAULT_HS_CSV) -> CsvHSTable:
    """HS부호 CSV를 읽어 표를 만든다. 언제: 시작할 때 한 번. 받는 것: CSV 경로. 반환: CsvHSTable."""
    with open(path, encoding="utf-8", newline="") as fh:
        rows = [
            _Row(r["hsk"], r["name_ko"], r["name_en"], _norm(r["name_ko"] + " " + r["name_en"]))
            for r in csv.DictReader(fh)
        ]
    return CsvHSTable(rows)


def keep_in_candidates(picks: list[HSCandidate], candidates: list[HSCandidate]) -> list[HSCandidate]:
    """모델이 고른 것 중 후보 목록 안의 코드만 남긴다. 언제: recommend_hs 4단계 직후.
    받는 것: picks(모델 선택, 1순위부터), candidates(코드가 낸 후보).
    반환: 후보에 있는 코드만, 같은 코드는 한 번, 최대 3개. 코드와 품목명은 후보 쪽 값을 쓰고, 이유는 모델이 쓴 것을 둔다.
    """
    known = {c.hs: c for c in candidates}
    kept: dict[str, HSCandidate] = {}
    for p in picks:
        base = known.get(p.hs)
        if base is None or p.hs in kept:
            continue
        kept[p.hs] = HSCandidate(hs=base.hs, name=base.name, reason=p.reason)
    return list(kept.values())[:MAX_PICKS]


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
