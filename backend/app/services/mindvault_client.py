"""MindVault 客户端：MCP create_note（新建）+ REST PUT（更新）双通道，带密码登录与 401 重登一次。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
from loguru import logger


class MindVaultError(Exception):
    """MindVault 不可达 / 协议错误 / 工具执行失败。"""


class MindVaultClient:
    def __init__(
        self,
        base_url: str,
        password: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 10.0,
    ):
        self.base_url = base_url.rstrip("/")
        self._password = password
        self._token: str | None = None
        self._http = httpx.AsyncClient(
            base_url=self.base_url, transport=transport, timeout=timeout
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    # ---------- 鉴权 ----------

    async def _login(self) -> None:
        try:
            resp = await self._http.post("/api/auth/login", json={"password": self._password})
        except httpx.HTTPError as exc:
            raise MindVaultError(f"MindVault 登录失败：{exc}") from exc
        if resp.status_code != 200:
            raise MindVaultError(f"MindVault 登录失败：HTTP {resp.status_code}")
        token = resp.cookies.get("mv_session") or ""
        if not token:
            raise MindVaultError("登录成功但未取得会话令牌（mv_session 缺失）")
        self._token = token

    async def _auth_headers(self) -> dict[str, str]:
        if self._token is None:
            await self._login()
        return {"Authorization": f"Bearer {self._token}"}

    async def request(self, method: str, url: str, **kw: Any) -> httpx.Response:
        """带鉴权请求；401 时重登一次重试（仅一次，防循环）。method 大小写不敏感。"""
        verb = method.lower()
        headers = kw.pop("headers", None) or {}
        if self._password:
            headers = {**headers, **(await self._auth_headers())}
        try:
            resp = await getattr(self._http, verb)(url, headers=headers, **kw)
        except httpx.HTTPError as exc:
            raise MindVaultError(f"MindVault 不可达：{exc}") from exc
        if resp.status_code == 401 and self._password:
            self._token = None
            headers = {**headers, **(await self._auth_headers())}
            try:
                resp = await getattr(self._http, verb)(url, headers=headers, **kw)
            except httpx.HTTPError as exc:
                raise MindVaultError(f"MindVault 不可达：{exc}") from exc
        return resp

    # ---------- 主题 ----------

    async def ensure_topic(self, name: str) -> int:
        resp = await self.request("GET", "/api/topics")
        if resp.status_code != 200:
            raise MindVaultError(f"读取主题树失败：HTTP {resp.status_code}")
        stack = list(resp.json())
        while stack:
            node = stack.pop()
            if node.get("name") == name:
                return int(node["id"])
            stack.extend(node.get("children") or [])
        created = await self.request("POST", "/api/topics", json={"name": name})
        if created.status_code not in (200, 201):
            raise MindVaultError(f"创建主题失败：HTTP {created.status_code} {created.text[:200]}")
        logger.info(f"[MindVault] 新建主题 {name} -> id={created.json().get('id')}")
        return int(created.json()["id"])

    # ---------- MCP ----------

    async def _mcp_call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        resp = await self.request("POST", "/api/mcp", json=payload)
        if resp.status_code == 401:
            raise MindVaultError(f"MindVault 鉴权失败（HTTP 401），检查 mindvault.password")
        if resp.status_code != 200:
            raise MindVaultError(f"MCP 调用失败：HTTP {resp.status_code} {resp.text[:200]}")
        data = resp.json()
        result = data.get("result") or {}
        content = result.get("content") or []
        if result.get("isError"):
            text = content[0].get("text", "未知工具错误") if content else "未知工具错误"
            raise MindVaultError(f"MCP 工具错误：{text}")
        if not content:
            raise MindVaultError("MCP 返回内容为空")
        return json.loads(content[0]["text"])

    # ---------- 高层操作 ----------

    async def push_note(
        self, title: str, content: str, topic_name: str | None = None, topic_id: int | None = None
    ) -> dict[str, Any]:
        """新建笔记（MCP create_note）；返回 {uuid, item_id, title, topic_id}。"""
        if topic_id is None:
            topic_id = await self.ensure_topic(topic_name or "CS2HQ")
        out = await self._mcp_call(
            "create_note", {"title": title, "content": content, "topic_id": topic_id}
        )
        logger.info(f"[MindVault] create_note uuid={out.get('uuid')} title={title!r}")
        return {
            "uuid": out["uuid"],
            "item_id": out.get("item_id"),
            "title": out.get("title"),
            "topic_id": topic_id,
        }

    async def update_note(
        self, uuid: str, content: str | None = None, title: str | None = None
    ) -> dict[str, Any]:
        """更新已有条目（REST PUT；MCP 无 update 工具）。"""
        body: dict[str, Any] = {}
        if content is not None:
            body["content"] = content
        if title is not None:
            body["title"] = title
        resp = await self.request("PUT", f"/api/items/{uuid}", json=body)
        if resp.status_code != 200:
            raise MindVaultError(f"更新条目失败：HTTP {resp.status_code} {resp.text[:200]}")
        logger.info(f"[MindVault] update_note uuid={uuid}")
        return resp.json()

    async def health(self) -> dict[str, Any]:
        resp = await self.request("GET", "/api/health")
        resp.raise_for_status()
        return resp.json()

    async def capture_video(self, path: str, title: str, preset: str = "raw") -> dict[str, Any]:
        """上传视频文件到 MindVault /api/capture/videos（≤20MB，{source_hash}_{preset_hash} 寻址）。"""
        with open(path, "rb") as f:
            files = {"file": (Path(path).name, f, "video/mp4")}
            data = {"title": title, "preset": preset}
            resp = await self.request("POST", "/api/capture/videos", files=files, data=data)
        if resp.status_code not in (200, 201):
            raise MindVaultError(f"视频捕获失败：HTTP {resp.status_code} {resp.text[:200]}")
        logger.info(f"[MindVault] capture_video {Path(path).name} preset={preset}")
        return resp.json()
