"""담당 사이 연결 약속 검사 (공용 파일). 담당: PM

담당끼리 서로 부르는 함수의 이름, 받는 것, 반환이 약속과 같은지 본다.
몸통이 비어 있어도(NotImplementedError) 모양은 지금부터 고정이다.

허용: 끝에 키워드 전용 인자를 기본값과 함께 더하는 것 (부르는 쪽이 깨지지 않는다).
금지: 약속된 인자의 이름·순서·종류를 바꾸거나 빼는 것, 반환 타입을 바꾸는 것.

약속을 바꿔야 하면: 이슈(라벨 '공용 파일') → PM 승인 → 이 파일과 부르는 쪽 코드를 같은 PR에서 함께 고친다.
(CONTRIBUTING.md '공용 파일 바꾸는 순서')
"""

import importlib
import inspect
import random
import typing
from dataclasses import dataclass

import pytest
from pydantic import ValidationError

from tools.models import (
    ChatFilters,
    ChatHistoryLine,
    ChatHistoryResponse,
    ChatResponse,
    Classification,
    DeclarationDraft,
    ExtractedDocument,
    HSResult,
    Issue,
    Job,
    OcrResult,
    PeriodResolved,
    QueryResult,
    ReportCheck,
    RereadResult,
    WmsState,
)

POS = inspect.Parameter.POSITIONAL_OR_KEYWORD
KW = inspect.Parameter.KEYWORD_ONLY


@dataclass(frozen=True)
class Contract:
    path: str  # "모듈:함수"
    params: tuple[tuple[str, inspect._ParameterKind], ...]
    returns: object
    maker: str  # 만드는 담당
    callers: str  # 부르는 담당


def P(*names: str, kw: tuple[str, ...] = ()):
    return tuple((n, POS) for n in names) + tuple((n, KW) for n in kw)


CONTRACTS = [
    # 1번 판독이 만들고, 다른 담당이 부른다
    Contract("tools.extract:read_document", P("file", "data", "doc_type", kw=("reader",)), ExtractedDocument, "1번 판독", "1번 에이전트 루프, 4번 API"),
    Contract("tools.extract:classify_document", P("file", "data", kw=("reader",)), Classification, "1번 판독", "1번 에이전트 루프"),
    Contract("tools.reread:reread_field", P("doc", "field", "data", kw=("ocr", "reader")), RereadResult, "1번 판독", "1번 에이전트 루프"),
    Contract("tools.reread:apply_rereads", P("issues", "rereads"), list[Issue], "1번 판독", "1번 에이전트 루프"),
    Contract("tools.report:finish_report", P("state"), ReportCheck, "1번 판독", "1번 에이전트 루프, 4번 WMS 조건"),
    Contract("tools.query:query_shipments", P("filters", kw=("store", "today")), QueryResult, "1번 판독", "1번 현황 Agent"),
    Contract("tools.query:resolve_period", P("filters", "today"), PeriodResolved | None, "1번 판독", "1번 현황 Agent"),
    Contract(
        "agent.document_agent:run_job",
        P("job_id", "files", "fetch", kw=("reader", "classifier", "on_step", "rereader", "hs_recommender", "agent_model", "on_docs")),
        Job, "1번 판독", "4번 처리 Lambda (on_step·hs_recommender·on_docs를 넘김, #122)",
    ),
    # 두 Lambda 진입점. 이름은 infra/create.sh의 --handler와 같다 (api.handler.lambda_handler, api.worker.lambda_handler)
    Contract("api.handler:lambda_handler", P("event", "context"), None, "4번 서버", "PM 배포 (API Lambda team06-api)"),
    Contract("api.worker:lambda_handler", P("event", "context"), None, "4번 서버", "PM 배포 (처리 Lambda team06-worker)"),
    Contract("agent.query_agent:answer", P("question", "session_id", kw=("store",)), ChatResponse, "1번 판독", "4번 API"),
    # 2번 검증이 만들고, 1번·4번이 부른다
    Contract("tools.validate:cross_check", P("docs"), list[Issue], "2번 검증", "1번 에이전트 루프"),
    Contract("tools.hs:recommend_hs", P("docs", "line", "importer", kw=("history", "table", "terms_reader", "picker")), HSResult, "2번 검증", "1번 에이전트 루프"),
    Contract("tools.hs:confirm_by_human", P("result", "hs", "importer", "key", "job_id", kw=("history",)), HSResult, "2번 검증", "4번 API (POST /jobs/{id}/hs)"),
    Contract("tools.hs:item_key", P("doc", "line"), str, "2번 검증", "2번, 4번 API"),
    Contract("tools.declaration:draft_declaration", P("docs", "issues", "hs"), DeclarationDraft, "2번 검증", "1번 에이전트 루프, 4번 API"),
    Contract("tools.certificate:make_certificate", P("job", "docs", kw=("importer",)), bytes, "PM", "4번 API (GET /jobs/{id}/certificate)"),
    # 4번 서버가 만들고, 1번·4번이 부른다
    Contract("tools.ocr:ocr_document", P("file", "data", kw=("client",)), OcrResult, "4번 서버", "1번 판독·다시 확인"),
    Contract("tools.wms:push_to_wms", P("record", kw=("adapter",)), WmsState, "4번 서버", "4번 API, 1번 리포트 뒤"),
    Contract("tools.wms:can_auto_register", P("result"), bool, "4번 서버", "4번 API, 1번 리포트 뒤"),
]

# 4번이 DynamoDB판으로 구현하고 1·2번이 쓰는 저장소 모양: 클래스 → (메서드, 인자 이름)
PROTOCOLS = {
    "tools.hs:HSHistory": {"get": ("importer", "item_key"), "put": ("importer", "item_key", "hs", "job_id")},
    "tools.hs:HSTable": {"search": ("terms", "limit"), "under": ("prefix6",), "exists": ("hs",)},
    "tools.query:ShipmentStore": {"all": ()},
    "tools.wms:WmsAdapter": {"register": ("record",), "registered_jobs": ("bl_no",)},
    "tools.ocr:TextractClient": {"analyze_document": ()},
}


def _load(path: str):
    module, name = path.split(":")
    return getattr(importlib.import_module(module), name)


def _fmt(params) -> str:
    """[('docs', POS), ('reader', KW)] → 'docs, *, reader'"""
    pos = [n for n, k in params if k != KW]
    kw = [n for n, k in params if k == KW]
    return ", ".join(pos + (["*"] + kw if kw else [])) or "(없음)"


def _how_to_fix(c: Contract) -> str:
    return (
        f"\n  만드는 담당: {c.maker} / 부르는 담당: {c.callers}"
        "\n  약속을 바꾸려면 이슈(라벨 '공용 파일') → PM 승인 → tests/unit/test_contracts.py와 부르는 쪽을 같은 PR에서 고친다."
    )


@pytest.mark.parametrize("c", CONTRACTS, ids=lambda c: c.path)
def test_function_contract(c: Contract):
    fn = _load(c.path)
    params = list(inspect.signature(fn).parameters.values())
    got = [(p.name, p.kind) for p in params]
    agreed = list(c.params)

    assert got[: len(agreed)] == agreed, (
        f"{c.path}의 받는 것이 약속과 다릅니다.\n  약속: ({_fmt(agreed)})\n  지금: ({_fmt(got)})" + _how_to_fix(c)
    )
    for p in params[len(agreed):]:
        assert p.kind == KW and p.default is not inspect.Parameter.empty, (
            f"{c.path}에 새 인자 '{p.name}'이 있습니다. 끝에 키워드 전용 + 기본값으로만 더할 수 있습니다." + _how_to_fix(c)
        )
    returns = typing.get_type_hints(fn).get("return")
    assert returns == c.returns, f"{c.path}의 반환이 약속과 다릅니다.\n  약속: {c.returns}\n  지금: {returns}" + _how_to_fix(c)


@pytest.mark.parametrize("path", PROTOCOLS, ids=list(PROTOCOLS))
def test_protocol_contract(path: str):
    cls = _load(path)
    for method, names in PROTOCOLS[path].items():
        assert hasattr(cls, method), f"{path}에 {method}가 없습니다. 4번의 DynamoDB판과 tests/unit/fakes.py가 이 모양을 따릅니다."
        got = [n for n in inspect.signature(getattr(cls, method)).parameters if n not in ("self", "kwargs")]
        assert tuple(got[: len(names)]) == names, f"{path}.{method}의 받는 것이 약속과 다릅니다. 약속: {names}, 지금: {got}"


def test_fakes_follow_protocols():
    """테스트용 메모리판이 같은 모양이어야 각자 테스트한 것이 합쳤을 때도 맞는다."""
    from tests.unit.fakes import MemoryHSHistory, MemoryShipments, MemoryWms

    pairs = {MemoryHSHistory: "tools.hs:HSHistory", MemoryShipments: "tools.query:ShipmentStore", MemoryWms: "tools.wms:WmsAdapter"}
    for fake, path in pairs.items():
        for method, names in PROTOCOLS[path].items():
            got = [n for n in inspect.signature(getattr(fake, method)).parameters if n != "self"]
            assert tuple(got[: len(names)]) == names, f"{fake.__name__}.{method}가 {path}와 다릅니다"


# ---------------------------------------------------------------------------
# 대화 기록 한 줄 규칙 (E6 #157). 모델만 본다 (api.handler는 부르지 않는다)
# ---------------------------------------------------------------------------
HISTORY_FIELDS = ["session_id", "ts", "role", "text", "filters", "count", "rule", "blocked", "block_reason"]
_LINE_KEY = {"session_id": "s1", "ts": "20261121090000123#a1b2c3d4#0"}


def test_chat_history_fields():
    """기록 한 줄은 9칸이고 expires_at(저장 칸)은 없다. 모르는 칸은 실패한다 (_Strict)."""
    assert list(ChatHistoryLine.model_fields) == HISTORY_FIELDS
    assert list(ChatHistoryResponse.model_fields) == ["messages"]
    with pytest.raises(ValidationError):
        ChatHistoryLine(**_LINE_KEY, role="user", text="질문", expires_at=1795824000)
    with pytest.raises(ValidationError):
        ChatHistoryLine(**_LINE_KEY, role="user", text="질문", data="{}")


_F = ChatFilters(status="통관 지연", period="this_week")


@pytest.mark.parametrize(
    ("fields", "ok"),
    [
        # 통과: 질문 줄, 조회한 답 줄, 조회하지 않은 답 줄(count null), 막힌 답 줄
        ({"role": "user"}, True),
        ({"role": "assistant", "filters": _F, "count": 1, "rule": "입항 후 3일 지나도 수리·반출 아님", "blocked": False}, True),
        ({"role": "assistant", "filters": ChatFilters(unsupported=["수하인 샘플무역"]), "blocked": False}, True),
        ({"role": "assistant", "blocked": True, "block_reason": "무관한 질문"}, True),
        # 2.3 질문 줄에 답 칸
        ({"role": "user", "count": 0}, False),
        # 2.4 답 줄에 blocked 없음
        ({"role": "assistant", "filters": _F, "count": 1}, False),
        # 2.5 막지 않은 답 줄에 filters 없음, 조회하지 않았는데(count null) rule
        ({"role": "assistant", "count": 1, "blocked": False}, False),
        ({"role": "assistant", "filters": _F, "rule": "입항 후 3일 지나도 수리·반출 아님", "blocked": False}, False),
        # 2.6 막지 않은 답 줄에 block_reason
        ({"role": "assistant", "filters": _F, "count": 1, "blocked": False, "block_reason": "무관한 질문"}, False),
        # 2.7 막힌 답 줄에 이유 없음·빈 이유
        ({"role": "assistant", "blocked": True}, False),
        ({"role": "assistant", "blocked": True, "block_reason": ""}, False),
        # 막힌 답 줄에 조회 칸
        ({"role": "assistant", "blocked": True, "block_reason": "무관한 질문", "count": 5}, False),
        ({"role": "assistant", "blocked": True, "block_reason": "무관한 질문", "filters": _F}, False),
        ({"role": "assistant", "blocked": True, "block_reason": "무관한 질문", "rule": "입항 후 3일 지나도 수리·반출 아님"}, False),
    ],
    ids=["user", "answered", "not-queried", "blocked", "user-with-count", "no-blocked", "no-filters", "rule-without-count",
         "answered-with-reason", "blocked-no-reason", "blocked-empty-reason", "blocked-with-count", "blocked-with-filters",
         "blocked-with-rule"],
)
def test_chat_history_line_rule_examples(fields, ok):
    if ok:
        ChatHistoryLine(**_LINE_KEY, text="글", **fields)
    else:
        with pytest.raises(ValidationError):
            ChatHistoryLine(**_LINE_KEY, text="글", **fields)


def random_line_fields(rng: random.Random):
    """role과 다섯 칸을 무작위로 (각 칸 null 포함, block_reason은 '' 포함).

    아무렇게나 고르면 맞는 줄이 드물어서, 절반은 맞는 줄(질문·조회한 답·막힌 답) 하나에서 시작해 칸 하나를 0~1번 바꾼다.
    """
    choices = {
        "filters": [None, ChatFilters(), _F, ChatFilters(unsupported=["수하인 샘플무역"])],
        "count": [None, 0, 1, rng.randint(2, 500)],
        "rule": [None, "입항 후 3일 지나도 수리·반출 아님"],
        "blocked": [None, False, True],
        "reason": [None, "", "무관한 질문", "프롬프트 공격", " "],
    }
    if rng.random() < 0.5:
        role = rng.choice(["user", "assistant"])
        fields = {name: rng.choice(values) for name, values in choices.items()}
    else:
        role, fields = rng.choice([
            ("user", dict.fromkeys(choices)),
            ("assistant", {"filters": rng.choice(choices["filters"][1:]), "count": rng.choice(choices["count"][1:]),
                           "rule": rng.choice(choices["rule"]), "blocked": False, "reason": None}),
            ("assistant", {"filters": rng.choice(choices["filters"][1:]), "count": None, "rule": None,
                           "blocked": False, "reason": None}),
            ("assistant", {"filters": None, "count": None, "rule": None, "blocked": True,
                           "reason": rng.choice(choices["reason"][2:])}),
        ])
        if rng.random() < 0.5:
            name = rng.choice(list(choices))
            fields[name] = rng.choice(choices[name])
    return role, fields["filters"], fields["count"], fields["rule"], fields["blocked"], fields["reason"]


def _line_ok(role, filters, count, rule, blocked, reason) -> bool:
    """독립 판정: 요구 2.3~2.7 + 조회하지 않은 답(count null)에는 rule 없음, 막힌 답에는 조회 칸 없음."""
    if role == "user":
        return all(v is None for v in (filters, count, rule, blocked, reason))
    if blocked is None:
        return False
    if blocked is False:
        return filters is not None and reason is None and (rule is None or count is not None)
    return isinstance(reason, str) and reason != "" and filters is None and count is None and rule is None


@pytest.mark.parametrize("seed", range(100))
def test_chat_history_line_null_rules(seed):
    """Feature: e6-chat-history, Property 1: 기록 줄 null 규칙

    Validates: Requirements 2.3, 2.4, 2.5, 2.6, 2.7, 2.12
    """
    rng = random.Random(seed)
    role, filters, count, rule, blocked, reason = random_line_fields(rng)
    kwargs = dict(role=role, text="글", filters=filters, count=count, rule=rule, blocked=blocked, block_reason=reason)
    if _line_ok(role, filters, count, rule, blocked, reason):
        line = ChatHistoryLine(**_LINE_KEY, **kwargs)
        assert (line.role, line.blocked, line.block_reason) == (role, blocked, reason)
    else:
        with pytest.raises(ValidationError):
            ChatHistoryLine(**_LINE_KEY, **kwargs)
