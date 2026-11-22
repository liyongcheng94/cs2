"""完美平台登录与状态 API：三步短信登录（滑块由用户在前端完成）+ 登录态查询。

send-code 会给真实手机号发短信——仅由面板用户主动点击触发，无定时/重试逻辑。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..database import SessionDep
from ..services import settings_service
from ..services.wanmei import PassportClient, WanmeiAuthError, WanmeiError

router = APIRouter(prefix="/wanmei", tags=["wanmei"])


def _new_passport() -> PassportClient:
    return PassportClient()


class SendCodeBody(BaseModel):
    mobile_phone: str
    sec_code: str
    cap_ticket: str


class SmsLoginBody(BaseModel):
    mobile_phone: str
    security_code: str


@router.post("/captcha-init")
async def captcha_init() -> dict:
    try:
        client = _new_passport()
        return await client.captcha_init()
    except WanmeiAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except WanmeiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/send-code")
async def send_code(body: SendCodeBody) -> dict:
    try:
        client = _new_passport()
        await client.send_code(body.mobile_phone, body.sec_code, body.cap_ticket)
        return {"sent": True}
    except WanmeiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/sms-login")
async def sms_login(body: SmsLoginBody, session: SessionDep) -> dict:
    try:
        client = _new_passport()
        out = await client.sms_login(body.mobile_phone, body.security_code)
    except WanmeiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    settings_service.set_value(session, "wanmei.access_token", out["token"])
    settings_service.set_value(session, "wanmei.steam_id", str(out["steam_id"]))
    settings_service.set_value(session, "wanmei.user_id", str(out["user_id"] or ""))
    settings_service.set_value(session, "wanmei.phone", out["mobile_phone"])
    return {"steam_id": str(out["steam_id"]), "user_id": out["user_id"]}


@router.get("/status")
def login_status(session: SessionDep) -> dict:
    detail = settings_service.get_detail(session)
    token = detail.get("wanmei.access_token") or ""
    steam_id = detail.get("wanmei.steam_id") or ""
    return {
        "logged_in": bool(token and steam_id),
        "steam_id": steam_id or None,
        "phone": detail.get("wanmei.phone") or None,
    }
