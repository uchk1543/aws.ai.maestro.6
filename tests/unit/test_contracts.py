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
import typing
from dataclasses import dataclass

import pytest

from tools.models import (
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
