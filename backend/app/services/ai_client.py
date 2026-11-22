"""AI 客户端：OpenAI 兼容接口（DeepSeek/GLM 均兼容），provider/base_url/key 从 settings 读。"""
from __future__ import annotations

import httpx

from ..config import get_project_root
from ..database import SessionDep
from ..services import settings_service

# provider -> 默认 base_url（均为 OpenAI 兼容 chat/completions）
PROVIDER_BASE_URLS = {
    "deepseek": "https://api.deepseek.com/v1",
    "glm": "https://open.bigmodel.cn/api/paas/v4",
    "ollama": "http://127.0.0.1:11434/v1",
}

PROMPT_DIR = get_project_root() / "backend" / "app" / "ai_skills"


class AiError(Exception):
    """AI 调用失败（网络/HTTP/结构）。"""


class AiClient:
    def __init__(
        self,
        provider: str = "deepseek",
        api_key: str = "",
        base_url: str | None = None,
        model: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 120.0,
        mv_base_url: str | None = None,
        mv_password: str | None = None,
    ):
        self.provider = provider
        self.api_key = api_key
        self.base_url = (base_url or PROVIDER_BASE_URLS.get(provider, PROVIDER_BASE_URLS["deepseek"])).rstrip("/")
        self.model = model or ("qwen2.5:7b" if provider == "ollama" else "deepseek-chat")
        self.mv_base_url = (mv_base_url or "").rstrip("/")
        self.mv_password = mv_password
        self._transport = transport
        self._http = httpx.AsyncClient(transport=transport, timeout=timeout)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _chat_via_mindvault(self, system: str, user: str) -> str:
        """AI 桥：借 MindVault 公网实例已配置的 provider（/api/ai/write action=custom）。"""
        from .mindvault_client import MindVaultClient, MindVaultError

        mv = MindVaultClient(
            base_url=self.mv_base_url, password=self.mv_password, transport=self._transport
        )
        try:
            resp = await mv.request(
                "POST",
                "/api/ai/write",
                json={"action": "custom", "text": user, "instruction": system},
            )
        except MindVaultError as exc:
            raise AiError(f"MindVault AI 桥失败：{exc}") from exc
        if resp.status_code == 401:
            raise AiError("MindVault 鉴权失败（检查设置页 mindvault.password）")
        if resp.status_code != 200:
            raise AiError(f"MindVault AI 返回 HTTP {resp.status_code}：{resp.text[:200]}")
        data = resp.json()
        text = data.get("text") or data.get("result") or data.get("content") or ""
        if not text:
            raise AiError(f"MindVault AI 返回空内容：{str(data)[:200]}")
        return str(text)

    async def chat(self, system: str, user: str) -> str:
        """单轮补全；provider=mindvault 走 AI 桥，其余 OpenAI 兼容。结构化提取关闭思考模式。"""
        if self.provider == "mindvault":
            if not self.mv_base_url:
                raise AiError("provider=mindvault 但未配置 mv.base_url")
            return await self._chat_via_mindvault(system, user)
        payload: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
        }
        if self.provider == "deepseek":
            payload["reasoning_effort"] = "none"  # 结构化提取：关闭思维链降延迟省成本（422 实测枚举为 none/minimal/low/...）
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            resp = await self._http.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise AiError(f"AI 服务不可达：{exc}") from exc
        if resp.status_code != 200:
            raise AiError(f"AI 返回 HTTP {resp.status_code}：{resp.text[:200]}")
        try:
            choice = resp.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            raise AiError(f"AI 响应结构异常：{resp.text[:200]}") from exc
        return choice


def load_prompt(name: str) -> str:
    """加载 backend/app/ai_skills/<name>.md 提示词资产。"""
    path = PROMPT_DIR / f"{name}.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def build_ai_client(session: SessionDep) -> AiClient:
    """从 settings 构建 AI 客户端（key 加密存储）；provider=mindvault 复用 MindVault 已配置的 AI。"""
    provider = settings_service.get_value(session, "ai.provider") or "deepseek"
    key = settings_service.get_value(session, "ai.api_key") or ""
    base = settings_service.get_value(session, f"ai.{provider}.base_url") or None
    model = settings_service.get_value(session, f"ai.{provider}.model") or None
    mv_base = settings_service.get_value(session, "mv.base_url") or None
    mv_pwd = settings_service.get_value(session, "mindvault.password") or None
    return AiClient(provider=provider, api_key=key, base_url=base, model=model, mv_base_url=mv_base, mv_password=mv_pwd)
