"""会话域：会话表与会话成员表。

Conversation 是"统一会话抽象"的落点——私聊 / 群聊 / 频道三态合一，
差异全部集中在 type 与少量配置字段上，收发消息等逻辑完全复用。
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, DateTime6, utcnow


class Conversation(Base):
    """私聊 / 群聊 / 频道三态合一，靠 type 区分。"""

    __tablename__ = "conversation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"), nullable=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # 新成员能看多少历史：all / since_join / recent_n；仅 group 生效，
    # channel 与 single 恒为 all（接口对非群聊直接拒绝设置，避免"设了不生效"）
    history_visible_mode: Mapped[str] = mapped_column(
        String(20), default="all", nullable=False
    )
    # 仅 mode=recent_n 时生效：条数存在字段里而非写死在枚举中，便于调参
    history_limit: Mapped[int | None] = mapped_column(Integer, default=20, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class ConversationMember(Base):
    """会话成员：私聊 / 群聊 / 频道共用一张成员表。

    一张表同时承担三件事，改动时注意别破坏其中任何一项：

    - ``role``（owner / admin / member）决定谁能改名、移除成员、审批加群；
    - ``joined_at`` 是群聊"仅可见加入后历史"（since_join）的判断依据；
    - ``last_read_message_id`` 用于未读红点，统计"我还有多少条没看"，
      **与已读回执无关**（本系统不做已读回执）。
    """

    __tablename__ = "conversation_member"
    __table_args__ = (
        UniqueConstraint("conversation_id", "user_id", name="uq_conv_user"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversation.id"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="member", nullable=False)
    joined_at: Mapped[dt.datetime] = mapped_column(
        DateTime6, default=utcnow, nullable=False
    )
    last_read_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_muted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
