"""内容域：频道帖子 / 评论 / 点赞（信息结构图 ⑥ 内容社区·内容层）。

频道容器层复用 conversation 表（type='channel'），本模块只承载
"内容沉淀"：帖子、评论、点赞三张独立表——群聊的 message 表装不下
点赞数 / 评论数 / 置顶位，且帖子是非实时内容，与消息流解耦。

冗余计数字段（like_count / comment_count）随写操作原子增减，供热度排序。
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, DateTime6, utcnow


class Post(Base):
    """频道帖子。status：1 正常 / 0 已删除（软删，管理员可审计）。"""

    __tablename__ = "post"
    __table_args__ = (
        # 帖子列表按「频道 + 时间倒序」拉取；缺这两个索引，帖子攒多后翻页会明显变慢
        Index("ix_post_channel_created", "channel_id", "created_at"),
        # 置顶帖优先返回
        Index("ix_post_channel_pinned", "channel_id", "is_pinned"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("conversation.id"), nullable=False, index=True
    )
    author_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    images: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # 名片帖：被推荐用户的 id（非空即为"好友名片"帖，content 通常为空）
    card_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.id"), nullable=True
    )
    like_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    comment_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # 删除留痕：status 表达「是否已删除」，deleted_at 只记录删除时间，便于事后追溯
    deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime6, default=utcnow, nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )


class Comment(Base):
    """帖子评论。parent_id 为空是一级评论；指向一级评论则是二级回复（最多两级）。"""

    __tablename__ = "comment"
    __table_args__ = (
        # 帖子详情页按时间正序拉评论，同样是「外键 + 时间」两列
        Index("ix_comment_post_created", "post_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("post.id"), nullable=False, index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("comment.id"), nullable=True, index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    like_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # 删除留痕：同 Post
    deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime6, default=utcnow, nullable=False
    )


class Like(Base):
    """点赞：帖子和评论共用一张表，target_type 区分（1=帖子 / 2=评论）。

    唯一索引保证"一人一目标最多一赞"，重复点赞直接被数据库拒绝。
    """

    __tablename__ = "likes"
    __table_args__ = (
        UniqueConstraint("user_id", "target_type", "target_id", name="uq_user_target"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    target_type: Mapped[int] = mapped_column(Integer, nullable=False)
    target_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime6, default=utcnow, nullable=False
    )
