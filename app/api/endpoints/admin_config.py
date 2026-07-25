from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.runtime_config import (
    MAX_COOKIE_LENGTH,
    clear_douyin_cookie,
    get_douyin_cookie_status,
    is_access_password_configured,
    set_douyin_cookie,
    verify_access_password,
)


router = APIRouter()


class DouyinCookieUpdate(BaseModel):
    cookie: str = Field(min_length=1, max_length=MAX_COOKIE_LENGTH)


def require_admin_password(
    x_admin_password: Optional[str] = Header(default=None, alias="X-Admin-Password"),
) -> None:
    if not is_access_password_configured():
        raise HTTPException(
            status_code=503,
            detail="Web access password is not configured.",
        )
    if not verify_access_password(x_admin_password):
        raise HTTPException(
            status_code=401,
            detail="Invalid admin password.",
        )


@router.get(
    "/douyin-cookie",
    dependencies=[Depends(require_admin_password)],
    summary="查看抖音 Cookie 配置状态/Get Douyin Cookie status",
)
def get_cookie_status():
    return get_douyin_cookie_status()


@router.put(
    "/douyin-cookie",
    dependencies=[Depends(require_admin_password)],
    summary="更新抖音 Cookie/Update Douyin Cookie",
)
def update_cookie(payload: DouyinCookieUpdate):
    try:
        return set_douyin_cookie(payload.cookie)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete(
    "/douyin-cookie",
    dependencies=[Depends(require_admin_password)],
    summary="清除网页配置的抖音 Cookie/Clear runtime Douyin Cookie",
)
def delete_cookie():
    return clear_douyin_cookie()
