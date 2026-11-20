"""docs/examples/*.json 이 tools/models.py 와 맞는지 확인한다 (약속 위반 감지)."""

import json
from pathlib import Path

import pytest

from tools.models import (
    ChatHistoryResponse,
    ChatResponse,
    DocumentsResponse,
    ExtractedDocument,
    Job,
    JobFilesResponse,
    JobListResponse,
    NoticeDocument,
    Shipment,
    StatsResponse,
)

EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "examples"

CASES = [
    ("extract_packing_list.json", ExtractedDocument),
    ("job_waiting_approval.json", Job),
    ("chat_response.json", ChatResponse),
    ("chat_chart_response.json", ChatResponse),
    ("shipment.json", Shipment),
    ("documents.json", DocumentsResponse),
    ("job_files.json", JobFilesResponse),
    ("notice.json", NoticeDocument),
    ("stats.json", StatsResponse),
    ("chat_history.json", ChatHistoryResponse),
    ("jobs.json", JobListResponse),
]


@pytest.mark.parametrize(("name", "model"), CASES)
def test_example_matches_model(name, model):
    data = json.loads((EXAMPLES / name).read_text(encoding="utf-8"))
    model.model_validate(data)


def test_all_examples_covered():
    """예시 파일을 새로 넣으면 여기에도 모델을 짝지어야 한다."""
    assert {p.name for p in EXAMPLES.glob("*.json")} == {name for name, _ in CASES}


def test_chat_history_example_shape():
    """대화 기록 예시 (E6 #157): 한 세션 4줄, 질문·답 차례, 통관 지연 답 하나와 막힌 답 하나, ts 오름차순."""
    lines = json.loads((EXAMPLES / "chat_history.json").read_text(encoding="utf-8"))["messages"]
    assert len(lines) == 4
    assert [line["role"] for line in lines] == ["user", "assistant", "user", "assistant"]
    assert len({line["session_id"] for line in lines}) == 1
    answers = [line for line in lines if line["role"] == "assistant"]
    assert sum(line["rule"] is not None for line in answers) == 1
    assert sum(line["blocked"] is True for line in answers) == 1
    ts = [line["ts"] for line in lines]
    assert ts == sorted(ts)
    assert all(t[:17].isdigit() and t[17] == "#" for t in ts)


def test_서류_보기_예시의_현장_표시는_SITE_FIELDS와_같다():
    """job_files.json의 fields[].site가 SITE_FIELDS(서류 종류별 현장 칸)와 맞아야 화면이 예시대로 거른다 (B12 #228)."""
    import re

    from tools.models import SITE_FIELDS

    data = json.loads((EXAMPLES / "job_files.json").read_text(encoding="utf-8"))
    for file in data["files"]:
        for f in file["fields"]:
            expected = re.sub(r"\[\d+\]", "", f["field"]) in SITE_FIELDS[file["doc_type"]]
            assert f.get("site", False) is expected, (file["doc_type"], f["field"])
