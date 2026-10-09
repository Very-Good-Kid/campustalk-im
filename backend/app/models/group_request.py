"""群聊加入申请域：申请加群 → 群主 / 管理员审批。

与好友申请同构（status：pending / accepted / rejected），但作用于会话域：
一条申请记录挂在「目标群 + 申请人」上，(conversation_id, user_id) 唯一，
被拒绝后允许复用同一条记录重新申请，避免刷表。

为什么单独建表而不复用 message / conversation_member：
申请是"待处理事项"，需要保留审批结果供双方回看，成员表只能表达"是否在群里"。
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class GroupJoinRequest(Base):
    """加群申请。status：pending 待审批 / accepted 已同意 / rejected 已拒绝。"""

    __tablename__ = "group_join_request"
    __table_args__ = (
        UniqueConstraint("conversation_id", "user_id", name="uq_group_join_user"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversation.id"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("user.id"), nullable=False, index=True
    )
    message: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
