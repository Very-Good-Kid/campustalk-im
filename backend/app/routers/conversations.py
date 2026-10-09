"""会话域端点：会话列表（含未读红点）、建群、建频道、加入、成员管理。

历史拉取、已读、置顶、撤回等消息域接口见 messages.py；
成员校验等可复用逻辑见 services/conversation_service.py。

三种会话形态共用同一套模型，差异只有三处：加入方式、历史可见性、置顶话题帖。
"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models import (
    Conversation,
    ConversationMember,
    Friendship,
    GroupJoinRequest,
    Message,
    User,
)
from app.schemas import (
    ConversationBriefOut,
    GroupPreviewOut,
    GroupRequestOut,
    MemberOut,
    UserBriefOut,
)
from app.services.conversation_service import (
    assert_member as _assert_member,
)
from app.services.conversation_service import (
    get_or_create_single_conversation,
    require_owner_or_admin as _require_role,
)

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


# ---------- 请求/响应模型 ----------

class GroupCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    member_ids: list[int] = Field(min_length=1, description="初始成员，仅可从好友中选择")
    avatar_url: str | None = Field(default=None, max_length=255, description="上传接口返回的 /uploads/ URL")


class ChannelCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    avatar_url: str | None = Field(default=None, max_length=255, description="上传接口返回的 /uploads/ URL")


class ConversationUpdateIn(BaseModel):
    """群 / 频道信息修改。None = 不修改；description 传空串表示清空。"""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    avatar_url: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=500)


class InviteIn(BaseModel):
    user_id: int


class GroupJoinRequestIn(BaseModel):
    """申请加群：附言可选，供群主判断申请人身份。"""

    message: str | None = Field(default=None, max_length=200)


class GroupJoinActionIn(BaseModel):
    action: str  # accept / reject


class HistoryVisibilityIn(BaseModel):
    """群聊历史可见性：all / since_join / recent_n（三种模式互斥、不叠加）。"""

    mode: str = Field(pattern="^(all|since_join|recent_n)$")
    limit: int | None = Field(default=None, ge=1, le=500, description="仅 recent_n 时生效")


# ---------- 辅助（已上移 services/conversation_service.py，此处保留别名） ----------


# ---------- 会话列表 ----------

@router.get("")
async def conversation_list(
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """会话列表：私聊 / 群聊 / 频道混排，按最后一条消息时间倒序。

    每个条目独立计算（数据量小，优先可读性）：

    - 显示名：私聊取"我给对方的备注 → 对方昵称 → 自己的昵称（自我会话）"，
      群 / 频道取 ``conversation.name``；
    - 显示头像：私聊取对方头像，群 / 频道取 ``conversation.avatar_url``；
    - 未读数：``id > last_read_message_id`` 且非自己发、未撤回的消息条数；
    - 私聊若好友关系已被删除则整条跳过（记录仍在库里，表现为"删好友即会话消失"）。
    """
    my_members = (
        await db.execute(
            select(ConversationMember).where(ConversationMember.user_id == current.id)
        )
    ).scalars().all()

    out = []
    for member in my_members:
        conv = await db.get(Conversation, member.conversation_id)
        if conv is None:
            continue

        # 私聊会话：好友关系被删除后列表不再显示（记录保留在库）。
        # 自我会话（只有自己一个成员，给自己发消息）没有"对方"，不做这层过滤。
        other = None
        if conv.type == "single":
            other = (
                await db.execute(
                    select(ConversationMember.user_id).where(
                        ConversationMember.conversation_id == conv.id,
                        ConversationMember.user_id != current.id,
                    )
                )
            ).scalars().first()
            if other is not None:
                rel = await db.scalar(
                    select(Friendship).where(
                        Friendship.user_id == current.id,
                        Friendship.friend_id == other,
                        Friendship.status == "accepted",
                    )
                )
                if rel is None:
                    continue

        # 名称：私聊显示对方昵称或我给对方的备注；自我会话显示自己的昵称
        display_name = conv.name or ""
        other_user = None
        if conv.type == "single":
            if other is None:
                display_name = current.nickname
            else:
                other_user = await db.get(User, other)
                if other_user is not None:
                    rel_remark = await db.scalar(
                        select(Friendship.remark).where(
                            Friendship.user_id == current.id,
                            Friendship.friend_id == other_user.id,
                        )
                    )
                    display_name = rel_remark or other_user.nickname

        member_count = await db.scalar(
            select(func.count())
            .select_from(ConversationMember)
            .where(ConversationMember.conversation_id == conv.id)
        )

        # 未读红点：排除自己发的和已撤回的
        unread = await db.scalar(
            select(func.count())
            .select_from(Message)
            .where(
                Message.conversation_id == conv.id,
                Message.id > (member.last_read_message_id or 0),
                Message.sender_id != current.id,
                Message.recalled_at.is_(None),
            )
        )

        last = await db.scalar(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.id.desc())
            .limit(1)
        )

        # 撤回摘要要显示"某某某 撤回了一条消息"，所以带上最后一条的发送者昵称
        last_sender_name = ""
        if last is not None:
            last_sender = await db.get(User, last.sender_id)
            last_sender_name = last_sender.nickname if last_sender else ""

        # 私聊本身没有会话头像：列表头像取对方头像；自我会话取自己的头像
        if conv.type == "single":
            display_avatar = (
                other_user.avatar_url if other_user is not None else current.avatar_url
            )
        else:
            display_avatar = conv.avatar_url

        out.append(
            {
                "conversation_id": conv.id,
                "type": conv.type,
                "name": display_name,
                "avatar_url": display_avatar,
                "member_count": member_count,
                "unread": unread,
                "history_visible_mode": conv.history_visible_mode,
                "history_limit": conv.history_limit,
                "is_owner": conv.owner_id == current.id,
                "my_role": member.role,
                "is_pinned_post": bool(
                    last and last.is_pinned and conv.type == "channel"
                ),
                "last_message": (
                    {
                        "id": last.id,
                        "sender_id": last.sender_id,
                        "sender_nickname": last_sender_name,
                        "msg_type": last.msg_type,
                        "recalled": last.recalled_at is not None,
                        "preview": "" if last.recalled_at else (last.content or "")[:30],
                        "created_at": last.created_at.isoformat(),
                    }
                    if last
                    else None
                ),
            }
        )

    out.sort(
        key=lambda c: c["last_message"]["created_at"] if c["last_message"] else "",
        reverse=True,
    )
    return out


# ---------- 建群 / 建频道 / 加入 ----------

@router.post("/group", status_code=201)
async def create_group(
    body: GroupCreateIn,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """创建群聊：创建者自动成为 owner，其余初始成员只允许从好友中选。

    这里只负责"建群 + 落成员"，后续加人由邀请（invite_member）
    与加群申请审批（join-requests）两条通道承担。
    """
    # 初始成员仅可从好友中选择
    friend_ids = set(
        (
            await db.execute(
                select(Friendship.friend_id).where(
                    Friendship.user_id == current.id,
                    Friendship.status == "accepted",
                )
            )
        ).scalars()
    )
    invalid = [uid for uid in body.member_ids if uid not in friend_ids]
    if invalid:
        raise HTTPException(status_code=400, detail="初始成员必须是你的好友")

    conv = Conversation(type="group", name=body.name, avatar_url=body.avatar_url, owner_id=current.id)
    db.add(conv)
    await db.flush()
    db.add(ConversationMember(conversation_id=conv.id, user_id=current.id, role="owner"))
    for uid in set(body.member_ids):
        if uid != current.id:
            db.add(ConversationMember(conversation_id=conv.id, user_id=uid))
    await db.commit()
    return {"ok": True, "conversation_id": conv.id}


@router.post("/channel", status_code=201)
async def create_channel(
    body: ChannelCreateIn,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """创建频道：创建者自动成为 owner。

    与建群不同，频道不选初始成员——任何人可免审加入（见 join），
    创建者只需提供名称与简介。
    """
    conv = Conversation(
        type="channel",
        name=body.name,
        description=body.description,
        avatar_url=body.avatar_url,
        owner_id=current.id,
    )
    db.add(conv)
    await db.flush()
    db.add(
        ConversationMember(
            conversation_id=conv.id, user_id=current.id, role="owner"
        )
    )
    await db.commit()
    return {"ok": True, "conversation_id": conv.id}


@router.put("/{conversation_id}")
async def update_conversation(
    conversation_id: int,
    body: ConversationUpdateIn,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """修改群 / 频道信息（名称 / 头像 / 简介）：群主或管理员。单聊不支持。"""
    conv = await db.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if conv.type == "single":
        raise HTTPException(status_code=400, detail="单聊会话不支持修改信息")

    await _require_role(db, conversation_id, current.id)

    if body.avatar_url is not None and not body.avatar_url.startswith("/uploads/"):
        raise HTTPException(status_code=400, detail="头像需先通过上传接口获取 URL")

    for field in ("name", "avatar_url", "description"):
        value = getattr(body, field)
        if value is not None:
            setattr(conv, field, value)
    await db.commit()
    return {"ok": True}


@router.get("/channels")
async def channel_square(
    q: str | None = Query(default=None, max_length=50),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """频道广场：全部频道，支持关键词与院系检索。加入免审。"""
    stmt = select(Conversation).where(Conversation.type == "channel")
    if q:
        keyword = f"%{q}%"
        stmt = stmt.where(
            (Conversation.name.like(keyword)) | (Conversation.description.like(keyword))
        )
    rows = await db.execute(stmt.order_by(Conversation.created_at.desc()))

    my_ids = set(
        (
            await db.execute(
                select(ConversationMember.conversation_id).where(
                    ConversationMember.user_id == current.id
                )
            )
        ).scalars()
    )

    out = []
    for conv in rows.scalars():
        member_count = await db.scalar(
            select(func.count())
            .select_from(ConversationMember)
            .where(ConversationMember.conversation_id == conv.id)
        )
        creator = await db.get(User, conv.owner_id) if conv.owner_id else None
        out.append(
            {
                "conversation_id": conv.id,
                "name": conv.name,
                "description": conv.description,
                "avatar_url": conv.avatar_url,
                "department": creator.department if creator else None,
                "member_count": member_count,
                "joined": conv.id in my_ids,
                "creator": creator.nickname if creator else None,
            }
        )
    return out


@router.post("/{conversation_id}/join")
async def join(
    conversation_id: int,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """免审加入频道（**仅频道**；群聊必须走加群申请）。

    加入无门槛不代表发言无门槛：频道内的发言同样受敏感词与举报机制约束，
    这是"免审进入 ≠ 免审发言"的落地。
    """
    conv = await db.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if conv.type != "channel":
        # 免审进入 ≠ 免审发言：加入无门槛仅限频道；群聊仍走邀请/申请
        raise HTTPException(status_code=403, detail="仅频道支持免审加入")

    # 注意：此处只能用查询判断"是否已加入"，不能用 _assert_member——
    # 后者在"非成员"时会抛 403，会导致所有未加入的人都无法加入频道。
    already = await db.scalar(
        select(ConversationMember).where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == current.id,
        )
    )
    if already is not None:
        raise HTTPException(status_code=400, detail="你已在该频道中")

    db.add(ConversationMember(conversation_id=conversation_id, user_id=current.id))
    await db.commit()
    return {"ok": True}


# ---------- 加群申请（群聊：搜索预览 → 申请 → 群主 / 管理员审批） ----------

@router.get("/{conversation_id}/group-preview", response_model=GroupPreviewOut)
async def group_preview(
    conversation_id: int,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """按群号预览群信息：知道群号即可查看，不要求是群成员。

    顺带返回"我是否已在群 / 我的申请状态"，让前端直接决定能否再发申请。
    """
    conv = await db.get(Conversation, conversation_id)
    if conv is None or conv.type != "group":
        raise HTTPException(status_code=404, detail="没有找到该群聊，请检查群号")

    member_count = await db.scalar(
        select(func.count())
        .select_from(ConversationMember)
        .where(ConversationMember.conversation_id == conversation_id)
    )
    owner = await db.get(User, conv.owner_id) if conv.owner_id else None

    joined = (
        await db.scalar(
            select(ConversationMember).where(
                ConversationMember.conversation_id == conversation_id,
                ConversationMember.user_id == current.id,
            )
        )
        is not None
    )

    mine = await db.scalar(
        select(GroupJoinRequest).where(
            GroupJoinRequest.conversation_id == conversation_id,
            GroupJoinRequest.user_id == current.id,
        )
    )

    return GroupPreviewOut(
        conversation_id=conv.id,
        name=conv.name,
        avatar_url=conv.avatar_url,
        description=conv.description,
        member_count=member_count or 0,
        owner_name=owner.nickname if owner else None,
        joined=joined,
        my_request_status=mine.status if mine else None,
    )


@router.post("/{conversation_id}/join-requests", status_code=201)
async def create_join_request(
    conversation_id: int,
    body: GroupJoinRequestIn,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """申请加入群聊（群号 = 会话 id）。

    与频道的免审加入不同：群聊必须由群主 / 管理员审批，
    因此这里只落一条 pending 申请，不改成员表。
    """
    conv = await db.get(Conversation, conversation_id)
    if conv is None or conv.type != "group":
        raise HTTPException(status_code=404, detail="群聊不存在")

    already = await db.scalar(
        select(ConversationMember).where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == current.id,
        )
    )
    if already is not None:
        raise HTTPException(status_code=400, detail="你已在该群中")

    existing = await db.scalar(
        select(GroupJoinRequest).where(
            GroupJoinRequest.conversation_id == conversation_id,
            GroupJoinRequest.user_id == current.id,
        )
    )
    if existing is not None:
        if existing.status == "pending":
            raise HTTPException(status_code=400, detail="已提交申请，等待群主处理")
        # 曾被拒绝：复用同一条记录重新申请（(conversation_id, user_id) 有唯一约束）
        existing.status = "pending"
        existing.message = body.message
        existing.created_at = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
        existing.updated_at = None
        await db.commit()
        return {"ok": True, "detail": "申请已重新发送"}

    db.add(
        GroupJoinRequest(
            conversation_id=conversation_id,
            user_id=current.id,
            message=body.message,
            status="pending",
        )
    )
    await db.commit()
    return {"ok": True, "detail": "申请已发送"}


@router.get("/join-requests", response_model=list[GroupRequestOut])
async def list_join_requests(
    box: str = Query(default="received", pattern="^(received|sent)$"),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """加群申请列表。

    received = 我作为群主 / 管理员的群的申请（含已同意，便于从记录打开群资料
    发消息）；sent = 我发出的全部状态申请。两栏都保留"已同意"，互不影响。
    """
    if box == "received":
        my_admin_conv_ids = set(
            (
                await db.execute(
                    select(ConversationMember.conversation_id).where(
                        ConversationMember.user_id == current.id,
                        ConversationMember.role.in_(("owner", "admin")),
                    )
                )
            ).scalars()
        )
        if not my_admin_conv_ids:
            return []
        stmt = select(GroupJoinRequest).where(
            GroupJoinRequest.conversation_id.in_(my_admin_conv_ids),
            GroupJoinRequest.status.in_(("pending", "accepted", "rejected")),
        )
    else:
        stmt = select(GroupJoinRequest).where(GroupJoinRequest.user_id == current.id)

    rows = await db.execute(stmt.order_by(GroupJoinRequest.created_at.desc()))
    out: list[GroupRequestOut] = []
    for r in rows.scalars():
        conv = await db.get(Conversation, r.conversation_id)
        if conv is None:
            continue
        applicant = await db.get(User, r.user_id)
        out.append(
            GroupRequestOut(
                request_id=r.id,
                conversation=ConversationBriefOut(
                    conversation_id=conv.id, name=conv.name, avatar_url=conv.avatar_url
                ),
                user=UserBriefOut.model_validate(applicant) if applicant else None,
                message=r.message,
                status=r.status,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
        )
    return out


@router.put("/join-requests/{request_id}")
async def handle_join_request(
    request_id: int,
    body: GroupJoinActionIn,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """审批加群申请：仅该群的群主 / 管理员。同意后申请人立即入群。"""
    req = await db.get(GroupJoinRequest, request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="申请不存在")

    conv = await db.get(Conversation, req.conversation_id)
    if conv is None or conv.type != "group":
        raise HTTPException(status_code=404, detail="群聊不存在")

    await _require_role(db, req.conversation_id, current.id)

    if req.status != "pending":
        raise HTTPException(status_code=400, detail="该申请已处理")

    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)

    if body.action == "accept":
        already = await db.scalar(
            select(ConversationMember).where(
                ConversationMember.conversation_id == req.conversation_id,
                ConversationMember.user_id == req.user_id,
            )
        )
        if already is None:
            db.add(
                ConversationMember(
                    conversation_id=req.conversation_id, user_id=req.user_id
                )
            )
        req.status = "accepted"
        req.updated_at = now
        await db.commit()
        return {"ok": True, "detail": "已同意入群"}

    if body.action == "reject":
        req.status = "rejected"
        req.updated_at = now
        await db.commit()
        return {"ok": True, "detail": "已拒绝"}

    raise HTTPException(status_code=400, detail="action 只能是 accept 或 reject")


@router.post("/{conversation_id}/leave")
async def leave(
    conversation_id: int,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """退出群聊 / 频道：删除自己的成员记录。

    非成员调用会被 ``_assert_member`` 拦成 403；
    退出不删除历史消息与帖子，重新加入后仍可按可见性规则看到。
    """
    member = await _assert_member(db, conversation_id, current.id)
    await db.delete(member)
    await db.commit()
    return {"ok": True}


@router.put("/{conversation_id}/history-visibility")
async def update_history_visibility(
    conversation_id: int,
    body: HistoryVisibilityIn,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """设置群聊历史可见性：群主 / 管理员（设计 2.2.7）。

    仅群聊提供入口——频道历史对新成员恒为全部可见，私聊恒为双方全部可见，
    两者都不需要配置，因此明确拒绝，避免产生"设置了却不生效"的误解。
    """
    conv = await db.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if conv.type != "group":
        raise HTTPException(status_code=400, detail="仅群聊支持设置历史可见性")

    await _require_role(db, conversation_id, current.id)

    if body.mode == "recent_n" and body.limit is None:
        raise HTTPException(status_code=400, detail="选择「最近 N 条」时必须填写条数")

    conv.history_visible_mode = body.mode
    if body.mode == "recent_n":
        conv.history_limit = body.limit
    await db.commit()
    return {
        "ok": True,
        "history_visible_mode": conv.history_visible_mode,
        "history_limit": conv.history_limit,
    }


# ---------- 成员管理 ----------

@router.get("/{conversation_id}/members", response_model=list[MemberOut])
async def member_list(
    conversation_id: int,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """成员列表：仅会话成员可查看。

    返回的 ``role`` 供前端决定是否显示"移除成员 / 历史可见性"等管理入口，
    真正的权限判定仍在服务端。
    """
    await _assert_member(db, conversation_id, current.id)
    rows = await db.execute(
        select(ConversationMember).where(
            ConversationMember.conversation_id == conversation_id
        )
    )
    out = []
    for m in rows.scalars():
        u = await db.get(User, m.user_id)
        if u is None:
            continue
        out.append(
            MemberOut(
                user_id=u.id,
                nickname=u.nickname,
                avatar_url=u.avatar_url,
                role=m.role,
                joined_at=m.joined_at,
            )
        )
    return out


@router.post("/{conversation_id}/members", status_code=201)
async def invite_member(
    conversation_id: int,
    body: InviteIn,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """群聊：群主 / 管理员邀请好友入群。"""
    conv = await db.get(Conversation, conversation_id)
    if conv is None or conv.type != "group":
        raise HTTPException(status_code=404, detail="群聊不存在")

    await _require_role(db, conversation_id, current.id)

    exists = await db.scalar(
        select(ConversationMember).where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == body.user_id,
        )
    )
    if exists is not None:
        raise HTTPException(status_code=400, detail="对方已在群里")

    db.add(ConversationMember(conversation_id=conversation_id, user_id=body.user_id))
    await db.commit()
    return {"ok": True}


@router.delete("/{conversation_id}/members/{user_id}")
async def remove_member(
    conversation_id: int,
    user_id: int,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """移除成员：群主 / 管理员（频道同理）。

    只删成员记录，不删除该成员已发送的消息；被移除者若想回来，
    群聊需重新申请，频道可直接免审再加入。
    """
    conv = await db.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    await _require_role(db, conversation_id, current.id)

    member = await db.scalar(
        select(ConversationMember).where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == user_id,
        )
    )
    if member is None:
        raise HTTPException(status_code=404, detail="对方不是该会话成员")
    await db.delete(member)
    await db.commit()
    return {"ok": True}


# ---------- 历史消息 / 已读 / 撤回 ----------
