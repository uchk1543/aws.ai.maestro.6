"""recommend_hs. 담당: 검증. 규칙: .kiro/steering/agent-design.md 6번, 형식: docs/schema.md

작업: e2e-plan.md C1·C2 (P1). HS부호 표는 data/hs/, 확정 이력 테이블(team06-hs-history)은 4번이 infra/ PR로 정의하고 PM이 만든다.
"""

import csv
import math
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
    category: str = ""  # 성질통합분류(상위 분류). 이름이 '기타'뿐인 줄이 무슨 물건인지 알려 준다


def _norm(text: str) -> str:
    """검색용으로 소문자로 바꾸고 기호를 공백 하나로 맞춘다. 앞뒤에 공백을 붙여 단어 시작을 찾기 쉽게 한다."""
    return " " + " ".join(w for w in _TOKEN_SPLIT.split(text.lower()) if w) + " "


def _has(text: str, piece: str) -> bool:
    """text 안에 piece가 있는지 본다. 영문은 단어 앞부분에서만 맞춘다('ion'이 'lions'에 맞지 않게). 한글은 어디서든 맞춘다."""
    return (" " + piece if piece.isascii() else piece) in text


def _tokens(term: str) -> list[str]:
    """검색어를 단어로 쪼갠다. 한 글자, 너무 흔한 말, 숫자가 든 단어(10, 50L, M10X50)는 뺀다. 표 이름에 거의 없어 잡음만 된다."""
    words = _TOKEN_SPLIT.split(term.lower())
    return [w for w in words if len(w) >= 2 and w not in _STOPWORDS and not re.search(r"\d", w)]


def _candidate(row: _Row, reason: str) -> HSCandidate:
    name = f"{row.name_ko} ({row.name_en})"
    return HSCandidate(hs=row.hsk, name=f"{name} [{row.category}]" if row.category else name, reason=reason)





class CsvHSTable:
    """data/hs/hs_codes.csv를 메모리에 올려 두고 찾는 HS부호 표 (HSTable 구현)."""

    def __init__(self, rows: list[_Row]) -> None:
        self._rows = sorted(rows, key=lambda r: r.hsk)
        self._by_code = {r.hsk: r for r in self._rows}
        self._words = [frozenset(r.text.split()) for r in self._rows]
        self._vocab = frozenset(w for ws in self._words for w in ws if w.isascii())
        self._hit_cache: dict[str, dict[int, float]] = {}
        self._prefix: dict[str, frozenset[str]] = {}

    def _word_match(self, tok: str, text: str, words: frozenset[str]) -> float:
        """단어 하나가 표 한 줄에 맞는 정도. 영문은 같은 단어(복수형 s·es 포함)면 1, 단어 앞부분만 같으면 0.3,
        한글은 어디서든 들어 있으면 1. 안 맞으면 0. ('ion'이 'lions'에, 'plate'가 'platessa'에 세게 맞지 않게)"""
        if not tok.isascii():
            return 1.0 if tok in text else 0.0
        if tok in words or tok + "s" in words or tok + "es" in words:
            return 1.0
        starts = self._prefix.get(tok)
        if starts is None:
            starts = self._prefix[tok] = frozenset(w for w in self._vocab if w.startswith(tok))
        return 0.3 if not words.isdisjoint(starts) else 0.0

    def _hits(self, tok: str) -> dict[int, float]:
        """단어 하나가 맞는 줄(번호 → 맞는 정도). 한 번 구하면 기억해 둔다."""
        got = self._hit_cache.get(tok)
        if got is None:
            got = {}
            for i, (row, words) in enumerate(zip(self._rows, self._words)):
                m = self._word_match(tok, row.text, words)
                if m > 0:
                    got[i] = m
            self._hit_cache[tok] = got
        return got

    def _weight(self, tok: str) -> float:
        """단어의 무게. 표에 드문 단어일수록 크다(log). 'white'처럼 흔한 단어는 작고, 'melamine'처럼 드문 단어는 크다."""
        n = len(self._hits(tok))
        return max(math.log((len(self._rows) + 1) / (n + 1)), 0.1)

    def search(self, terms: list[str], limit: int = MAX_CANDIDATES) -> list[HSCandidate]:
        """검색어로 HS 후보를 찾는다. 언제: recommend_hs 3단계.
        받는 것: terms(모델이 뽑은 한글·영문 검색어), limit(상한, 30을 넘기지 않는다).
        반환: 점수 높은 순 후보. 검색어의 단어마다 (맞는 정도 × 단어 무게)를 더하고, 단어가 둘 이상인 구절이 통째로 들어 있으면
        10점을 더한다. 검색어마다 더한다. 점수가 같으면 부호 순이다. 하나도 안 맞으면 빈 목록이다.
        표 이름에는 상위 분류(예: 가구, 일차전지 및 축전지)도 들어 있어 '기타'뿐인 줄도 찾을 수 있다.
        """
        limit = max(0, min(limit, MAX_CANDIDATES))
        score: dict[int, float] = {}
        matched: dict[int, list[str]] = {}
        for term in terms:
            toks = _tokens(term)
            if not toks:
                continue
            phrase = _norm(term).strip() if len(toks) > 1 else ""
            per_row: dict[int, float] = {}
            for t in toks:
                w = self._weight(t)
                for i, m in self._hits(t).items():
                    per_row[i] = per_row.get(i, 0.0) + m * w
            for i, got in per_row.items():
                if phrase and _has(self._rows[i].text, phrase):
                    got += 10
                score[i] = score.get(i, 0.0) + got
                matched.setdefault(i, []).append(term.strip())
        ranked = sorted(score, key=lambda i: (-score[i], i))  # 줄 번호는 부호 순이다
        return [
            _candidate(self._rows[i], f"HS부호 표 품목명이 검색어와 맞음: {', '.join(matched[i])}") for i in ranked[:limit]
        ]

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
            _Row(
                r["hsk"], r["name_ko"], r["name_en"],
                _norm(r["name_ko"] + " " + r["name_en"] + " " + r.get("category", "")), r.get("category", ""),
            )
            for r in csv.DictReader(fh)
        ]
    return CsvHSTable(rows)


def is_known_hs(hs: str, table: HSTable) -> bool:
    """사람이 직접 넣은 HS가 관세청 HS부호 표에 있는 10자리 코드인지 본다.
    언제: 사람이 후보 밖 코드를 직접 넣었을 때. 서버(POST /jobs/{id}/hs)가 이 결과가 거짓이면 400으로 돌려보낸다.
    받는 것: hs(입력한 코드), table(HS부호 표).
    반환: 10자리 숫자이고 표에 있으면 True, 아니면 False. 공백과 점이 섞인 글자는 False다(화면이 숫자만 보낸다).
    """
    return re.fullmatch(r"[0-9]{10}", hs) is not None and table.exists(hs)


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


def _doc_hs_text(items: list[tuple[ExtractedDocument, ExtractedItem]]) -> str | None:
    """서류에 적힌 HS를 적힌 그대로(점 포함) 꺼낸다. 서류 우선순위대로 처음 있는 것. 없으면 None."""
    for _, it in items:
        text = _cell_text(it.hs_code)
        if text:
            return text
    return None


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
    name = next((t for _, it in items if (t := _cell_text(it.name))), "")
    shown_info = {"item_name": name or None, "doc_hs_code": _doc_hs_text(items)}  # 화면이 '1행 · 품명 (서류 HS)'로 보여 준다

    # 1. 확정 이력. 이력의 코드가 HS부호 표에 없으면 믿지 않고 다음 단계로 간다.
    if key is not None:
        saved = history.get(importer, key)
        if saved and table.exists(saved):
            print(f"[hs] 확정 이력 사용 key={key} hs={saved}")
            return HSResult(line=line, status="자동 확정", by="history", hs_code=saved, candidates=[], **shown_info)

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
        return HSResult(line=line, status="자동 확정", by="auto_match", hs_code=doc_hs[0], candidates=picks, **shown_info)
    return HSResult(line=line, status="사람 확인 필요", by=None, hs_code=None, candidates=shown, **shown_info)


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
    return HSResult(
        line=result.line, status="사람 확정", by="human", hs_code=hs, candidates=result.candidates,
        item_name=result.item_name, doc_hs_code=result.doc_hs_code,
    )
