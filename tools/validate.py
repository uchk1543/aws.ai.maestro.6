"""서류 교차 검증. 담당: 검증. 규칙: .kiro/steering/agent-design.md 3·5번, 형식: docs/schema.md 약속 2

P0 규칙 셋(X-INV-01 송장 번호, X-QTY-01 총수량, X-WT-01 총중량)은 서류 전체 값만 비교한다.
규칙 문장틀과 허용 오차는 tools/rules/rules.csv, 비교 전에 맞추는 표기(단위 별칭, 번호·품명 정리)는
tools/rules/units.csv, tools/rules/text_rules.csv 에 있다.
"""

import csv
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from tools.models import DOC_TYPE_KO, Cell, ExtractedDocument, Grade, Issue, IssueCell

RULES_DIR = Path(__file__).parent / "rules"
RULES_CSV = RULES_DIR / "rules.csv"
UNITS_CSV = RULES_DIR / "units.csv"
TEXT_RULES_CSV = RULES_DIR / "text_rules.csv"
_EPS = 1e-9


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


@cache
def load_rules() -> dict[tuple[str, str], dict[str, str]]:
    """rules.csv를 (rule_id, 등급) → 행으로 읽는다."""
    return {(row["rule_id"], row["grade"]): row for row in _read_csv(RULES_CSV)}


def _rule(rule_id: str, grade: Grade) -> dict[str, str]:
    return load_rules()[(rule_id, grade)]


@cache
def _rule_ids() -> list[str]:
    """rules.csv에 나온 순서대로 본 rule_id 목록."""
    return list(dict.fromkeys(rule_id for rule_id, _ in load_rules()))


# ---------------------------------------------------------------------------
# 정규화: 비교하기 전에 표기를 맞춘다
# ---------------------------------------------------------------------------
@cache
def load_units() -> dict[str, str]:
    """units.csv를 별칭(대문자) → 표준 단위 이름으로 읽는다."""
    return {row["alias"].strip().upper(): row["canonical"] for row in _read_csv(UNITS_CSV)}


@cache
def _text_ops() -> dict[str, str]:
    """text_rules.csv를 대상(invoice_no, name) → 연산 이름으로 읽는다."""
    return {row["target"]: row["operation"] for row in _read_csv(TEXT_RULES_CSV)}


def normalize_unit(alias: str) -> str:
    """단위 별칭을 표준 이름으로 바꾼다. 표에 없으면 대문자로만 맞춘다. 예: 'cartons' → 'CTN'."""
    key = alias.strip().upper()
    return load_units().get(key, key)


def normalize_text(target: str, text: str) -> str:
    """text_rules.csv의 연산으로 글자를 맞춘다. 예: ('invoice_no', 'QDT/26/0279') → 'QDT260279'."""
    op = _text_ops().get(target)
    if op is None:
        return text.strip()
    if op == "keep_alnum_upper":  # 영문·숫자만 남기고 대문자로
        return re.sub(r"[^0-9A-Z]", "", text.upper())
    if op == "lower_alnum_words":  # 소문자, 영문·숫자·한글 아닌 문자는 공백 하나로
        return " ".join(re.sub(r"[^0-9a-z가-힣]+", " ", text.lower()).split())
    raise ValueError(f"text_rules.csv에 없는 연산: {op}")


# ---------------------------------------------------------------------------
# 서류에서 비교할 값 꺼내기
# ---------------------------------------------------------------------------
def _fmt(value: float) -> str:
    """6250.0 → '6,250', 6250.25 → '6,250.25'."""
    return f"{value:,.3f}".rstrip("0").rstrip(".")


@dataclass
class _Read:
    """서류 한 장에서 읽은 비교 값 하나."""

    key: float | str | None  # 비교에 쓰는 값(정규화한 값). 못 구했으면 None
    field: str  # 칸 경로. 예: 'total_gross_kg', 'items[*].qty'
    raw: str | None  # 서류에 적힌 그대로
    reason: str | None = None  # key가 None일 때 못 구한 이유
    shown: str = ""  # 근거 문장에 쓰는 값
    notation: str | None = None  # 표기 차이를 볼 때 쓰는 값(수량의 단위 표기, 번호의 원래 글자)


def _total_value(
    doc: ExtractedDocument, total: Cell | None, total_field: str, item_attr: str
) -> tuple[float | None, str, str | None, str | None]:
    """서류 전체 숫자 값. (값, 칸 경로, raw, 못 구한 이유)

    합계 칸을 먼저 쓰고, 없거나 못 읽었으면 행별 값을 코드가 더한다. 행 하나라도 못 읽었으면 값은 None.
    """
    if total is not None and isinstance(total.value, (int, float)):
        return float(total.value), total_field, total.raw, None
    cells = [getattr(item, item_attr) for item in doc.items]
    if cells and all(c is not None and isinstance(c.value, (int, float)) for c in cells):
        raw = " + ".join(c.raw or "" for c in cells)
        return round(sum(float(c.value) for c in cells), 3), f"items[*].{item_attr}", raw, None
    # 못 구한 이유: 합계 칸 → 행 순서로, 값을 못 구한 첫 칸의 이유
    paths = [total_field, *(f"items[{i}].{item_attr}" for i in range(len(cells)))]
    for path, cell in zip(paths, [total, *cells]):
        if cell is None or isinstance(cell.value, (int, float)):
            continue
        if cell.unreadable:
            return None, path, cell.raw, cell.unreadable
        if cell.raw is not None:
            return None, path, cell.raw, "숫자로 풀 수 없음"
    return None, total_field, None, "칸 없음"


def _read_total_gross(doc: ExtractedDocument) -> _Read:
    value, field, raw, reason = _total_value(doc, doc.total_gross_kg, "total_gross_kg", "gross_kg")
    return _Read(value, field, raw, reason, shown="" if value is None else _fmt(value))


def _raw_unit(raw: str | None) -> str | None:
    """'2,650 CTNS' → 'CTNS'. 수 뒤의 첫 영문 단어."""
    match = re.search(r"\d[\d,]*(?:\.\d+)?\s*([A-Za-z]+)", raw or "")
    return match.group(1).upper() if match else None


def _read_total_qty(doc: ExtractedDocument) -> _Read:
    value, field, raw, reason = _total_value(doc, doc.total_qty, "total_qty", "qty")
    unit = _raw_unit(raw) if field == "total_qty" else None  # 행을 더한 값은 단위 표기를 보지 않는다
    return _Read(value, field, raw, reason, shown="" if value is None else _fmt(value), notation=unit)


def _read_invoice_no(doc: ExtractedDocument) -> _Read:
    """송장 번호. 포장명세서의 doc_no에도 송장 번호가 들어온다 (tools/extract.py)."""
    cell = doc.doc_no
    if cell is None:
        return _Read(None, "doc_no", None, "칸 없음")
    if isinstance(cell.value, str) and cell.value.strip():
        key = normalize_text("invoice_no", cell.value)
        if key:
            return _Read(key, "doc_no", cell.raw, shown=cell.value.strip(), notation=cell.value.strip())
        return _Read(None, "doc_no", cell.raw, "번호로 읽을 글자가 없음")
    return _Read(None, "doc_no", cell.raw, cell.unreadable or "칸 없음")


# 칸 이름(rules.csv target) → (읽는 함수, 숫자인지)
_READERS: dict[str, tuple[Callable[[ExtractedDocument], _Read], bool]] = {
    "total_gross_kg": (_read_total_gross, True),
    "total_qty": (_read_total_qty, True),
    "invoice_no": (_read_invoice_no, False),
}


# ---------------------------------------------------------------------------
# 규칙 하나를 서류들에 적용
# ---------------------------------------------------------------------------
def _ckey(read: _Read) -> float | str:
    """다수결과 같음 비교에 쓰는 값. 숫자는 소수 셋째 자리까지."""
    return round(read.key, 3) if isinstance(read.key, float) else read.key  # type: ignore[arg-type]


def _notation_note(rule_id: str, reads: list[tuple[ExtractedDocument, _Read, IssueCell]]) -> Issue | None:
    """값은 같고 표기만 다를 때 '참고' 하나. 수량은 단위 표기, 번호는 구분 기호 차이."""
    first = next((t for t in reads if t[1].notation), None)
    if first is None:
        return None
    other = next(
        (
            t
            for t in reads
            if t[1].notation
            and t[1].notation != first[1].notation
            and (rule_id != "X-QTY-01" or normalize_unit(t[1].notation) == normalize_unit(first[1].notation))
        ),
        None,
    )
    if other is None:
        return None

    def shown(read: _Read) -> str:
        return f"{read.shown} {read.notation}" if rule_id == "X-QTY-01" else read.shown

    text = _rule(rule_id, "참고")["template"].format(
        a_doc=DOC_TYPE_KO[first[0].doc_type], a_val=shown(first[1]),
        b_doc=DOC_TYPE_KO[other[0].doc_type], b_val=shown(other[1]),
    )
    return Issue(rule_id=rule_id, grade="참고", cells=[t[2] for t in reads], evidence=text)


def _check_rule(rule_id: str, docs: list[ExtractedDocument]) -> list[Issue]:
    base = _rule(rule_id, "불일치")
    doc_part, field = base["target"].split(":")
    if field not in _READERS:
        return []  # 아직 판정 코드가 없는 규칙(P1)
    reader, numeric = _READERS[field]
    tol = float(base["tolerance"])
    docs = [d for d in docs if d.doc_type in set(doc_part.split("|"))]
    if len(docs) < 2:
        return []  # 비교할 상대가 없음

    issues: list[Issue] = []
    readable: list[tuple[ExtractedDocument, _Read, IssueCell]] = []
    for doc in docs:
        read = reader(doc)
        cell = IssueCell(doc=doc.doc_type, field=read.field, raw=read.raw)
        if read.key is None:
            text = _rule(rule_id, "확인 필요")["template"].format(doc=DOC_TYPE_KO[doc.doc_type], reason=read.reason)
            issues.append(Issue(rule_id=rule_id, grade="확인 필요", cells=[cell], evidence=text))
        else:
            readable.append((doc, read, cell))
    if len(readable) < 2:
        return issues

    keys = [r.key for _, r, _ in readable]
    if numeric:
        spread = max(keys) - min(keys)  # type: ignore[type-var,operator]
        same = spread <= _EPS
    else:
        same = len(set(keys)) == 1
    if same:  # 값은 일치. 표기 차이만 있으면 '참고'
        note = _notation_note(rule_id, readable)
        return [*issues, note] if note else issues

    grade: Grade = "참고" if numeric and spread <= tol + _EPS else "불일치"

    # 다수결: 셋 이상이고 한 서류만 다르면 그 서류를 짚는다
    suspect = None
    counts = Counter(_ckey(r) for _, r, _ in readable)
    major_key, major_count = counts.most_common(1)[0]
    if len(readable) >= 3 and major_count == len(readable) - 1:
        odd_doc, odd_read, _ = next(t for t in readable if _ckey(t[1]) != major_key)
        suspect = odd_doc.doc_type
        a_doc, a_val = DOC_TYPE_KO[odd_doc.doc_type], odd_read.shown
        majors = [t for t in readable if _ckey(t[1]) == major_key]
        b_doc = "·".join(DOC_TYPE_KO[d.doc_type] for d, _, _ in majors)
        b_val = majors[0][1].shown
    else:
        first_doc, first_read, _ = readable[0]
        other_doc, other_read, _ = next(t for t in readable[1:] if _ckey(t[1]) != _ckey(first_read))
        a_doc, a_val = DOC_TYPE_KO[first_doc.doc_type], first_read.shown
        b_doc, b_val = DOC_TYPE_KO[other_doc.doc_type], other_read.shown

    text = _rule(rule_id, grade)["template"].format(
        a_doc=a_doc, a_val=a_val, b_doc=b_doc, b_val=b_val, tol=_fmt(tol)
    )
    cells = [c for _, _, c in readable]
    issues.append(Issue(rule_id=rule_id, grade=grade, cells=cells, suspect=suspect, evidence=text))
    return issues


def cross_check(docs: list[ExtractedDocument]) -> list[Issue]:
    """읽은 서류끼리 대조해 문제 목록을 돌려준다.

    언제: 서류를 모두 읽은 뒤, 그리고 다시 읽은 뒤마다.
    받는 것: read_document 결과 목록 (약속 1).
    반환: Issue 목록. 문제가 없으면 빈 목록. 못 읽은 값은 일치로 세지 않고 '확인 필요'로 낸다.
    """
    print(f"[tool] cross_check docs={[d.doc_type for d in docs]}")
    issues: list[Issue] = []
    for rule_id in _rule_ids():
        issues += _check_rule(rule_id, docs)
    return issues
