"""C4 신고서 칸 목록이 docs/schema.md, 정답지(eval/declarations.csv)와 같은지 본다. AWS 호출 없음. 담당: 검증."""
import csv
import re
from pathlib import Path

from tools.declaration import DECLARATION_FIELDS

ROOT = Path(__file__).resolve().parents[2]


def _schema_rows() -> list[tuple[str, str, str, str]]:
    """schema.md '신고서 초안 칸' 절의 표 줄 → (field, 신고서 칸, 출처, 읽기 칸)."""
    text = (ROOT / "docs" / "schema.md").read_text(encoding="utf-8")
    section = text.split("## 신고서 초안 칸", 1)[1].split("\n## ", 1)[0]
    rows = []
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("|") and len(cells) == 4 and cells[0].startswith("`"):
            rows.append((cells[0].strip("`"), cells[1], re.sub(r" \(.*$", "", cells[2]).strip("`"), cells[3]))
    return rows


def test_코드_표가_schema와_같다():
    schema = [(label, source) for _, label, source, _ in _schema_rows()]
    assert DECLARATION_FIELDS == schema


def test_정답지_칸_이름과_같다():
    with open(ROOT / "eval" / "declarations.csv", encoding="utf-8", newline="") as fh:
        truth = {(r["field"], r["label"]) for r in csv.DictReader(fh)}
    assert {(f, label) for f, label, _, _ in _schema_rows()} == truth


def test_정답지_출처와_같다_세번부호만_HS_결과에서():
    with open(ROOT / "eval" / "declarations.csv", encoding="utf-8", newline="") as fh:
        truth = {r["field"]: r["source"] for r in csv.DictReader(fh)}
    for field, _, source, _ in _schema_rows():
        if field == "hs_code":
            assert source == "hs[0].hs_code"
        else:
            assert truth[field] == source


def test_읽기_칸_표시는_있음_또는_없음():
    assert {r[3] for r in _schema_rows()} == {"있음", "없음"}


def test_칸은_중복이_없다():
    names = [n for n, _ in DECLARATION_FIELDS]
    assert len(names) == len(set(names)) == 23
