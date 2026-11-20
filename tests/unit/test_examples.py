"""docs/examples/*.json 이 tools/models.py 와 맞는지 확인한다 (약속 위반 감지)."""

import json
from pathlib import Path

import pytest

from tools.models import ChatResponse, DocumentsResponse, ExtractedDocument, Job, JobFilesResponse, Shipment, StatsResponse

EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "examples"

CASES = [
    ("extract_packing_list.json", ExtractedDocument),
    ("job_waiting_approval.json", Job),
    ("chat_response.json", ChatResponse),
    ("shipment.json", Shipment),
    ("documents.json", DocumentsResponse),
    ("job_files.json", JobFilesResponse),
    ("stats.json", StatsResponse),
]


@pytest.mark.parametrize(("name", "model"), CASES)
def test_example_matches_model(name, model):
    data = json.loads((EXAMPLES / name).read_text(encoding="utf-8"))
    model.model_validate(data)


def test_all_examples_covered():
    """예시 파일을 새로 넣으면 여기에도 모델을 짝지어야 한다."""
    assert {p.name for p in EXAMPLES.glob("*.json")} == {name for name, _ in CASES}
