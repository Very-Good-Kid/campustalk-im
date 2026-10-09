"""关系域：好友的添加、删除与信息修改（备注 / 分组 / 特别关注）。

铁律：好友关系必须双向存两条；备注与分组是持有者私有数据。
"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models import Conversation, ConversationMember, Friendship, User
from app.services import presence_service
from app.services.conversation_service import get_or_create_single_conversation
from app.schemas import FriendOut, RequestOut, UserBriefOut

router = APIRouter(prefix="/api", tags=["friends"])


# ---------- 请求/响应模型 ----------

class FriendRequestIn(BaseModel):
    friend_id: int
    request_message: str | None = Field(default=None, max_length=200)


class FriendRequestActionIn(BaseModel):
    action: str  # accept / reject


class FriendUpdateIn(BaseModel):
    remark: str | None = Field(default=None, max_length=50)
    group_name: str | None = Field(default=None, max_length=50)
    is_starred: bool | None = None


# ---------- 在线状态快照 ----------

@router.get("/friends/online")
async def friends_online(
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """好友在线快照 {好友id: 是否在线}，联系人页进入时拉一次。

    之后的变化靠 WS 的 presence 帧推送；注册在 /friends/{friend_id}
    类路径之前，避免 "online" 被当成路径参数吃掉。
    """
    snap = await presence_service.snapshot(db, current.id)
    return {"online": {str(uid): flag for uid, flag in snap.items()}}


# ---------- 用户检索 ----------

# 路由顺序陷阱：FastAPI 按注册顺序匹配，若这里写成 /users/{user_id}，
# 会把 /users/search 当成 user_id="search" 而报 422。故资料接口独占 /profile 子路径。
@router.get("/users/{user_id}/profile", response_model=UserBriefOut)
async def user_profile(
    user_id: int,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """按 id 查用户简要资料——名片消息点击后使用。"""
    u = await db.get(User, user_id)
    if u is None or u.is_bot:
        raise HTTPException(status_code=404, detail="用户不存在")
    return UserBriefOut.model_validate(u)


@router.get("/users/search", response_model=list[UserBriefOut])
async def search_users(
    q: str = Query(min_length=1, max_length=50),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """按用户名精确检索——唯一可发现的加好友通道。

    隐私设计：昵称可能被填成真实姓名，学号属于半敏感信息，
    两者均不可被检索，否则"按姓名搜人"会带来骚扰风险。
    找同班同学走独立的受控接口（classmates）。
    """
    rows = await db.execute(
        select(User)
        .where(
            User.username == q.strip(),
            User.id != current.id,
            User.is_bot == False,  # noqa: E712
        )
        .limit(1)
    )
    return [UserBriefOut.model_validate(u) for u in rows.scalars()]


@router.post("/friends/{friend_id}/conversation")
async def open_single_conversation(
    friend_id: int,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """打开与某位好友的私聊会话（不存在则创建）。

    资料卡片上的「发消息」使用——好友关系已成立，故无需二次校验申请。
    friend_id == 自己时是"给自己发消息"，跳过好友校验（自己不是自己的好友）。
    """
    if friend_id != current.id:
        is_friend = await db.scalar(
            select(Friendship).where(
                Friendship.user_id == current.id,
                Friendship.friend_id == friend_id,
                Friendship.status == "accepted",
            )
        )
        if is_friend is None:
            raise HTTPException(status_code=403, detail="对方还不是你的好友")

    conv = await get_or_create_single_conversation(db, current.id, friend_id)
    await db.commit()
    return {"conversation_id": conv.id}


@router.get("/users/classmates", response_model=list[UserBriefOut])
async def classmates(
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """找同班同学：按班级精确匹配。"""
    if not current.class_name:
        return []
    rows = await db.execute(
        select(User).where(
            User.class_name == current.class_name,
            User.id != current.id,
            User.is_bot == False,  # noqa: E712
        )
    )
    return [UserBriefOut.model_validate(u) for u in rows.scalars()]


# ---------- 好友申请 ----------

@router.post("/friends/requests", status_code=201)
async def send_request(
    body: FriendRequestIn,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """发起好友申请：只写一条"我 → 对方"的 pending 记录。

    拒绝的情况：加自己、目标不存在或是机器人、双方已是好友、已有待处理申请。
    曾被拒绝的申请允许重新发起——复用同一条记录（(user_id, friend_id) 有唯一约束，
    不能直接插新行）并刷新附言与时间，让对方重新收到待处理申请。
    """
    if body.friend_id == current.id:
        raise HTTPException(status_code=400, detail="不能添加自己为好友")

    target = await db.get(User, body.friend_id)
    if target is None or target.is_bot:
        raise HTTPException(status_code=404, detail="用户不存在")

    existing = await db.scalar(
        select(Friendship).where(
            Friendship.user_id == current.id, Friendship.friend_id == body.friend_id
        )
    )
    if existing is not None:
        if existing.status == "accepted":
            raise HTTPException(status_code=400, detail="你们已经是好友")
        if existing.status == "pending":
            raise HTTPException(status_code=400, detail="已提交过申请，等待对方处理")
        # 曾被拒绝：允许重新发起。复用同一条记录（(user_id, friend_id) 有唯一约束，
        # 不能直接插新行），并刷新附言与时间，让对方重新收到一条待处理申请。
        existing.status = "pending"
        existing.request_message = body.request_message
        existing.created_at = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
        existing.updated_at = None
        await db.commit()
        return {"ok": True, "detail": "申请已重新发送"}

    db.add(
        Friendship(
            user_id=current.id,
            friend_id=body.friend_id,
            status="pending",
            request_message=body.request_message,
        )
    )
    await db.commit()
    return {"ok": True, "detail": "申请已发送"}


@router.get("/friends/requests", response_model=list[RequestOut])
async def list_requests(
    box: str = Query(default="received", pattern="^(received|sent)$"),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """收到的 / 发出的好友申请。

    不再只返回 pending：发起方需要看到对方"同意 / 拒绝"的结果，
    否则"发出的申请"会在对方处理后就凭空消失。两个方向都返回全部状态，
    收到的也保留"已同意"，以便从这条记录直接打开资料卡发消息。
    """
    if box == "received":
        stmt = select(Friendship).where(
            Friendship.friend_id == current.id,
            Friendship.status.in_(("pending", "accepted", "rejected")),
        )
    else:
        stmt = select(Friendship).where(Friendship.user_id == current.id)
    rows = await db.execute(stmt.order_by(Friendship.created_at.desc()))

    out: list[RequestOut] = []
    for r in rows.scalars():
        other_id = r.user_id if box == "received" else r.friend_id
        other = await db.get(User, other_id)
        out.append(
            RequestOut(
                request_id=r.id,
                user=UserBriefOut.model_validate(other) if other else None,
                request_message=r.request_message,
                status=r.status,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
        )
    return out


@router.put("/friends/requests/{request_id}")
async def handle_request(
    request_id: int,
    body: FriendRequestActionIn,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """同意 / 拒绝好友申请（仅申请接收方本人可操作）。

    同意时做两件关键动作：
    1. **反向补写**一条 (我 → 申请人, accepted)——好友关系必须双向两条，
       因为备注与分组是各自私有的数据，不能共用一条记录；
    2. 建立或复用双方私聊会话，使"成为好友即可开聊"成立。
    """
    req = await db.get(Friendship, request_id)
    if req is None or req.friend_id != current.id:
        raise HTTPException(status_code=404, detail="申请不存在")

    if req.status != "pending":
        raise HTTPException(status_code=400, detail="该申请已处理")

    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)

    if body.action == "accept":
        req.status = "accepted"
        req.updated_at = now
        # 关键：反向补写一条。备注与分组是持有者私有数据，必须各存各的。
        reverse = await db.scalar(
            select(Friendship).where(
                Friendship.user_id == current.id, Friendship.friend_id == req.user_id
            )
        )
        if reverse is None:
            db.add(
                Friendship(
                    user_id=current.id,
                    friend_id=req.user_id,
                    status="accepted",
                    updated_at=now,
                )
            )
        else:
            reverse.status = "accepted"
            reverse.updated_at = now
        await db.commit()
        # 双方成为好友后，私聊会话自动成立
        await get_or_create_single_conversation(db, req.user_id, current.id)
        return {"ok": True, "detail": "已同意"}

    if body.action == "reject":
        req.status = "rejected"
        req.updated_at = now
        await db.commit()
        return {"ok": True, "detail": "已拒绝"}

    raise HTTPException(status_code=400, detail="action 只能是 accept 或 reject")


# ---------- 好友列表与信息修改 ----------

@router.get("/friends", response_model=list[FriendOut])
async def friend_list(
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """我的好友列表：取"我持有"的记录 + 对方公开资料。

    排序规则：特别关注置顶，其余按昵称。备注与分组只影响我自己的视图，
    不会出现在对方的列表里。
    """
    rows = await db.execute(
        select(Friendship).where(
            Friendship.user_id == current.id, Friendship.status == "accepted"
        )
    )
    out: list[FriendOut] = []
    for r in rows.scalars():
        friend = await db.get(User, r.friend_id)
        if friend is None:
            continue
        out.append(
            FriendOut(
                friend_user_id=friend.id,
                username=friend.username,
                nickname=friend.nickname,
                avatar_url=friend.avatar_url,
                department=friend.department,
                class_name=friend.class_name,
                remark=r.remark,
                group_name=r.group_name,
                is_starred=r.is_starred,
            )
        )
    # 特别关注置顶，其余按昵称
    out.sort(key=lambda f: (not f.is_starred, f.nickname))
    return out


@router.put("/friends/{friend_user_id}")
async def update_friend(
    friend_user_id: int,
    body: FriendUpdateIn,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """修改我给某位好友设置的备注 / 分组 / 特别关注。

    只写"我持有"的那条记录，因此不会影响对方看到的我的名字——
    这正是好友关系必须存双向两条的原因。仅 accepted 状态可修改。
    """
    rel = await db.scalar(
        select(Friendship).where(
            Friendship.user_id == current.id, Friendship.friend_id == friend_user_id
        )
    )
    if rel is None or rel.status != "accepted":
        raise HTTPException(status_code=404, detail="好友关系不存在")

    for field in ("remark", "group_name", "is_starred"):
        value = getattr(body, field)
        if value is not None:
            setattr(rel, field, value)
    rel.updated_at = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    await db.commit()
    return {"ok": True}


@router.delete("/friends/{friend_user_id}")
async def delete_friend(
    friend_user_id: int,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """双向删除两条记录。私聊会话记录保留，但列表不再显示（见会话列表过滤）。"""
    rows = await db.execute(
        select(Friendship).where(
            or_(
                (Friendship.user_id == current.id)
                & (Friendship.friend_id == friend_user_id),
                (Friendship.user_id == friend_user_id)
                & (Friendship.friend_id == current.id),
            )
        )
    )
    found = False
    for rel in rows.scalars():
        await db.delete(rel)
        found = True
    if not found:
        raise HTTPException(status_code=404, detail="好友关系不存在")
    await db.commit()
    return {"ok": True}
