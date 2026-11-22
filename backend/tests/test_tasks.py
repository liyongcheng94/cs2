import pytest

from app.services.task_manager import WanmeiAuthError


@pytest.fixture()
def register_dummy_handler():
    from app.services import task_manager

    async def ok_handler(task, session_factory):
        return {"done": True, "echo": task.payload["echo"]}

    async def auth_fail_handler(task, session_factory):
        raise WanmeiAuthError("token 失效")

    task_manager.HANDLERS["dummy_ok"] = ok_handler
    task_manager.HANDLERS["dummy_auth_fail"] = auth_fail_handler
    yield
    task_manager.HANDLERS.pop("dummy_ok", None)
    task_manager.HANDLERS.pop("dummy_auth_fail", None)


def test_create_and_list_task(client, register_dummy_handler):
    """
    Given 新建一个任务
    When  GET /api/tasks
    Then  任务存在且初始状态 pending，payload 原样保存
    """
    resp = client.post(
        "/api/tasks", json={"type": "dummy_ok", "payload": {"echo": "hi"}, "priority": 3}
    )
    assert resp.status_code == 202
    task_id = resp.json()["id"]

    listed = client.get("/api/tasks").json()
    target = next(t for t in listed if t["id"] == task_id)
    assert target["status"] == "pending"
    assert target["payload"]["echo"] == "hi"
    assert target["priority"] == 3


def test_run_task_success(client, register_dummy_handler):
    """
    Given 一个注册了成功 handler 的任务
    When  POST /api/tasks/{id}/run
    Then  状态变 success，result 含 handler 返回值
    """
    task_id = client.post(
        "/api/tasks", json={"type": "dummy_ok", "payload": {"echo": "x"}}
    ).json()["id"]
    resp = client.post(f"/api/tasks/{task_id}/run")
    assert resp.status_code == 200
    body = client.get(f"/api/tasks/{task_id}").json()
    assert body["status"] == "success"
    assert body["result"]["echo"] == "x"


def test_run_task_auth_failure_breaks_to_need_auth(client, register_dummy_handler):
    """
    Given handler 抛 WanmeiAuthError（完美平台 401/403 熔断场景）
    When  POST /api/tasks/{id}/run
    Then  状态为 NEED_AUTH 而非 failed，error 含人话原因
    """
    task_id = client.post("/api/tasks", json={"type": "dummy_auth_fail"}).json()["id"]
    client.post(f"/api/tasks/{task_id}/run")
    body = client.get(f"/api/tasks/{task_id}").json()
    assert body["status"] == "NEED_AUTH"
    assert "token" in body["error"]


def test_unknown_task_type_400(client):
    """
    Given 未注册的 task 类型
    When  POST /api/tasks
    Then  返回 400（禁止创建必然无处执行的任务）
    """
    resp = client.post("/api/tasks", json={"type": "no_such_type"})
    assert resp.status_code == 400
