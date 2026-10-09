"""治理域：举报表、学号变更申请表与敏感词库表。"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class Report(Base):
    """举报记录：内容治理的事后防线。"""

    __tablename__ = "report"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    reporter_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    message_id: Mapped[int] = mapped_column(ForeignKey("message.id"), nullable=False)
    reason: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    handled_by: Mapped[int | None] = mapped_column(ForeignKey("user.id"), nullable=True)
    handled_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class SensitiveWord(Base):
    """敏感词库：词表从文件（sensitive_words.txt）搬进数据库（10-02）。

    动机：文件词库改一个词要重启服务，管理员没有可用的维护入口。
    本表是**唯一权威源**；启动时若表为空，从旧文件导入作为种子。
    进程内仍缓存前缀树（core/sensitive.py），增删后经总线控制帧让
    全部实例重建缓存，无需重启。
    """

    __tablename__ = "sensitive_word"
    __table_args__ = (UniqueConstraint("word", name="uq_sensitive_word"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    word: Mapped[str] = mapped_column(String(50), nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("user.id"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class StudentIdRequest(Base):
    """学号变更申请：用户提交证明材料 → 管理员审核 → 通过后写入新学号。

    存在的理由：学号是"后台实名"的载体，不能让用户自助修改；
    但真实场景确实存在转专业、留级、教务录入错误等情况，
    因此需要一条"有证据、有审核、有留痕"的变更通道。
    """

    __tablename__ = "student_id_request"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    old_student_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    new_student_id: Mapped[str] = mapped_column(String(32), nullable=False)
    # 证明材料存于私密目录，字段只存文件名；读取必须走管理员鉴权接口
    proof_file: Mapped[str] = mapped_column(String(255), nullable=False)
    user_note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), default="pending", nullable=False
    )  # pending / approved / rejected
    reviewer_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    review_note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
