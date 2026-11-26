"""场景：API Key 等机密设置绝不以明文出现在任何 API 响应中。

Given ai.api_key 属于机密键
When 保存并读取设置（列表/detail）
Then 库内加密、所有对外响应均为脱敏掩码
"""
from fastapi.testclient import TestClient


def _setup(client: TestClient):
    r = client.put("/api/settings", json={"ai.api_key": "sk-secret1234567890"})
    assert r.status_code == 200
    return r.json()


def test_api_key_is_secret_and_masked_everywhere(client: TestClient):
    # Given/When：保存机密 key
    masked = _setup(client)
    # Then：列表脱敏
    assert masked["ai.api_key"].startswith("****")
    assert "sk-secret" not in masked["ai.api_key"]
    # Then：detail 也脱敏（曾经明文回显，属泄露面）
    detail = client.get("/api/settings/detail").json()
    assert detail["ai.api_key"].startswith("****")
    assert "sk-secret" not in detail["ai.api_key"]
