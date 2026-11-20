"""채점. 담당: 검증(코드), 정답지 CSV는 판독. 규칙: .kiro/steering/agent-design.md 11번, 형식: docs/schema.md 약속 3
작업: e2e-plan.md H1·H2. 저장된 판독(판독 캐시)으로 모델 호출 없이 다시 채점할 수 있어야 한다.
결과는 건수로 쓴다. 예: "심은 오류 20건 중 17건 탐지, 정상 10세트 중 오탐 0건".

이 파일은 AWS와 Bedrock을 부르지 않는다. 읽은 결과(ExtractedDocument)와 cross_check 결과(Issue)를 받아 세기만 한다.
"""

import argparse
import contextlib
import csv
import io
import re
from collections import defaultdict
from pathlib import Path

from tools.models import Cell, ExtractedDocument, ExtractedItem, Issue

EVAL_DIR = Path(__file__).parent
_FIELD_ALIAS = {"doc_no": "invoice_no"}  # 약속 1의 doc_no = 정답지의 invoice_no
_ITEM_TO_TOTAL = {"gross_kg": "total_gross_kg", "qty": "total_qty"}  # 행 단위로 짚으면 서류 전체 값으로 묶는다
# 읽기 채점 대상: P0 대조에 쓰는 서류 전체 값. 정답지 칸 이름 → ExtractedDocument 필드
_READ_FIELDS = {"invoice_no": "doc_no", "total_qty": "total_qty", "total_gross_kg": "total_gross_kg"}
_P0_DOCS = ("commercial_invoice", "packing_list")  # P0에서 읽는 서류. B/L·원산지증명서는 P1


def load_answers(path: Path = EVAL_DIR / "answers.csv") -> list[dict[str, str]]:
    """정답지(약속 3)를 읽는다."""
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def load_formats(sets_csv: Path = EVAL_DIR / "sets.csv") -> dict[tuple[str, str], str]:
    """sets.csv의 docs 칸에서 (세트, 서류 종류) → 파일 형식(pdf · png · scan)을 읽는다.

    docs 칸 예: 'doc_a=packing_list;doc_b=commercial_invoice;fmt_a=pdf;fmt_b=scan;style=1'
    """
    formats: dict[tuple[str, str], str] = {}
    with sets_csv.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            pairs = dict(p.split("=", 1) for p in row["docs"].split(";") if "=" in p)
            for key, doc_type in pairs.items():
                if key.startswith("doc_") and f"fmt_{key[4:]}" in pairs:
                    formats[(row["set_id"], doc_type)] = pairs[f"fmt_{key[4:]}"]
    return formats


def _answer_field(field: str) -> str:
    """Issue 칸 경로를 정답지의 서류 전체 값 이름으로 맞춘다.

    예: 'doc_no' → 'invoice_no', 'items[0].gross_kg' → 'total_gross_kg'. 그 밖의 칸은 그대로.
    """
    field = _FIELD_ALIAS.get(field, field)
    match = re.fullmatch(r"items\[(?:\d+|\*)\]\.(\w+)", field)
    if match and match.group(1) in _ITEM_TO_TOTAL:
        return _ITEM_TO_TOTAL[match.group(1)]
    return field


def score_detection(
    answers: list[dict[str, str]],
    issues_by_set: dict[str, list[Issue]],
    split: str,
    *,
    phases: tuple[str, ...] = ("P0",),
    fmt_by_doc: dict[tuple[str, str], str] | None = None,
) -> dict:
    """판정 채점: 탐지와 오탐.

    언제: cross_check 결과를 정답지와 맞춰 볼 때. 모델 호출은 없다.
    받는 것: 정답지 줄, 세트 ID → 그 세트의 issues, split(dev · test), phases(정답으로 볼 단계. 기본 P0),
        fmt_by_doc(load_formats 결과. 있으면 형식별 탐지도 낸다).
    반환: {"planted", "detected", "flagged", "misses", "normal_sets", "false_positive_sets",
        "check_needed_sets", "wrong_cell_sets", "not_run_sets", "by_error_type", "by_format", "by_variant", ...}.
    탐지(detected)는 심은 칸(doc, field)을 '불일치'로 짚었을 때만 센다. 엉뚱한 칸을 짚어 세트가 걸린 것은 탐지가 아니다.
    flagged는 '불일치'나 '확인 필요'로 그 칸을 짚은 수다(사람에게 넘어가는 것까지 센 값).
    오탐은 정상 세트(심은 오류가 없거나 phases 밖의 오류만 있는 세트)에서 '불일치'가 나온 세트 수다. '참고'는 세지 않는다.
    issues_by_set에 없는 세트는 채점하지 않고 not_run_sets에 센다.
    """
    rows = [a for a in answers if a["split"] == split]
    set_ids = sorted({a["set_id"] for a in rows})
    planted_rows: dict[str, list[dict[str, str]]] = defaultdict(list)
    variant_of: dict[str, str] = {}
    for a in rows:
        if a["error_type"] != "none" and a["phase"] in phases:
            planted_rows[a["set_id"]].append(a)
        elif a["error_type"] == "none" and a.get("variant"):
            variant_of[a["set_id"]] = a["variant"]

    result = {
        "split": split, "phases": list(phases), "planted": 0, "detected": 0, "flagged": 0, "misses": [],
        "normal_sets": 0, "false_positive_sets": 0, "false_positives": [], "check_needed_sets": 0,
        "wrong_cell_sets": 0, "extra_hard_issues": 0, "not_run_sets": 0,
    }
    by_type: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # [탐지, 심은 수]
    by_format: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    by_variant: dict[str, dict[str, int]] = defaultdict(lambda: {"sets": 0, "false_positive_sets": 0})

    for set_id in set_ids:
        if set_id not in issues_by_set:
            result["not_run_sets"] += 1
            continue
        issues = issues_by_set[set_id]
        hard = [i for i in issues if i.grade == "불일치"]
        check = [i for i in issues if i.grade == "확인 필요"]
        hard_cells = {(c.doc, _answer_field(c.field)) for i in hard for c in i.cells}
        flag_cells = hard_cells | {(c.doc, _answer_field(c.field)) for i in check for c in i.cells}

        if set_id in planted_rows:
            planted_keys = {(a["doc"], a["field"]) for a in planted_rows[set_id]}
            hit_any = False
            for a in planted_rows[set_id]:
                key = (a["doc"], a["field"])
                fmt = (fmt_by_doc or {}).get((set_id, a["doc"]))
                result["planted"] += 1
                by_type[a["error_type"]][1] += 1
                if fmt:
                    by_format[fmt][1] += 1
                if key in hard_cells:
                    result["detected"] += 1
                    by_type[a["error_type"]][0] += 1
                    if fmt:
                        by_format[fmt][0] += 1
                    hit_any = True
                else:
                    result["misses"].append(
                        {"set_id": set_id, "doc": a["doc"], "field": a["field"], "error_type": a["error_type"]}
                    )
                if key in flag_cells:
                    result["flagged"] += 1
            if hard and not hit_any:
                result["wrong_cell_sets"] += 1  # 불일치는 냈지만 심은 칸이 아니다
            # 심은 칸을 하나도 포함하지 않는 불일치는 따로 센다
            result["extra_hard_issues"] += sum(
                1 for i in hard if not ({(c.doc, _answer_field(c.field)) for c in i.cells} & planted_keys)
            )
        else:
            result["normal_sets"] += 1
            variant = variant_of.get(set_id)
            if variant:
                by_variant[variant]["sets"] += 1
            if hard:
                result["false_positive_sets"] += 1
                result["false_positives"].append(
                    {"set_id": set_id, "rule_id": hard[0].rule_id, "evidence": hard[0].evidence, "variant": variant}
                )
                if variant:
                    by_variant[variant]["false_positive_sets"] += 1
            elif check:
                result["check_needed_sets"] += 1  # 불일치는 없고 '확인 필요'만 나옴

    result["by_error_type"] = {k: {"detected": v[0], "planted": v[1]} for k, v in sorted(by_type.items())}
    result["by_format"] = {k: {"detected": v[0], "planted": v[1]} for k, v in sorted(by_format.items())}
    result["by_variant"] = dict(sorted(by_variant.items()))
    return result


def _number(text: str) -> float | None:
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def score_fields(
    fields_csv: Path,
    docs_by_set: dict[str, list[ExtractedDocument]],
    *,
    doc_types: tuple[str, ...] = _P0_DOCS,
    fmt_by_doc: dict[tuple[str, str], str] | None = None,
) -> dict:
    """읽기 채점: eval/fields.csv로 칸별 판독 정답 수.

    언제: 저장된 판독(ExtractedDocument)을 정답 값과 맞춰 볼 때. 탐지가 낮을 때 읽기 문제인지 규칙 문제인지 가른다.
    받는 것: fields.csv 경로, 세트 ID → 읽은 서류 목록, doc_types(채점할 서류 종류. 기본은 P0의 상업송장·포장명세서), fmt_by_doc(load_formats 결과. 있으면 형식별로도 센다).
    반환: {"docs", "docs_correct", "cells", "cells_correct", "unread", "missing_docs", "by_field", "by_format", "wrong"}.
    '잘 읽었다'는 서류의 채점 칸(송장 번호 · 총수량 · 총중량)이 모두 정답과 같을 때다. 정답과 다르게 읽은 칸(wrong)과
    못 읽은 칸(unread)은 따로 센다. 송장 번호는 글자가 그대로 같아야 하고(구분 기호를 맞춰 주지 않는다), 숫자는 값이 같아야 한다.
    docs_by_set에 없는 세트는 채점하지 않는다.
    """
    cells: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)  # (세트, 서류) → [(칸, 정답)]
    with fields_csv.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if row["field"] in _READ_FIELDS and row["doc"] in doc_types and row["set_id"] in docs_by_set:
                cells[(row["set_id"], row["doc"])].append((row["field"], row["answer"]))

    result = {"docs": 0, "docs_correct": 0, "cells": 0, "cells_correct": 0, "unread": 0, "missing_docs": 0, "wrong": []}
    by_field: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # [맞음, 전체]
    by_format: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for (set_id, doc_type), expected in sorted(cells.items()):
        result["docs"] += 1
        doc = next((d for d in docs_by_set[set_id] if d.doc_type == doc_type), None)
        fmt = (fmt_by_doc or {}).get((set_id, doc_type))
        all_ok = True
        for field, answer in expected:
            result["cells"] += 1
            by_field[field][1] += 1
            cell: Cell | None = getattr(doc, _READ_FIELDS[field]) if doc else None
            value = cell.value if cell else None
            if doc is None:
                result["missing_docs"] += 1
                ok = False
            elif value is None:
                result["unread"] += 1
                ok = False
            elif isinstance(value, (int, float)):
                expected_number = _number(answer)
                ok = expected_number is not None and abs(float(value) - expected_number) <= 1e-6
            else:
                ok = str(value).strip() == answer.strip()
            if ok:
                result["cells_correct"] += 1
                by_field[field][0] += 1
            else:
                all_ok = False
                if doc is not None and value is not None:
                    result["wrong"].append(
                        {"set_id": set_id, "doc": doc_type, "field": field, "answer": answer, "read": value}
                    )
        if all_ok:
            result["docs_correct"] += 1
        if fmt:
            by_format[fmt][1] += 1
            by_format[fmt][0] += all_ok
    result["by_field"] = {k: {"correct": v[0], "total": v[1]} for k, v in sorted(by_field.items())}
    result["by_format"] = {k: {"correct": v[0], "total": v[1]} for k, v in sorted(by_format.items())}
    return result


def format_report(detection: dict, fields: dict | None = None) -> str:
    """채점 결과를 건수로 쓴 한국어 요약. 비율(%)은 쓰지 않는다. 정상 세트가 적으면 비율이 오해를 부른다."""
    lines = [
        f"[{detection['split']}] 심은 오류 {detection['planted']}건 중 {detection['detected']}건 탐지"
        f" (불일치로 짚음). 불일치·확인 필요로 짚은 것까지 {detection['flagged']}건",
        f"정상 세트 {detection['normal_sets']}세트 중 오탐 {detection['false_positive_sets']}세트"
        f" (확인 필요만 나온 세트 {detection['check_needed_sets']})",
    ]
    if detection["wrong_cell_sets"] or detection["extra_hard_issues"]:
        lines.append(
            f"엉뚱한 칸만 짚은 세트 {detection['wrong_cell_sets']}, 심은 칸이 아닌 불일치 {detection['extra_hard_issues']}건"
        )
    if detection["not_run_sets"]:
        lines.append(f"채점하지 않은 세트 {detection['not_run_sets']}세트 (결과 없음)")
    for name, group in (("오류 종류별", detection["by_error_type"]), ("형식별", detection["by_format"])):
        if group:
            lines.append(f"{name}: " + ", ".join(f"{k} {v['detected']}/{v['planted']}" for k, v in group.items()))
    if detection["by_variant"]:
        lines.append(
            "정상 변형별 오탐: "
            + ", ".join(f"{k} {v['false_positive_sets']}/{v['sets']}" for k, v in detection["by_variant"].items())
        )
    for miss in detection["misses"]:
        lines.append(f"놓침: {miss['set_id']} {miss['doc']}.{miss['field']} ({miss['error_type']})")
    if fields is not None:
        lines.append(
            f"읽기: 서류 {fields['docs']}장 중 {fields['docs_correct']}장 모든 칸 정답,"
            f" 칸 {fields['cells']}개 중 {fields['cells_correct']}개 정답"
            f" (못 읽음 {fields['unread']}, 서류 없음 {fields['missing_docs']})"
        )
        if fields["by_field"]:
            lines.append("칸별: " + ", ".join(f"{k} {v['correct']}/{v['total']}" for k, v in fields["by_field"].items()))
        if fields["by_format"]:
            lines.append("형식별(서류): " + ", ".join(f"{k} {v['correct']}/{v['total']}" for k, v in fields["by_format"].items()))
    return "\n".join(lines)


def oracle_docs(fields_csv: Path = EVAL_DIR / "fields.csv", split_prefix: str = "D") -> dict[str, list[ExtractedDocument]]:
    """정답 값(심은 오류 포함)을 그대로 읽은 것처럼 만든 가짜 읽기 결과. 모델 호출 없이 규칙만 시험할 때 쓴다.

    실제 판독 오류는 들어 있지 않으므로 이 점수는 규칙의 상한이다. 상업송장과 포장명세서만 만든다.
    """
    values: dict[tuple[str, str], dict[str, str]] = defaultdict(dict)
    with fields_csv.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if row["set_id"].startswith(split_prefix) and row["doc"] in ("commercial_invoice", "packing_list"):
                values[(row["set_id"], row["doc"])][row["field"]] = row["answer"]
    docs: dict[str, list[ExtractedDocument]] = defaultdict(list)
    for (set_id, doc_type), f in values.items():
        docs[set_id].append(
            ExtractedDocument(
                doc_type=doc_type,  # type: ignore[arg-type]
                file=f"oracle/{set_id}/{doc_type}",
                doc_no=Cell(raw=f.get("invoice_no"), value=f.get("invoice_no")) if f.get("invoice_no") else None,
                total_qty=Cell(raw=f["total_qty"], value=_number(f["total_qty"])) if f.get("total_qty") else None,
                total_gross_kg=(
                    Cell(raw=f["total_gross_kg"], value=_number(f["total_gross_kg"])) if f.get("total_gross_kg") else None
                ),
            )
        )
    return dict(docs)


# ---------------------------------------------------------------------------
# H2. HS 확정과 자동 처리율 (모델 호출 없음)
# ---------------------------------------------------------------------------
HS_MODES = ("none", "oracle", "trap")  # 모델 대신 쓰는 가짜: 없음 · 정답을 1순위로 · 헷갈리는 HS를 1순위로
MODEL_MODE = "bedrock"  # 진짜 Bedrock 모델(검색어 뽑기 + 후보 고르기). 돈과 시간이 들어서 --hs-model일 때만 돈다


class _MemoryHistory:
    """확정 이력. 평가는 비어 있는 상태로 시작한다 (agent-design.md 11번)."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], str] = {}

    def get(self, importer: str, item_key: str) -> str | None:
        return self.rows.get((importer, item_key))

    def put(self, importer: str, item_key: str, hs: str, job_id: str) -> None:
        self.rows[(importer, item_key)] = hs


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text or "")


def load_hs_inputs(split: str = "dev", eval_dir: Path = EVAL_DIR) -> dict:
    """HS 채점에 쓸 정답지 값을 모은다.
    반환: rows(품목 행, 세트 번호 · 줄 순서), co_hs((세트, 줄) → 원산지증명서에 찍힌 HS 숫자),
    inv_hs((세트, 줄) → 상업송장에 찍힌 HS. 함정 세트만 알 수 있다), normal(오류가 하나도 없는 세트 번호).
    """
    with (eval_dir / "sets.csv").open(encoding="utf-8", newline="") as fh:
        rows = [r for r in csv.DictReader(fh) if r["split"] == split]
    rows.sort(key=lambda r: (r["set_id"], int(r["line"])))
    co_hs: dict[tuple[str, int], str] = {}
    with (eval_dir / "fields.csv").open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            m = re.fullmatch(r"items\[(\d+)\]\.hs_code", r["field"])
            if m and r["doc"] == "certificate_of_origin":
                co_hs[(r["set_id"], int(m.group(1)) + 1)] = _digits(r["answer"])
    inv_hs: dict[tuple[str, int], str] = {}
    kinds: dict[str, set[str]] = defaultdict(set)
    for a in load_answers(eval_dir / "answers.csv"):
        kinds[a["set_id"]].add(a["error_type"])
        m = re.fullmatch(r"items\[(\d+)\]\.hs_code", a["field"] or "")
        if a["error_type"] == "trap_all_docs" and a["doc"] == "commercial_invoice" and m:
            inv_hs[(a["set_id"], int(m.group(1)) + 1)] = _digits(a["planted_value"])
    normal = {s for s, k in kinds.items() if k == {"none"}}
    return {"rows": rows, "co_hs": co_hs, "inv_hs": inv_hs, "normal": normal}


def _hs_docs(row: dict, co_hs: dict, inv_hs: dict) -> list[ExtractedDocument]:
    line, sid = int(row["line"]), row["set_id"]

    def cell(text: str) -> Cell:
        return Cell(raw=text, value=text)

    inv = ExtractedItem(
        line=line, name=cell(row["item"]), hs_code=cell(inv_hs[(sid, line)]) if (sid, line) in inv_hs else None
    )
    docs = [ExtractedDocument(doc_type="commercial_invoice", file=f"oracle/{sid}/commercial_invoice", items=[inv])]
    if (sid, line) in co_hs:
        item = ExtractedItem(line=line, hs_code=cell(co_hs[(sid, line)]))
        docs.append(ExtractedDocument(doc_type="certificate_of_origin", file=f"oracle/{sid}/co", items=[item]))
    return docs


def score_hs(inputs: dict, table, mode: str = "none", clean_sets: set[str] | None = None) -> dict:
    """품목 행마다 recommend_hs를 돌려 HS 지표와 자동 처리율을 센다. 모델 호출 없음.
    언제: 규칙·HS 표·확정 조건을 고친 뒤. 받는 것: load_hs_inputs 결과, HS 표(HSTable), mode(HS_MODES),
    clean_sets(cross_check에 불일치·확인 필요가 없는 세트. None이면 모두 깨끗하다고 본다).
    mode: none = 모델 없음(자동 확정은 확정 이력만), oracle = 후보 안에 정답이 있으면 1순위로(상한), trap = 헷갈리는 HS를 1순위로(최악),
    bedrock = 진짜 Bedrock 모델이 검색어를 뽑고 후보에서 고른다(bedrock_terms_reader·bedrock_picker. 이때만 모델을 부른다).
    '사람 확인 필요'가 나오면 정답 HS를 사람이 고른 것처럼 넣고 계속한다. 이력은 비운 상태에서 시작해 세트 순서대로 쌓인다.
    반환: 건수 dict. wrong_auto는 0이어야 한다.
    """
    from tools.hs import confirm_by_human, item_key, recommend_hs
    from tools.models import HSPick

    if mode not in (*HS_MODES, MODEL_MODE):
        raise ValueError(f"mode는 {(*HS_MODES, MODEL_MODE)} 중 하나: {mode}")
    if mode == MODEL_MODE:
        from tools.hs import bedrock_picker, bedrock_terms_reader
    history = _MemoryHistory()
    out = dict(
        rows=0, answer_not_in_table=0, auto=0, by_history=0, by_auto_match=0, wrong_auto=0,
        human=0, human_in_top3=0, human_in_candidates=0, trap_top=0, trap_auto=0,
    )
    set_auto: dict[str, bool] = {}
    for row in inputs["rows"]:
        sid, line, answer, trap = row["set_id"], int(row["line"]), row["hs_answer"], row["trap_hs"]
        docs = _hs_docs(row, inputs["co_hs"], inputs["inv_hs"])
        seen: dict[str, list] = {"cands": []}

        def picker(name, cands, answer=answer, trap=trap, seen=seen):
            seen["cands"] = cands
            if mode == MODEL_MODE:
                return bedrock_picker(name, cands)
            by_hs = {c.hs: c for c in cands}
            order = {"none": [], "oracle": [answer], "trap": [trap, answer]}[mode]
            return HSPick(picks=[by_hs[h] for h in order if h in by_hs])

        with contextlib.redirect_stdout(io.StringIO()):  # [tool] 출력을 숨긴다
            result = recommend_hs(
                docs, line, row["consignee"], history=history, table=table, picker=picker,
                terms_reader=bedrock_terms_reader if mode == MODEL_MODE else None,
            )
        out["rows"] += 1
        out["answer_not_in_table"] += 0 if table.exists(answer) else 1
        if result.status == "자동 확정":
            out["auto"] += 1
            out["by_history" if result.by == "history" else "by_auto_match"] += 1
            if result.hs_code != answer:
                out["wrong_auto"] += 1
            if result.hs_code == trap:
                out["trap_auto"] += 1
            set_auto[sid] = set_auto.get(sid, True)
            continue
        set_auto[sid] = False
        out["human"] += 1
        shown = [c.hs for c in result.candidates]
        out["human_in_top3"] += answer in shown
        out["human_in_candidates"] += answer in [c.hs for c in seen["cands"]]
        out["trap_top"] += bool(shown) and shown[0] == trap
        with contextlib.redirect_stdout(io.StringIO()):
            confirm_by_human(result, answer, row["consignee"], item_key(docs[0], line), sid, history=history)
    normal = sorted(inputs["normal"] & set(set_auto))
    clean = set(set_auto) if clean_sets is None else clean_sets
    out["normal_sets"] = len(normal)
    out["auto_registered"] = sum(1 for s in normal if set_auto[s] and s in clean)
    out["mode"] = mode
    return out


def format_hs_report(r: dict) -> str:
    """score_hs 결과를 건수 문장으로 쓴다."""
    return "\n".join(
        [
            f"HS (모델 대신: {r['mode']}) 품목 {r['rows']}행",
            f"  자동 확정 {r['auto']}건 (이력 {r['by_history']}, auto_match {r['by_auto_match']}), 그중 틀린 것 {r['wrong_auto']}건",
            f"  사람 확인 필요 {r['human']}건 중 정답이 후보 3개 안 {r['human_in_top3']}건, 후보 목록(30개) 안 {r['human_in_candidates']}건",
            f"  헷갈리는 HS를 1순위로 낸 건 {r['trap_top']}건, 자동 확정한 건 {r['trap_auto']}건",
            f"  자동 처리율: 정상 {r['normal_sets']}세트 중 사람 손 없이 WMS 등록까지 {r['auto_registered']}세트",
            f"  (정답 HS가 HS부호 표에 없는 행 {r['answer_not_in_table']}건)",
        ]
    )


def main() -> None:
    """정답 값으로 규칙만 채점한다 (모델 호출 없음). 예: uv run python -m eval.score --split dev [--hs] [--hs-model]"""
    from tools.validate import cross_check  # 순환을 피하려고 여기서 부른다

    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument("--split", default="dev", choices=["dev", "test"])
    parser.add_argument("--hs", action="store_true", help="HS 확정과 자동 처리율도 센다 (모델 없음·정답·함정 세 가지)")
    parser.add_argument("--hs-model", action="store_true", help="진짜 Bedrock 모델로 HS를 추천해 센다 (aws login과 MODEL_ID 필요, 모델을 부른다)")
    args = parser.parse_args()
    if args.split == "test":
        raise SystemExit("발표용(test)은 저장소에 없고 마지막에 한 번만 돌린다. 이 명령은 dev만 지원한다.")
    docs = oracle_docs()
    with contextlib.redirect_stdout(io.StringIO()):  # cross_check의 [tool] 출력을 숨긴다
        issues = {set_id: cross_check(d) for set_id, d in docs.items() if len(d) >= 2}
    formats = load_formats()
    detection = score_detection(load_answers(), issues, args.split, fmt_by_doc=formats)
    fields = score_fields(EVAL_DIR / "fields.csv", docs, fmt_by_doc=formats)
    print(format_report(detection, fields))
    if args.hs or args.hs_model:
        from tools.hs import load_hs_table

        table = load_hs_table()
        inputs = load_hs_inputs(args.split)
        clean = {s for s in inputs["normal"] if not [i for i in issues.get(s, []) if i.grade != "참고"]}
        for mode in (HS_MODES if args.hs else ()) + ((MODEL_MODE,) if args.hs_model else ()):
            print()
            print(format_hs_report(score_hs(inputs, table, mode, clean)), flush=True)


if __name__ == "__main__":
    main()
