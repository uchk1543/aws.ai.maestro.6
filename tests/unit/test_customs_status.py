"""E1 통관 상태 값과 지연 기준이 schema.md, 1번의 시드 생성기(samples/make_extra.py), 시드 데이터와 같은지 본다. AWS 호출 없음. 담당: 검증."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = (ROOT / "docs" / "schema.md").read_text(encoding="utf-8")


def _schema_statuses() -> list[str]:
    line = next(l for l in SCHEMA.splitlines() if "→" in l and "`입항`" in l)
    return re.findall(r"`([^`]+)`", line)


def _schema_delay_days() -> int:
    return int(re.search(r"≥ \*\*(\d+)일\*\*", SCHEMA).group(1))


def test_상태_값은_진행_순서_6개():
    assert _schema_statuses() == ["입항", "수입신고", "심사 중", "검사 중", "수리", "반출"]


def test_통관_지연은_상태_값이_아니다():
    assert "통관 지연" not in _schema_statuses()


def test_지연_일수는_숫자로_적혀_있다():
    assert _schema_delay_days() == 3


def test_시드_생성기_상수와_같다():
    text = (ROOT / "samples" / "make_extra.py").read_text(encoding="utf-8")
    statuses = re.search(r"^STATUSES = \[(.*?)\]", text, re.M).group(1)
    assert re.findall(r'"([^"]+)"', statuses) == _schema_statuses()
    assert int(re.search(r"^DELAY_DAYS = (\d+)", text, re.M).group(1)) == _schema_delay_days()
    cleared = re.search(r"^CLEARED = \{(.*?)\}", text, re.M).group(1)
    assert set(re.findall(r'"([^"]+)"', cleared)) == {"수리", "반출"}


def test_시드_화물_기록의_상태는_모두_목록_안():
    records = json.loads((ROOT / "samples" / "data" / "shipments.json").read_text(encoding="utf-8"))
    if isinstance(records, dict):
        records = next(v for v in records.values() if isinstance(v, list))
    assert records and {r["customs_status"] for r in records} <= set(_schema_statuses())
