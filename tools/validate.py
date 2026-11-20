"""서류 교차 검증. 담당: 검증. 규칙: .kiro/steering/agent-design.md 3·5번, 형식: docs/schema.md 약속 2

P0 규칙 셋(X-INV-01 송장 번호, X-QTY-01 총수량, X-WT-01 총중량)은 서류 전체 값만 비교한다.
P1 규칙(FB06 #163)은 X-PKG-01 총포장수(서류끼리), X-CNTR-01 컨테이너 번호 체크 디지트와 X-SUM-01 줄 금액 합(서류 한 장 안)이다.
규칙 문장틀과 허용 오차는 tools/rules/rules.csv, 비교 전에 맞추는 표기(단위 별칭, 번호·품명 정리)는
tools/rules/units.csv, tools/rules/text_rules.csv 에 있다.
"""

import csv
import html
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from tools.models import DOC_TYPE_KO, Cell, CheckedBy, ExtractedDocument, Grade, Issue, IssueCell, NoticeDocument

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
    absent: bool = False  # 그 서류에 이 칸이 없다. 비교에서 빼고 '확인 필요'도 내지 않는다


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


def _is_absent(cell: Cell | None) -> bool:
    """그 서류에 이 칸이 없는가. 칸 자체가 없거나, 아무것도 못 읽었고 이유가 '칸 없음'(또는 이유 없음)일 때."""
    return cell is None or (cell.value is None and cell.raw is None and cell.unreadable in (None, "칸 없음"))


def _read_total_packages(doc: ExtractedDocument) -> _Read:
    """총포장수(Total Packages, No. of Pkgs). 품목 수량 합계(total_qty)와 다르다.

    포장명세서는 총포장수를 안 찍는 양식도 있어서, 칸이 없으면 비교에서 뺀다(absent). 행을 더해 만들지 않는다.
    """
    cell = doc.total_packages
    if _is_absent(cell):
        return _Read(None, "total_packages", None, "칸 없음", absent=True)
    if isinstance(cell.value, (int, float)):
        return _Read(float(cell.value), "total_packages", cell.raw, shown=_fmt(float(cell.value)))
    if cell.unreadable:
        return _Read(None, "total_packages", cell.raw, cell.unreadable)
    return _Read(None, "total_packages", cell.raw, "숫자로 풀 수 없음")


# 칸 이름(rules.csv target) → (읽는 함수, 숫자인지)
_READERS: dict[str, tuple[Callable[[ExtractedDocument], _Read], bool]] = {
    "total_gross_kg": (_read_total_gross, True),
    "total_qty": (_read_total_qty, True),
    "invoice_no": (_read_invoice_no, False),
    "total_packages": (_read_total_packages, True),
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
        if read.absent:
            continue
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


# ---------------------------------------------------------------------------
# 서류 한 장 안에서 계산하는 규칙 (agent-design.md 3번 1층)
# ---------------------------------------------------------------------------
_CONTAINER_NO = re.compile(r"[A-Z]{3}[UJZ]\s?\d{6}\s?\d")  # 소유자 코드 3자 + 장비 구분(U·J·Z) + 번호 6자 + 체크 디지트 1자


@cache
def _letter_values() -> dict[str, int]:
    """ISO 6346 글자값. A=10부터 세되 11의 배수(11, 22, 33)는 건너뛴다. 예: K=21, L=23."""
    values: dict[str, int] = {}
    n = 10
    for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        if n % 11 == 0:
            n += 1
        values[ch] = n
        n += 1
    return values


def container_check_digit(first10: str) -> int:
    """컨테이너 번호 앞 10자(영문 4 + 숫자 6)로 ISO 6346 체크 디지트를 계산한다. 예: 'CSQU305438' → 3."""
    letters = _letter_values()
    total = sum((letters[ch] if ch.isalpha() else int(ch)) * 2**i for i, ch in enumerate(first10))
    return total % 11 % 10


def _check_container(docs: list[ExtractedDocument]) -> list[Issue]:
    """X-CNTR-01: 선하증권 컨테이너 번호의 체크 디지트가 맞는지. 번호가 여러 개면 하나씩 본다."""
    issues: list[Issue] = []
    for doc in docs:
        if doc.doc_type != "bill_of_lading" or _is_absent(doc.container_no):
            continue
        cell = doc.container_no
        assert cell is not None  # _is_absent가 None을 걸러 냈다
        ko = DOC_TYPE_KO[doc.doc_type]
        issue_cell = IssueCell(doc=doc.doc_type, field="container_no", raw=cell.raw)
        text = cell.value if isinstance(cell.value, str) else cell.raw
        if not text or not text.strip():
            reason = cell.unreadable or "컨테이너 번호로 읽을 글자가 없음"
            msg = _rule("X-CNTR-01", "확인 필요")["template"].format(doc=ko, reason=reason)
            issues.append(Issue(rule_id="X-CNTR-01", grade="확인 필요", cells=[issue_cell], evidence=msg))
            continue
        numbers = ["".join(m.split()) for m in _CONTAINER_NO.findall(re.sub(r"[-.]", "", text.upper()))]
        if not numbers:
            msg = _rule("X-CNTR-01", "확인 필요")["template"].format(doc=ko, reason="컨테이너 번호 형식이 아님")
            issues.append(Issue(rule_id="X-CNTR-01", grade="확인 필요", cells=[issue_cell], evidence=msg))
        for number in numbers:
            expected = container_check_digit(number[:10])
            if int(number[10]) != expected:
                msg = _rule("X-CNTR-01", "불일치")["template"].format(doc=ko, val=number, expected=expected)
                issues.append(Issue(rule_id="X-CNTR-01", grade="불일치", cells=[issue_cell], evidence=msg))
    return issues


def _line_amount_problem(items_amounts: list[Cell | None]) -> str | None:
    """줄 금액을 하나라도 숫자로 못 구하면 그 이유(예: '2행 금액 흐림'). 모두 구했으면 None."""
    if not items_amounts:
        return "줄 금액 칸 없음"
    for n, cell in enumerate(items_amounts, start=1):
        if cell is None:
            return f"{n}행 금액 칸 없음"
        if not isinstance(cell.value, (int, float)):
            return f"{n}행 금액 {cell.unreadable or '숫자로 풀 수 없음'}"
    return None


def _check_amount_sum(docs: list[ExtractedDocument]) -> list[Issue]:
    """X-SUM-01: 상업송장 줄 금액의 합이 총금액과 같은지. 합은 코드가 더한다."""
    base = _rule("X-SUM-01", "불일치")
    tol = float(base["tolerance"])
    issues: list[Issue] = []
    for doc in docs:
        if doc.doc_type != "commercial_invoice" or _is_absent(doc.total_amount):
            continue  # 총금액이 안 찍힌 송장은 비교할 합계가 없다
        total = doc.total_amount
        assert total is not None
        ko = DOC_TYPE_KO[doc.doc_type]
        total_cell = IssueCell(doc=doc.doc_type, field="total_amount", raw=total.raw)
        amounts = [item.amount for item in doc.items]
        problem = (
            f"총금액 {total.unreadable or '숫자로 풀 수 없음'}"
            if not isinstance(total.value, (int, float))
            else _line_amount_problem(amounts)
        )
        if problem:
            msg = _rule("X-SUM-01", "확인 필요")["template"].format(doc=ko, reason=problem)
            issues.append(Issue(rule_id="X-SUM-01", grade="확인 필요", cells=[total_cell], evidence=msg))
            continue
        line_sum = round(sum(float(c.value) for c in amounts if c is not None and isinstance(c.value, (int, float))), 2)
        diff = abs(line_sum - float(total.value))  # type: ignore[arg-type]
        if diff <= _EPS:
            continue
        grade: Grade = "참고" if diff <= tol + _EPS else "불일치"
        msg = _rule("X-SUM-01", grade)["template"].format(
            a_doc=ko, a_val=_fmt(line_sum), b_val=_fmt(float(total.value)), tol=_fmt(tol)  # type: ignore[arg-type]
        )
        cells = [total_cell] + [
            IssueCell(doc=doc.doc_type, field=f"items[{n}].amount", raw=c.raw) for n, c in enumerate(amounts) if c is not None
        ]
        issues.append(Issue(rule_id="X-SUM-01", grade=grade, cells=cells, evidence=msg))
    return issues


# 서류 한 장 안에서 판정하는 규칙(rules.csv의 rule_id → 판정 함수). 나머지는 서류끼리 비교(_check_rule)
_SINGLE_DOC_RULES: dict[str, Callable[[list[ExtractedDocument]], list[Issue]]] = {
    "X-CNTR-01": _check_container,
    "X-SUM-01": _check_amount_sum,
}


def cross_check(docs: list[ExtractedDocument]) -> list[Issue]:
    """읽은 서류끼리 대조해 문제 목록을 돌려준다.

    언제: 서류를 모두 읽은 뒤, 그리고 다시 읽은 뒤마다.
    받는 것: read_document 결과 목록 (약속 1).
    반환: Issue 목록. 문제가 없으면 빈 목록. 못 읽은 값은 일치로 세지 않고 '확인 필요'로 낸다.
    """
    print(f"[tool] cross_check docs={[d.doc_type for d in docs]}")
    issues: list[Issue] = []
    for rule_id in _rule_ids():
        single = _SINGLE_DOC_RULES.get(rule_id)
        issues += single(docs) if single else _check_rule(rule_id, docs)
    return issues


# ---------------------------------------------------------------------------
# 불일치 통지 문서 (C7 #158). 근거는 코드가 문장틀로 만들고 모델은 쓰지 않는다 (agent-design.md 5번)
# ---------------------------------------------------------------------------
_CHECKED_BY_KO: dict[CheckedBy, str] = {
    "pdf_text": "PDF 글자층에서 확인",
    "textract": "Textract OCR로 확인",
    "model_reread": "모델이 다시 읽어 확인 (근거가 약함)",
    "none": "아직 다시 확인하지 않음",
}
_NOTICE_MARK = "자동 생성 문서입니다. 사람이 검토한 뒤 보냅니다."
_NOTICE_REQUEST: dict[str, str] = {
    "불일치": "정정한 서류를 다시 보내 주세요.",
    "확인 필요": "원본 값을 확인해 주세요.",
}
_MAX_TEXT = 300  # 서류에서 온 글자 한 덩이의 길이 상한
_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+!|<>~&])")


def _plain(text: str | None) -> str:
    """서류에서 온 글자를 한 줄로 정리한다. 제어 문자를 빼고 공백을 하나로 맞추고 길이를 자른다."""
    kept = "".join(ch if ch.isprintable() else " " for ch in (text or ""))
    one_line = " ".join(kept.split())
    return one_line if len(one_line) <= _MAX_TEXT else one_line[:_MAX_TEXT] + "…"


def _md(text: str | None) -> str:
    """마크다운에 데이터로 넣는다. 서식 글자를 이스케이프해 링크·제목·표·태그가 만들어지지 않게 한다."""
    return _MD_SPECIAL.sub(r"\\\1", _plain(text))


def _doc_number(doc: ExtractedDocument) -> str | None:
    """서류 번호(doc_no)를 글자로. 값이 있으면 값, 없으면 적힌 그대로. 비었으면 None."""
    cell = doc.doc_no
    if cell is None:
        return None
    text = cell.value if isinstance(cell.value, str) else cell.raw
    return _plain(text) or None


def _file_name(path: str) -> str:
    return _plain(re.split(r"[\\/]", path)[-1])


def _notice_subject(job_id: str, docs: list[ExtractedDocument]) -> str:
    """제목. B/L 번호와 송장 번호가 있으면 넣고, 둘 다 없으면 작업 ID."""
    numbers: dict[str, str | None] = {}
    for doc in docs:
        if doc.doc_type in ("bill_of_lading", "commercial_invoice") and doc.doc_type not in numbers:
            numbers[doc.doc_type] = _doc_number(doc)
    parts = []
    if numbers.get("bill_of_lading"):
        parts.append(f"B/L {numbers['bill_of_lading']}")
    if numbers.get("commercial_invoice"):
        parts.append(f"송장 {numbers['commercial_invoice']}")
    return f"[불일치 확인 요청] {' / '.join(parts) if parts else _plain(job_id)}"


def notice_document(job_id: str, docs: list[ExtractedDocument], issues: list[Issue]) -> NoticeDocument:
    """불일치 내용을 담아 관리자(화주·수출자 담당)에게 보낼 문서를 만든다. 모델 호출 없음.

    언제: cross_check와 다시 확인이 끝난 뒤, 문서를 내려받거나 보낼 때.
    받는 것: job_id(작업 ID), docs(읽은 서류), issues(cross_check 결과).
    반환: NoticeDocument(제목, 마크다운, HTML, 불일치·확인 필요 건수). 불일치와 확인 필요만 담고 참고는 뺀다.
    둘 다 없으면 본문에 '불일치 없음' 한 줄만 쓴다. 문장은 코드가 규칙의 근거 문장(evidence)을 그대로 쓰고,
    서류에서 온 글자는 마크다운·HTML 모두 데이터로만 넣는다(이스케이프). 맨 위에 '자동 생성 문서' 표시를 붙인다.
    """
    print(f"[tool] notice_document job_id={job_id} issues={len(issues)}")
    subject = _notice_subject(job_id, docs)
    groups = {grade: [i for i in issues if i.grade == grade] for grade in ("불일치", "확인 필요")}

    doc_lines = [
        (DOC_TYPE_KO.get(d.doc_type, d.doc_type), _file_name(d.file), _doc_number(d)) for d in docs
    ]

    def cell_text(cell: IssueCell, escape: Callable[[str], str]) -> str:
        """짚은 칸 한 줄. 서류에서 온 값(칸 경로·raw)만 escape를 거치고, 코드가 정한 문구는 그대로 쓴다."""
        head = f"{escape(DOC_TYPE_KO.get(cell.doc, cell.doc))} {escape(cell.field)}: "
        return head + (escape(cell.raw) if _plain(cell.raw) else "(읽지 못함)")

    # 마크다운
    md = [f"# {_md(subject)}", "", f"> {_NOTICE_MARK}", "", f"작업 ID: {_md(job_id)}", "", "## 대상 서류", ""]
    md += [
        f"- {ko}: 파일 {_md(name)}" + (f", 서류 번호 {_md(no)}" if no else "") for ko, name, no in doc_lines
    ] or ["- (읽은 서류 없음)"]
    if not groups["불일치"]:
        md += ["", "## 불일치", "", "불일치 없음"]
    for grade, items in groups.items():
        if not items:
            continue
        md += ["", f"## {grade} ({len(items)}건)", "", _NOTICE_REQUEST[grade], ""]
        for issue in items:
            md += [f"- 규칙 {_md(issue.rule_id)}: {_md(issue.evidence)}"]
            md += [f"  - 짚은 칸: {cell_text(c, _md)}" for c in issue.cells]
            md += [f"  - 확인 방법: {_CHECKED_BY_KO[issue.checked_by]}"]

    # HTML
    esc = html.escape
    page = [
        "<!doctype html>", '<html lang="ko">', '<head><meta charset="utf-8">', f"<title>{esc(subject)}</title></head>", "<body>",
        f"<h1>{esc(subject)}</h1>", f"<p><strong>{esc(_NOTICE_MARK)}</strong></p>", f"<p>작업 ID: {esc(_plain(job_id))}</p>",
        "<h2>대상 서류</h2>", "<ul>",
    ]
    page += [
        f"<li>{esc(ko)}: 파일 {esc(name)}" + (f", 서류 번호 {esc(no)}" if no else "") + "</li>" for ko, name, no in doc_lines
    ] or ["<li>(읽은 서류 없음)</li>"]
    page.append("</ul>")
    if not groups["불일치"]:
        page += ["<h2>불일치</h2>", "<p>불일치 없음</p>"]
    for grade, items in groups.items():
        if not items:
            continue
        page += [f"<h2>{esc(grade)} ({len(items)}건)</h2>", f"<p>{esc(_NOTICE_REQUEST[grade])}</p>", "<ul>"]
        for issue in items:
            page += [f"<li>규칙 {esc(_plain(issue.rule_id))}: {esc(_plain(issue.evidence))}", "<ul>"]
            page += [f"<li>짚은 칸: {cell_text(c, lambda s: esc(_plain(s)))}</li>" for c in issue.cells]
            page += [f"<li>확인 방법: {esc(_CHECKED_BY_KO[issue.checked_by])}</li>", "</ul></li>"]
        page.append("</ul>")
    page += ["</body>", "</html>"]

    return NoticeDocument(
        job_id=_plain(job_id), subject=subject, markdown="\n".join(md) + "\n", html="\n".join(page) + "\n",
        mismatch_count=len(groups["불일치"]), check_count=len(groups["확인 필요"]),
    )
