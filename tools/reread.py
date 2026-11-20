"""reread_field. 담당: 판독. 규칙: .kiro/steering/agent-design.md 4번, 형식: docs/schema.md

작업: e2e-plan.md B8 (P1). cross_check가 불일치로 짚은 칸 하나를 첫 판독과 다른 방법으로 다시 확인한다.
방법 순서 (쓸 수 있는 첫 방법):
  1. pdf_text: 텍스트 PDF의 글자를 코드로 뽑아, 판독한 raw가 문서에 그대로 있는지 본다. 모델 호출 없음 (pypdf, #111)
  2. textract: 저장해 둔 Textract 글자(OcrResult)에서 같은 방식으로 찾는다 (스캔본·사진, B4)
  3. model_reread: 그 칸 하나만 묻는 질문으로 모델에게 두 번 묻는다. 리포트에 model_reread로 남아 근거가 약함을 구분한다
결과: 두 번째 근거가 첫 판독과 같으면 불일치 확정, 다르면 '확인 필요(읽기 오류 의심)' (apply_rereads).
"""

import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import PurePath

from tools import extract
from tools.extract import ModelReader, _ask_twice, _unit_after_number, content_blocks, parse_number, system_prompt
from tools.models import DOC_TYPE_KO, CheckedBy, ExtractedDocument, Issue, OcrResult, RereadResult

# PDF 바이트 → 글자층 글자. 없거나 스캔본이면 ''. 테스트에서는 가짜로 바꾼다.
PdfText = Callable[[bytes], str]

_PATH = re.compile(r"^(?:items\[(\d+|\*)\]\.)?([a-z_]+)$")
_STRENGTH: dict[CheckedBy, int] = {"pdf_text": 3, "textract": 2, "model_reread": 1, "none": 0}


def _pypdf_text(data: bytes) -> str:
    """pypdf로 글자층을 뽑는다. pypdf가 없거나(#111 전) 읽지 못하면 ''."""
    try:
        import io

        import pypdf
    except ImportError:
        print("[reread] pypdf 없음: pdf_text를 건너뜀")
        return ""
    try:
        return "".join(page.extract_text() or "" for page in pypdf.PdfReader(io.BytesIO(data)).pages)
    except Exception as exc:  # 깨진 PDF 등
        print(f"[reread] PDF 글자 뽑기 실패: {type(exc).__name__}: {exc}")
        return ""


def field_raw(doc, field: str) -> str | None:
    """칸 경로의 raw. ExtractedDocument·RawDocument 둘 다 받는다.

    예: 'total_gross_kg', 'doc_no', 'items[0].gross_kg', 'items[*].gross_kg'(행 raw를 ' + '로 이음, cross_check와 같은 모양).
    칸이 없거나 못 읽었으면 None.
    """
    match = _PATH.match(field)
    if not match:
        raise ValueError(f"모르는 칸 경로입니다: {field}")
    index, name = match.groups()
    if index is None:
        cell = getattr(doc, name, None)
        return cell.raw if cell is not None else None
    items = doc.items
    if index == "*":
        raws = [field_raw(item, name) for item in items]
        return None if not raws or any(r is None for r in raws) else " + ".join(raws)
    i = int(index)
    if i >= len(items):
        return None
    cell = getattr(items[i], name, None)
    return cell.raw if cell is not None else None


def _squash(text: str) -> str:
    """띄어쓰기·줄바꿈을 지우고 대문자로. PDF 글자층은 칸 사이가 줄바꿈·공백으로 갈라져 나온다."""
    return "".join(text.split()).upper()


_NUMBER_TOKEN = re.compile(r"\d[\d,]*(?:\.\d+)?")


def find_in_text(raw: str, text: str) -> str | None:
    """판독한 raw가 문서 글자에 그대로 있는지 본다. 있으면 찾은 글자, 없으면 None.

    raw 전체가 있으면 raw. 없으면 raw 안의 숫자(적힌 그대로, 예 '6,520.00')가 있으면 그 숫자.
    행을 더한 raw('a + b')는 조각이 모두 있어야 한다.
    """
    hay = _squash(text)
    if not hay:
        return None
    parts = [p for p in raw.split(" + ")] if " + " in raw else [raw]
    found = []
    for part in parts:
        if _squash(part) and _squash(part) in hay:
            found.append(part)
            continue
        numbers = _NUMBER_TOKEN.findall(part)
        if numbers and all(n in hay for n in numbers):
            found.append(" ".join(numbers))
            continue
        return None
    return " + ".join(found)


def _field_prompt(doc: ExtractedDocument, field: str) -> str:
    """칸 하나만 묻는 지시. 읽기 지시문 뒤에 붙인다."""
    return (
        system_prompt(doc.doc_type)
        + f"\n- 이번에는 {field} 칸 하나만 옮긴다. 나머지 칸은 모두 null로 두고, 품목 행은 이 칸을 옮기는 데 필요할 때만 쓴다."
    )


_NUMERIC = ("gross_kg", "net_kg", "qty")


def _text_core(raw: str) -> str:
    """'Invoice No.: QDT/26/0289' → 'QDT/26/0289'. 모델이 칸 이름까지 옮긴 경우를 떼고 비교한다."""
    return _squash(raw.rsplit(":", 1)[-1])


def same_value(field: str, a: str | None, b: str | None) -> bool:
    """두 판독이 같은 값인지. 숫자 칸은 숫자(적힌 그대로)와 단위, 글자 칸은 앞 꼬리표를 뗀 글자로 본다.

    예: 'Total Gross Weight: 241.40 kg'과 '241.40 kg'은 같다. '6,520.00 KGS'와 '6,250.00 KGS'는 다르다.
    """
    if a is None or b is None:
        return False
    if field.endswith(_NUMERIC):
        parts_a, parts_b = a.split(" + "), b.split(" + ")
        if len(parts_a) != len(parts_b):
            return False
        for x, y in zip(parts_a, parts_b):
            if parse_number(x) is None or parse_number(x) != parse_number(y):
                return False
            ux, uy = _unit_after_number(x), _unit_after_number(y)
            if ux and uy and ux.rstrip("S") != uy.rstrip("S"):  # KG·KGS는 같고 KG·LBS는 다르다
                return False
        return True
    return _text_core(a) == _text_core(b)


def reread_field(
    doc: ExtractedDocument,
    field: str,
    data: bytes,
    *,
    ocr: OcrResult | None = None,
    reader: ModelReader | None = None,
    pdf_text: PdfText | None = None,
) -> RereadResult:
    """불일치에 걸린 칸 하나를 첫 판독과 다른 방법으로 다시 확인한다.

    언제: cross_check가 불일치를 낸 칸마다. 서류 전체를 다시 읽지 않는다.
    받는 것: doc(첫 판독 결과), field(칸 경로, 예 'items[0].gross_kg'), data(원본 파일),
             ocr(저장해 둔 Textract 결과, 사진·스캔본일 때), reader(테스트용 가짜 모델), pdf_text(테스트용 가짜 PDF 글자 뽑기).
    반환: RereadResult. 방법 순서: 텍스트 PDF면 pdf_text → OCR이 있으면 textract → 둘 다 없으면 model_reread.
    실패: 모델 호출이 실패하면 ReadError (부른 쪽이 단계 기록에 실패로 남기고 불일치는 그대로 둔다).
    """
    print(f"[tool] reread_field doc={doc.doc_type} field={field}")
    first = field_raw(doc, field)
    if first is None:  # 첫 판독에서 못 읽은 칸은 대조가 '확인 필요'로 낸다. 다시 확인할 raw가 없다
        return RereadResult(doc=doc.doc_type, field=field, first_raw=None, second_raw=None, checked_by="none", same=False)

    # 1. 텍스트 PDF
    if PurePath(doc.file).suffix.lower() == ".pdf":
        text = (pdf_text or _pypdf_text)(data)
        if text.strip():
            found = find_in_text(first, text)
            return RereadResult(
                doc=doc.doc_type, field=field, first_raw=first, second_raw=found, checked_by="pdf_text", same=found is not None
            )
    # 2. 저장해 둔 Textract 글자
    if ocr is not None and ocr.lines:
        found = find_in_text(first, "\n".join(line.text for line in ocr.lines))
        return RereadResult(
            doc=doc.doc_type, field=field, first_raw=first, second_raw=found, checked_by="textract", same=found is not None
        )
    # 3. 칸 하나만 모델에게 두 번
    reader = reader or extract._strands_reader  # 부를 때 찾는다 (테스트가 extract._strands_reader를 바꿔 끼움)
    blocks, prompt = content_blocks(doc.file, data), _field_prompt(doc, field)
    with ThreadPoolExecutor(max_workers=2) as pool:  # 두 번 묻기를 동시에 (서로의 답을 보지 않는다)
        futures = [pool.submit(_ask_twice, lambda: reader(blocks, prompt)) for _ in range(2)]
        answers = [field_raw(f.result(), field) for f in futures]
    same = same_value(field, answers[0], first) and same_value(field, answers[1], first)
    return RereadResult(
        doc=doc.doc_type, field=field, first_raw=first, second_raw=answers[0], checked_by="model_reread", same=same
    )


def _downgraded(issue: Issue, differ: list) -> Issue:
    """두 근거가 다른 불일치를 '확인 필요(읽기 오류 의심)'로 내린다. 근거 문장은 코드가 만든다."""
    parts = [
        f"{DOC_TYPE_KO[r.doc]} {r.field} 첫 판독 {r.first_raw} / 다시 확인 {r.second_raw if r.second_raw is not None else '찾지 못함'}"
        for r in differ
    ]
    evidence = f"{issue.evidence} 다시 확인한 값이 첫 판독과 달라 읽기 오류일 수 있습니다 ({'; '.join(parts)})."
    return issue.model_copy(update={"grade": "확인 필요", "evidence": evidence, "checked_by": _weakest(differ)})


def _weakest(rereads: list) -> CheckedBy:
    """근거의 세기가 가장 약한 방법. model_reread로만 확인한 칸이 있으면 그렇게 표시한다."""
    return min((r.checked_by for r in rereads), key=lambda m: _STRENGTH[m])


def apply_rereads(issues: list[Issue], rereads: list[RereadResult]) -> list[Issue]:
    """다시 확인 결과를 issues에 반영한다.

    언제: reread_field를 모두 부른 뒤 (부를 때마다 다시 불러도 결과가 같다).
    받는 것: cross_check가 낸 issues, reread_field 결과 목록.
    반환: 새 issues. 불일치의 칸이 모두 다시 확인됐을 때만 바꾼다.
      - 두 근거가 모두 같으면 불일치 그대로, checked_by에 가장 약한 방법
      - 하나라도 다르면 '확인 필요(읽기 오류 의심)'로 내리고 근거 문장에 두 값을 붙인다
      - 다시 확인을 못 한 칸(checked_by none)이 있으면 그대로 둔다 (일치로 세지 않는다)
    불일치가 아닌 문제는 그대로 둔다.
    """
    by_cell = {(r.doc, r.field): r for r in rereads}
    out: list[Issue] = []
    for issue in issues:
        found = [by_cell.get((c.doc, c.field)) for c in issue.cells]
        if issue.grade != "불일치" or not found or any(r is None or r.checked_by == "none" for r in found):
            out.append(issue)
            continue
        differ = [r for r in found if not r.same]
        out.append(_downgraded(issue, differ) if differ else issue.model_copy(update={"checked_by": _weakest(found)}))
    return out

