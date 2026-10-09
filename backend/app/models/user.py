"""身份域：用户表。"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class User(Base):
    """用户表：普通学生、管理员、机器人与系统账号共用一张表。

    三类特殊身份靠布尔字段区分，不额外建角色表（避免权限判定逻辑分散）：

    - ``is_admin``：管理端权限，由 ``deps.require_admin`` 校验；
    - ``is_bot``：机器人账号，不可登录、不可被加好友、不可被封禁；
    - ``is_active``：为假即已禁用，需登录 / 鉴权 / WS 握手三处同时拦截。

    ``username`` 是登录凭据兼**唯一可检索标识**（昵称与学号不可被检索）；
    ``student_id`` 是校园实名载体，不允许用户自助修改，只能经审核写入。
    """

    __tablename__ = "user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 学号：可空是因为机器人账号没有学号；全局唯一，重复注册即拒绝
    student_id: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True)
    # 登录名，同时是"按用户名精确检索"的唯一通道
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    nickname: Mapped[str] = mapped_column(String(50), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bio: Mapped[str | None] = mapped_column(String(200), nullable=True)
    department: Mapped[str | None] = mapped_column(String(100), nullable=True)
    class_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # 机器人标记：不可登录、不可被加好友 / 被推荐为名片、不可被封禁
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # 管理员标记：能否进入管理端、能否调用 /api/admin（真正的边界在 deps.require_admin）
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # 账号可用性：为假即"已禁用"。禁用需三处同时拦截（登录 / 鉴权 / WS 握手），
    # 否则会出现"禁用后仍能用旧令牌继续收发消息"的漏洞。禁用留痕便于追责。
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    disabled_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    disabled_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    last_seen_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    # 学号变更留痕：学号是后台实名的载体，不允许用户自助修改，
    # 只能经 F4 审核通过后写入，并记录审核人与时间，便于追责。
    student_id_updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    student_id_updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
