"""消息域：消息表。"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, DateTime6, utcnow


class Message(Base):
    """消息表：人类消息与机器人消息共用，私聊 / 群聊 / 频道同构。

    - ``content`` 的语义随 ``msg_type`` 变化：文本与表情存原文，
      图片与文件存上传接口返回的 ``/uploads/...`` URL，名片存被推荐用户 id；
    - ``sender_type`` 让机器人以"非人类发送者"身份接入同一条消息链路；
    - ``recalled_at`` 是**撤回标记而非删除**，原文保留以便审计；
      未读统计必须排除已撤回消息，否则会出现"有 1 条未读但点进去什么都没有"；
    - ``is_pinned`` 仅频道使用（话题帖），由接口保证同时至多一条为真。

    写入的唯一合法入口是 ``services/message_service.save_and_push``。
    """

    __tablename__ = "message"
    __table_args__ = (
        # 历史拉取与分页全靠它，缺失会导致群内消息多了以后翻页卡顿
        Index("ix_message_conv_created", "conversation_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversation.id"), nullable=False
    )
    sender_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    # text / emoji / image / file / card（白名单校验在 routers/ws.py）
    msg_type: Mapped[str] = mapped_column(String(20), default="text", nullable=False)
    # user / bot —— 机器人与后续 AI 消息的接入标识
    sender_type: Mapped[str] = mapped_column(String(20), default="user", nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reply_to_id: Mapped[int | None] = mapped_column(
        ForeignKey("message.id"), nullable=True
    )
    recalled_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # @我：存被 @ 用户 id 的 JSON 数组文本（如 "[2, 9]"），NULL 表示没 @ 任何人。
    # 只有 msg_type=text 才会解析写入，由 save_and_push 统一生成
    mentions: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime6, default=utcnow, nullable=False
    )
