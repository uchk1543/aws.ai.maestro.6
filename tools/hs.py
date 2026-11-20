"""recommend_hs. 담당: 검증. 규칙: .kiro/steering/agent-design.md 6번, 형식: docs/schema.md

작업: e2e-plan.md C1·C2 (P1). HS부호 표는 data/hs/, 확정 이력 테이블(team06-hs-history)은 4번이 infra/ PR로 정의하고 PM이 만든다.
"""

import csv
import re
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple, Protocol

from tools.models import Cell, ExtractedDocument, ExtractedItem, HSCandidate, HSPick, HSResult, HSSearchTerms
from tools.validate import normalize_text


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

_DOC_ORDER = ("commercial_invoice", "packing_list", "bill_of_lading", "certificate_of_origin")  # 품목 정보를 읽을 서류 우선순위


def _items_at(docs: list[ExtractedDocument], line: int) -> list[tuple[ExtractedDocument, ExtractedItem]]:
    """서류마다 그 행 번호의 품목을 모은다. 상업송장부터 순서대로."""
    rank = {t: i for i, t in enumerate(_DOC_ORDER)}
    found = []
    for doc in sorted(docs, key=lambda d: rank.get(d.doc_type, len(rank))):
        for item in doc.items:
            if item.line == line:
                found.append((doc, item))
                break
    return found


def _cell_text(cell: Cell | None) -> str | None:
    """칸에서 글자를 꺼낸다. value가 글자면 그것, 아니면 raw. 비었으면 None."""
    if cell is None:
        return None
    for v in (cell.value, cell.raw):
        if v is not None and str(v).strip():
            return str(v).strip()
    return None


def _item_key_of(item: ExtractedItem) -> str | None:
    code = _cell_text(item.item_code)
    if code:
        return "code:" + re.sub(r"\s+", "", code).upper()
    name = _cell_text(item.name)
    if name:
        return "name:" + normalize_text("name", name)
    return None


def item_key(doc: ExtractedDocument, line: int) -> str:
    """확정 이력 키의 품목 부분. 품목 코드가 있으면 그것, 없으면 정규화한 품명.
    언제: 이력을 찾거나 저장하기 전. 받는 것: doc(읽은 서류), line(품목 행 번호).
    반환: 'code:BP-200' 또는 'name:lithium ion battery pack'. 코드와 품명이 서로 섞이지 않게 앞에 종류를 붙인다.
    그 행이 없거나 코드도 품명도 못 읽었으면 ValueError.
    """
    for item in doc.items:
        if item.line == line:
            key = _item_key_of(item)
            if key:
                return key
            raise ValueError(f"{line}행에 품목 코드와 품명이 모두 없음")
    raise ValueError(f"{line}행이 서류에 없음")


def _hs_digits(cell: Cell | None) -> str | None:
    """서류에 적힌 HS를 숫자만 남겨 꺼낸다. 없으면 None."""
    text = _cell_text(cell)
    digits = re.sub(r"\D", "", text) if text else ""
    return digits or None


def _dedupe(cands: list[HSCandidate]) -> list[HSCandidate]:
    seen: dict[str, HSCandidate] = {}
    for c in cands:
        seen.setdefault(c.hs, c)
    return list(seen.values())


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
    모델(terms_reader, picker)이 없거나 실패하면 자동 확정 없이 사람 확인 필요로 간다. 품명을 그대로 검색어로 쓴다.
    """
    print(f"[tool] recommend_hs line={line} importer={importer}")
    items = _items_at(docs, line)
    key = next((k for _, it in items if (k := _item_key_of(it))), None)

    # 1. 확정 이력. 이력의 코드가 HS부호 표에 없으면 믿지 않고 다음 단계로 간다.
    if key is not None:
        saved = history.get(importer, key)
        if saved and table.exists(saved):
            print(f"[hs] 확정 이력 사용 key={key} hs={saved}")
            return HSResult(line=line, status="자동 확정", by="history", hs_code=saved, candidates=[])

    name = next((t for _, it in items if (t := _cell_text(it.name))), "")

    # 2. 모델이 검색어를 뽑는다. 못 하면 품명을 그대로 쓴다.
    terms = [name] if name else []
    if terms_reader is not None and name:
        try:
            got = terms_reader(name).terms
            if got:
                terms = got
        except Exception as e:  # 모델 호출 실패는 판정에 영향 없이 품명 검색으로 대신한다
            print(f"[hs] 검색어 뽑기 실패, 품명으로 검색: {type(e).__name__}")

    # 3. 후보: 서류 HS 앞 6자리 아래 10자리 + 표 검색(최대 30개)
    doc_hs = [d for _, it in items if (d := _hs_digits(it.hs_code))]
    cands: list[HSCandidate] = []
    for d in dict.fromkeys(doc_hs):
        if len(d) >= 6:
            cands += table.under(d[:6])
    cands += table.search(terms, limit=MAX_CANDIDATES)
    cands = _dedupe(cands)

    # 4. 모델이 후보 안에서 고른다. 후보 밖 코드는 버린다.
    picks: list[HSCandidate] = []
    if picker is not None and cands:
        try:
            picks = keep_in_candidates(picker(name, cands).picks, cands)
        except Exception as e:
            print(f"[hs] 후보 고르기 실패: {type(e).__name__}")
    shown = picks or cands[:MAX_PICKS]

    # 5. 자동 확정: 서류에 적힌 10자리가 모두 같고, 표에 있고, 모델 1순위와 같을 때만
    same = len(set(doc_hs)) == 1 and len(doc_hs[0]) == 10
    if same and table.exists(doc_hs[0]) and picks and picks[0].hs == doc_hs[0]:
        return HSResult(line=line, status="자동 확정", by="auto_match", hs_code=doc_hs[0], candidates=picks)
    return HSResult(line=line, status="사람 확인 필요", by=None, hs_code=None, candidates=shown)


def confirm_by_human(result: HSResult, hs: str, importer: str, key: str, job_id: str, *, history: HSHistory) -> HSResult:
    """사람이 고른 HS로 확정하고 이력에 저장한다. 모델 호출 없음.
    API 경로 POST /jobs/{id}/hs(C3, 서버 담당)가 이 함수를 부른다. 이 함수 자체는 C2(검증 담당) 몫이다.
    언제: 사람이 화면에서 후보 중 하나를 골랐을 때.
    받는 것: result(그 행의 HSResult), hs(고른 10자리), importer(수입자), key(item_key 값), job_id(작업 ID), history(이력 저장소).
    반환: 사람 확정 HSResult. 10자리 숫자가 아니면 ValueError이고 이력에 아무것도 쓰지 않는다.
    """
    print(f"[tool] confirm_by_human line={result.line} hs={hs} importer={importer}")
    if not re.fullmatch(r"\d{10}", hs):
        raise ValueError(f"HS는 10자리 숫자여야 함: {hs!r}")
    history.put(importer, key, hs, job_id)
    return HSResult(line=result.line, status="사람 확정", by="human", hs_code=hs, candidates=result.candidates)
