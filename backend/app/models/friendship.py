"""关系域：好友关系表。"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class Friendship(Base):
    """好友关系：必须双向存两条，备注与分组属于持有者私有数据。"""

    __tablename__ = "friendship"
    __table_args__ = (UniqueConstraint("user_id", "friend_id", name="uq_user_friend"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    friend_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    remark: Mapped[str | None] = mapped_column(String(50), nullable=True)
    group_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_starred: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    request_message: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
