"""현황 조회 Agent(answer) 단위 테스트. 질문 → 조건 모델은 가짜로 대신한다 (Bedrock·AWS 호출 없음)."""

import json
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from agent.query_agent import answer, compose_answer, filter_prompt
from tests.unit.fakes import MemoryShipments
from tools.models import ChatFilters, ChatResponse, Shipment

ROOT = Path(__file__).resolve().parents[2]
SHIPMENTS = [Shipment.model_validate(r) for r in json.loads((ROOT / "samples/data/shipments.json").read_text(encoding="utf-8"))]
TODAY = date(2026, 11, 21)
STORE = MemoryShipments(SHIPMENTS)


def parser_of(**filters):
    calls = []

    def parser(question, prompt):
        calls.append((question, prompt))
        return ChatFilters.model_validate(filters)

    parser.calls = calls
    return parser


def test_delayed_this_week_counts_by_code():
    parser = parser_of(status="통관 지연", period="this_week")
    res = answer("이번 주 통관 지연 건 알려줘", "s1", store=STORE, today=TODAY, parser=parser)
    ChatResponse.model_validate(res.model_dump(mode="json", by_alias=True))  # 약속 2 형식
    assert len(res.rows) == 3
    assert res.answer.startswith("이번 주(11/16~11/22) 통관 지연 건은 3건입니다.")
    assert "(통관 지연 기준: 입항 후 3일 지나도 수리·반출 아님)" in res.answer
    assert all(r.bl_no in res.answer for r in res.rows)
    assert "2026-11-21 (토요일" in parser.calls[0][1]


def test_zero_rows_says_zero_and_conditions():
    res = answer("다음 주 입항 화물 있어?", "s1", store=STORE, today=TODAY,
                 parser=parser_of(period="range", date_from="2026-11-23", date_to="2026-11-29"))
    assert res.rows == []
    assert res.answer == "11/23~11/29 입항한 화물은 0건입니다. 조회 조건: 상태 조건 없음, 입항일 2026-11-23~2026-11-29."


def test_many_rows_list_first_five():
    res = answer("10월에 입항한 화물", "s1", store=STORE, today=TODAY,
                 parser=parser_of(period="range", date_from="2026-10-01", date_to="2026-10-31"))
    assert len(res.rows) == 20 and "외 15건." in res.answer


def test_status_spacing_is_normalized_and_unknown_status_is_not_queried():
    res = answer("검사중 화물", "s1", store=STORE, today=TODAY, parser=parser_of(status="검사중"))
    assert res.filters.status == "검사 중" and len(res.rows) == 9
    res = answer("보류된 화물", "s1", store=STORE, today=TODAY, parser=parser_of(status="보류"))
    assert res.rows == [] and "'보류' 상태는 화물 기록에 없습니다" in res.answer


def test_model_failure_twice_gives_message_not_error():
    def broken(question, prompt):
        raise ValidationError.from_exception_data("ChatFilters", [])

    res = answer("아무거나", "s1", store=STORE, today=TODAY, parser=broken)
    assert res.rows == [] and "조회 조건으로 바꾸지 못했습니다" in res.answer


def test_prompt_lists_statuses_and_keeps_date_math_in_code():
    prompt = filter_prompt(TODAY)
    for word in ("입항", "수입신고", "심사 중", "검사 중", "수리", "반출", "통관 지연", "계산하지 않는다", "지시"):
        assert word in prompt


def test_compose_answer_whole_period():
    from tools.query import query_shipments

    result = query_shipments(ChatFilters(status="심사 중"), store=STORE, today=TODAY)
    assert compose_answer(result).startswith("지금까지 '심사 중' 상태 화물은 4건입니다.")


# ---------------------------------------------------------------------------
# POST /chat (api/handler.py) — 질문 → 조건 모델과 DynamoDB는 가짜
# ---------------------------------------------------------------------------
class FakeScanTable:
    """DynamoDB Scan을 두 쪽으로 나눠 돌려준다 (LastEvaluatedKey 넘기기 확인)."""

    def __init__(self, items):
        self.items = items

    def scan(self, **kwargs):
        half = len(self.items) // 2
        if "ExclusiveStartKey" not in kwargs:
            return {"Items": self.items[:half], "LastEvaluatedKey": {"bl_no": "x"}}
        return {"Items": self.items[half:]}


def test_dynamo_shipments_reads_all_pages():
    from tools.query import DynamoShipments

    items = [s.model_dump(mode="json", exclude_none=True) for s in SHIPMENTS]  # 시드와 같은 모양 (job_id 칸 없음)
    assert DynamoShipments(FakeScanTable(items)).all() == SHIPMENTS


def call_chat(monkeypatch, body, path="/api/chat", **filters):
    from agent import query_agent
    from api import handler
    from tools import query

    monkeypatch.setattr(query_agent, "_strands_parser", parser_of(**filters))
    monkeypatch.setattr(query, "dynamo_shipments", lambda: STORE)
    event = {"requestContext": {"http": {"method": "POST"}}, "rawPath": path, "body": json.dumps(body)}
    res = handler.lambda_handler(event, None)
    return res["statusCode"], json.loads(res["body"])


def test_chat_route_answers_in_contract_shape(monkeypatch):
    status, body = call_chat(monkeypatch, {"session_id": "s1", "message": "심사 중인 화물 전체 알려줘"}, status="심사 중")
    assert status == 200
    ChatResponse.model_validate(body)
    assert len(body["rows"]) == 4 and "4건" in body["answer"]
    assert call_chat(monkeypatch, {"message": "심사 중 화물"}, path="/chat", status="심사 중")[0] == 200  # 옮기는 동안 /api 없이도


def test_chat_route_rejects_bad_body(monkeypatch):
    assert call_chat(monkeypatch, {"session_id": "s1", "message": "  "})[0] == 400
    assert call_chat(monkeypatch, {"session_id": "s1", "message": "가" * 501})[0] == 400
    assert call_chat(monkeypatch, {"session_id": 3, "message": "오늘 입항"})[0] == 400
