"""身份域：注册、登录、查看与修改个人资料、管理员学号变更。"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import create_access_token, hash_password, verify_password
from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas import (
    ChangePasswordIn,
    LoginIn,
    ProfileUpdateIn,
    RegisterIn,
    TokenOut,
    UserOut,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


# 常见弱密码黑名单：命中即拒绝，避免"用户名+123456"这类一眼可猜的密码。
# 注册（register）与改密（change_password）共用同一份，保证两处口径一致。
WEAK_PASSWORDS = {
    "123456", "1234567", "12345678", "123456789", "111111", "000000",
    "password", "abc123", "a123456", "qwerty", "iloveyou",
}


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterIn, db: AsyncSession = Depends(get_db)):
    """注册新账号。

    校验顺序（全部以服务端判定为准，前端提示只是体验）：
    协议已勾选 → 邀请码（``INVITE_CODE`` 非空时才校验）→ 两次密码一致 →
    密码不等于用户名 / 学号 → 不在弱密码黑名单 → 用户名唯一 → 学号唯一。

    返回:
        201 + ``UserOut``；**任何响应都不含密码字段**，库里存的是 bcrypt 哈希。
    """
    if not body.agree_terms:
        raise HTTPException(status_code=400, detail="请先阅读并同意用户协议")

    # 准入强制开关：INVITE_CODE 非空时校验邀请码；留空 = 开放注册。
    # 本地无法验证学号真伪，开启时用邀请码把注册面收窄到"被允许的人"。
    if settings.invite_code and body.invite_code != settings.invite_code:
        raise HTTPException(status_code=403, detail="邀请码无效，请向管理员获取")

    # 两次输入一致：前端提示只是体验，后端校验才算数
    if body.password != body.confirm_password:
        raise HTTPException(status_code=400, detail="两次输入的密码不一致")

    # 弱密码：不得与本人用户名 / 学号相同，也不得是常见弱密码
    if body.password == body.username:
        raise HTTPException(status_code=400, detail="密码不能与用户名相同")
    if body.student_id and body.password == body.student_id:
        raise HTTPException(status_code=400, detail="密码不能与学号相同")
    if body.password.lower() in WEAK_PASSWORDS:
        raise HTTPException(status_code=400, detail="密码过于简单，请更换")

    # 唯一性：用户名与学号全局唯一，重复即拒绝
    if await db.scalar(select(User).where(User.username == body.username)):
        raise HTTPException(status_code=400, detail="该用户名已被注册")

    if body.student_id and await db.scalar(
        select(User).where(User.student_id == body.student_id)
    ):
        raise HTTPException(status_code=400, detail="该学号已注册")

    user = User(
        username=body.username,
        password_hash=hash_password(body.password),  # 绝不存明文
        nickname=body.nickname,
        student_id=body.student_id,
        department=body.department,
        class_name=body.class_name,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return UserOut.model_validate(user)


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, db: AsyncSession = Depends(get_db)):
    """普通登录：校验凭据后签发令牌。

    与 ``/admin-login`` 的区别是**不要求管理员身份**——管理员用同一入口登录后
    仍可正常使用用户端，管理入口在个人资料页（见 frontend 的「我的」分区）。
    """
    user = await db.scalar(select(User).where(User.username == body.username))
    # 用户名不存在与密码错误返回同一句提示，避免账号枚举
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=400, detail="用户名或密码错误")

    # 机器人账号只能作为消息发送者存在（见 services/bot_service.py）。
    # 它身上带密码哈希只是为了满足 user 表结构，不等于它是一个可以登录的账号：
    # 不拦这一下，知道初始化脚本里那个占位密码的人就能登进去冒充机器人发言。
    if user.is_bot:
        raise HTTPException(status_code=403, detail="机器人账号无法登录")

    # 账号禁用第一处生效点：凭据正确也拒绝登录（另两处在 deps.py 与 ws.py）
    if not user.is_active:
        raise HTTPException(status_code=403, detail="该账号已被禁用，请联系管理员")

    return TokenOut(
        access_token=create_access_token(user.id),
        user_id=user.id,
        nickname=user.nickname,
        is_admin=user.is_admin,
    )


@router.post("/admin-login", response_model=TokenOut)
async def admin_login(body: LoginIn, db: AsyncSession = Depends(get_db)):
    """管理端独立登录入口（设计 2.3.9）。

    与普通登录分开：密码正确但账号无管理员权限时，服务端直接拒绝且**不签发令牌**。
    前端隐藏入口与路由守卫都只是体验层，这里才是真正的访问控制。
    """
    user = await db.scalar(select(User).where(User.username == body.username))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=400, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="该账号已被禁用")
    if user.is_bot:
        raise HTTPException(status_code=403, detail="机器人账号无法登录")
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="该账号无管理员权限")

    return TokenOut(
        access_token=create_access_token(user.id),
        user_id=user.id,
        nickname=user.nickname,
        is_admin=user.is_admin,
    )


@router.get("/me", response_model=UserOut)
async def me(current: User = Depends(get_current_user)):
    """当前登录用户资料。

    前端进入布局骨架时调用一次，用于渲染顶栏昵称 / 头像、
    以及决定「我的」分区是否显示"进入管理后台"入口（依赖 is_admin）。
    """
    return UserOut.model_validate(current)


@router.put("/me", response_model=UserOut)
async def update_me(
    body: ProfileUpdateIn,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """部分更新个人资料：只覆盖显式传入（非 None）的字段。

    可改字段里没有学号与用户名——学号必须走 F4 审核通道（routers/verifications.py），
    用户名是登录凭据兼检索标识，注册后不可修改。
    """
    for field in ("nickname", "bio", "avatar_url", "department", "class_name"):
        value = getattr(body, field)
        if value is not None:
            setattr(current, field, value)
    await db.commit()
    await db.refresh(current)
    return UserOut.model_validate(current)


@router.post("/me/password")
async def change_password(
    body: ChangePasswordIn,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """用户自助修改密码。

    新密码同样过一遍弱密码黑名单——注册时的强度要求改密时同样适用；
    旧密码错误不提示"账号不存在"之类信息，避免给攻击者额外线索。
    """
    if not verify_password(body.old_password, current.password_hash):
        raise HTTPException(status_code=400, detail="原密码不正确")
    if body.new_password != body.confirm_password:
        raise HTTPException(status_code=400, detail="两次输入的新密码不一致")
    if body.new_password == body.old_password:
        raise HTTPException(status_code=400, detail="新密码不能与原密码相同")
    if body.new_password.lower() in WEAK_PASSWORDS:
        raise HTTPException(status_code=400, detail="密码过于简单，请更换")

    current.password_hash = hash_password(body.new_password)
    await db.commit()
    return {"ok": True}


@router.post("/logout")
async def logout(
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """退出登录：记录最后在线时间。

    JWT 是无状态的，服务端不维护会话白名单，因此"令牌失效"由前端清除本地
    令牌完成（设计 2.2.3）；在线连接在该 WebSocket 断开时由连接管理器移除。
    本端点存在的意义是留下最后在线时间，供演示与排查使用。
    """
    current.last_seen_at = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    await db.commit()
    return {"ok": True}
