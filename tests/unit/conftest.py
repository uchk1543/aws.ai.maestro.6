"""tests/unit 공통 준비. 단위 테스트가 실제 team06-chat에 쓰지 못하게 한다 (E6 #157)."""

import sys

import pytest


@pytest.fixture(autouse=True)
def _no_real_chat_table(monkeypatch):
    """CHAT_TABLE을 지우고 _chat_store 캐시를 앞뒤로 비운다. 그래서 _chat_store()는 boto3를 만들기 전에 KeyError를 낸다.

    session_id가 있는 POST /chat 요청(test_query_agent.py의 "s1" 등)은 기록을 시도하지만 [warn] 로그만 남는다.
    """
    monkeypatch.delenv("CHAT_TABLE", raising=False)
    _clear_chat_store()
    yield
    _clear_chat_store()


def _clear_chat_store() -> None:
    handler = sys.modules.get("api.handler")  # 아직 import 안 했으면 캐시도 없다. 다른 테스트의 import 순서를 바꾸지 않는다
    if handler is not None and hasattr(handler, "_chat_store") and hasattr(handler._chat_store, "cache_clear"):
        handler._chat_store.cache_clear()
