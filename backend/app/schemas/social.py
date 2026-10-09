"""关系与会话域 schema：好友 / 成员 / 消息。"""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict

from app.schemas.auth import UserOut  # noqa: F401  （保持旧导入路径可用）


class UserBriefOut(BaseModel):
    """用户简要资料：加好友检索结果、名片、资料卡、申请列表共用。

    字段刻意最小化（不含 bio、is_admin、is_active 等），
    避免"顺手多带几个字段"把不必要的信息暴露给其他用户。
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    nickname: str
    student_id: str | None = None
    avatar_url: str | None = None
    department: str | None = None
    class_name: str | None = None


class CardUserOut(BaseModel):
    """名片消息里的被推荐用户：只给展示所需的头像与昵称。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    nickname: str
    avatar_url: str | None = None


class FriendOut(BaseModel):
    """好友列表项：对方公开资料 + **只有我可见**的备注 / 分组 / 特别关注。

    ``remark`` / ``group_name`` / ``is_starred`` 取自"我持有"的那条 friendship
    记录，因此绝不会出现在对方的好友列表里（这是好友关系必须存双向两条的原因）。
    返回时由接口排序：特别关注置顶，其余按昵称。
    """

    model_config = ConfigDict(from_attributes=True)

    friend_user_id: int
    username: str
    nickname: str
    avatar_url: str | None = None
    department: str | None = None
    class_name: str | None = None
    remark: str | None = None
    group_name: str | None = None
    is_starred: bool = False


class RequestOut(BaseModel):
    """好友申请项：收到的（box=received）与发出的（box=sent）两个方向共用。

    ``user`` 是"对方"——收到的申请里是申请人，发出的申请里是被申请人，
    由接口按 box 决定取哪一侧，前端无需再判断方向。
    """

    model_config = ConfigDict(from_attributes=True)

    request_id: int
    user: UserBriefOut | None = None
    request_message: str | None = None
    # pending / accepted / rejected：发起方需要看到对方处理的结果
    status: str = "pending"
    created_at: dt.datetime
    updated_at: dt.datetime | None = None


class MemberOut(BaseModel):
    """会话成员项：成员侧栏展示用。

    ``role``（owner / admin / member）决定前端是否显示"移除成员""历史可见性"
    等管理入口；真正的权限判定仍在服务端，前端只是体验层。
    """

    model_config = ConfigDict(from_attributes=True)

    user_id: int
    nickname: str
    avatar_url: str | None = None
    role: str
    joined_at: dt.datetime


class ConversationBriefOut(BaseModel):
    """群聊简要信息（加群申请列表里展示目标群）。"""

    model_config = ConfigDict(from_attributes=True)

    conversation_id: int
    name: str | None = None
    avatar_url: str | None = None


class GroupPreviewOut(BaseModel):
    """按群号搜索到的群公开信息（加群前预览，不要求是群成员）。"""

    model_config = ConfigDict(from_attributes=True)

    conversation_id: int
    name: str | None = None
    avatar_url: str | None = None
    description: str | None = None
    member_count: int = 0
    owner_name: str | None = None
    joined: bool = False
    my_request_status: str | None = None


class GroupRequestOut(BaseModel):
    """加群申请：发起方看到自己申请的结果，群主看到待处理的申请。"""

    model_config = ConfigDict(from_attributes=True)

    request_id: int
    conversation: ConversationBriefOut
    user: UserBriefOut | None = None
    message: str | None = None
    status: str = "pending"
    created_at: dt.datetime
    updated_at: dt.datetime | None = None


class MessageOut(BaseModel):
    """历史消息项（``GET /api/conversations/{id}/messages``）。

    与 WS 帧的 ``services/message_service.message_payload`` 字段保持一致，
    改动其一务必同步另一处，否则"刷新看到的消息"和"实时收到的消息"会不一致。
    已撤回消息由接口把 ``content`` 置空，原文不返回。
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int
    sender_id: int
    sender_nickname: str = ""
    sender_avatar_url: str | None = None
    msg_type: str
    sender_type: str
    content: str
    file_name: str | None = None
    file_size: int | None = None
    reply_to_id: int | None = None
    recalled_at: dt.datetime | None = None
    is_pinned: bool = False
    # 被 @ 的用户 id 列表（后端解析写入，与 message_payload 同源）
    mentions: list[int] = []
    created_at: dt.datetime
    # 名片消息的被推荐用户（msg_type=card 时才有）
    card_user: CardUserOut | None = None
