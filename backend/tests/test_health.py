def test_health_returns_ok(client):
    """
    Given CS2HQ 后端已启动
    When  GET /api/health
    Then  返回 status=ok 与版本号
    """
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "version" in body
