"""AI 客户端 provider 分支契约：按设置构建（deepseek/glm/ollama/mindvault）/缺 Key 降级 None/流式错误路径。"""
import httpx
import pytest
from sqlmodel import Session

from app.database import session_factory
from app.services.ai_client import AiClient, AiError, build_ai_client
from app.services import settings_service


def _set(session: Session, key: str, value: str) -> None:
    settings_service.set_value(session, key, value)


def test_build_ai_client_defaults_to_deepseek_without_key(client):
    """
    Given 无任何 AI 设置（默认 provider=deepseek，无 key）
    When  build_ai_client
    Then  返回空 key 的 AiClient（降级判断由调用方 _new_ai 承担，不在构建层）
    """
    with session_factory() as s:
        ai = build_ai_client(s)
    assert isinstance(ai, AiClient)
    assert ai.provider == "deepseek" and ai.api_key == ""


def test_build_ai_client_deepseek_with_key(client):
    """
    Given provider=deepseek + api_key
    When  build_ai_client
    Then  返回 AiClient（deepseek-chat 模型）
    """
    with session_factory() as s:
        _set(s, "ai.provider", "deepseek")
        _set(s, "ai.api_key", "sk-test")
        ai = build_ai_client(s)
    assert isinstance(ai, AiClient)
    assert ai.model == "deepseek-chat" and ai.provider == "deepseek"


def test_build_ai_client_ollama_default_model(client):
    """
    Given provider=ollama
    When  build_ai_client
    Then  默认模型 qwen2.5:7b（本地推理）
    """
    with session_factory() as s:
        _set(s, "ai.provider", "ollama")
        _set(s, "ai.api_key", "")
        ai = build_ai_client(s)
    assert ai is not None and ai.model == "qwen2.5:7b"


def test_build_ai_client_mindvault_bridge(client):
    """
    Given provider=mindvault（无需 api_key，读 mv.base_url / mindvault.password）
    When  build_ai_client
    Then  返回桥客户端，指向 MindVault 公网实例
    """
    with session_factory() as s:
        _set(s, "ai.provider", "mindvault")
        _set(s, "mv.base_url", "http://mv-stub")
        _set(s, "mindvault.password", "pw")
        ai = build_ai_client(s)
    assert ai is not None and ai.provider == "mindvault" and ai.mv_base_url == "http://mv-stub"


@pytest.mark.anyio
async def test_chat_stream_http_error_raises(client, monkeypatch):
    """
    Given DeepSeek 流式端点返回 500
    When  chat_stream
    Then  抛 AiError（HTTP 非 200 明确报错，不静默）
    """
    client_ai = AiClient(provider="deepseek", api_key="k",
                         transport=httpx.MockTransport(lambda r: httpx.Response(500, text="boom")))

    class StubStreamCtx:
        def __init__(self, resp):
            self.resp = resp

        async def __aenter__(self):
            return self.resp

        async def __aexit__(self, *a):
            return False

    def fake_stream(self, method, url, **kw):
        return StubStreamCtx(httpx.Response(500, text="boom"))

    monkeypatch.setattr(httpx.AsyncClient, "stream", fake_stream)
    with pytest.raises(AiError):
        _ = [d async for d in client_ai.chat_stream("s", "u")]


@pytest.mark.anyio
async def test_chat_via_mindvault_requires_base_url():
    """
    Given provider=mindvault 但未配置 mv.base_url
    When  chat_stream
    Then  抛 AiError 明确提示
    """
    ai = AiClient(provider="mindvault", mv_base_url="")
    with pytest.raises(AiError, match="mv.base_url"):
        _ = [d async for d in ai.chat_stream("s", "u")]
