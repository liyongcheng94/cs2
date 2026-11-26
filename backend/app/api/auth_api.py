"""认证路由：注册 / 登录 / 登出 / me（JWT httpOnly cookie）。"""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlmodel import Session

from ..database import get_session
from ..models import User
from ..services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


class Credentials(BaseModel):
    username: str
    password: str


def get_current_user(request: Request, session: Annotated[Session, Depends(get_session)]) -> User:
    token = request.cookies.get(auth_service.COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    user_id = auth_service.decode_user_id(token)
    if user_id is None:
        raise HTTPException(status_code=401, detail="登录已失效")
    user = auth_service.get_by_id(session, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="用户不存在")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def _auth_cookie_response(user: User, token: str) -> JSONResponse:
    resp = JSONResponse({"id": user.id, "username": user.username, "display_name": user.display_name, "is_admin": user.is_admin})
    resp.set_cookie(
        auth_service.COOKIE_NAME,
        token,
        max_age=30 * 24 * 3600,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return resp


@router.post("/register")
def register(body: Credentials, session: Annotated[Session, Depends(get_session)]) -> JSONResponse:
    if not body.username.strip() or not body.password:
        raise HTTPException(status_code=422, detail="用户名与密码必填")
    if auth_service.get_by_username(session, body.username.strip()) is not None:
        raise HTTPException(status_code=409, detail="用户名已存在")
    user = auth_service.create_user(session, body.username.strip(), body.password)
    return _auth_cookie_response(user, auth_service.create_token(user.id))


@router.post("/login")
def login(body: Credentials, session: Annotated[Session, Depends(get_session)]) -> JSONResponse:
    user = auth_service.get_by_username(session, body.username.strip())
    if user is None or not auth_service.verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return _auth_cookie_response(user, auth_service.create_token(user.id))


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(auth_service.COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: CurrentUser) -> dict:
    return {"id": user.id, "username": user.username, "display_name": user.display_name, "is_admin": user.is_admin}


# 供业务路由隔离查询用
def visible_user_ids(user: User) -> Optional[set[int]]:
    """当前用户可见数据的 user_id 集合语义：
    - admin：全部（含 legacy None）
    - 普通用户：仅自己的 user_id
    """
    return None if user.is_admin else {user.id}  # type: ignore[return-value]
