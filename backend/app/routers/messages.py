"""消息域 REST 端点：历史拉取、已读标记、置顶话题帖、撤回。

URL 前缀与 conversations 相同（/api/conversations），按文档域划分归属消息域，
拆分只为代码组织清晰，对外接口路径不变。
"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.deps import get_current_user
from app.models import Conversation, Message, User
from app.schemas import CardUserOut, MessageOut
from app.services.conversation_service import assert_member, require_owner_or_admin
from app.services.message_service import mentions_of
from app.services.notify_service import push_system_notice

router = APIRouter(prefix="/api/conversations", tags=["messages"])


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
async def history(
    conversation_id: int,
    cursor: str | None = Query(default=None, description="上一页最早一条的 created_at"),
    limit: int = Query(default=20, le=50),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """历史消息：游标分页（游标 = 上一页最早一条的 created_at），返回**时间正序**。

    参数:
        cursor: 传上一页最早一条的 created_at 即向前翻更早的消息；不传则取最新一页。
        limit: 每页条数，上限 50。

    可见性由会话配置决定：
        - single / channel 恒为全部可见；
        - group 的 since_join 只返回 joined_at 之后的消息；
        - group 的 recent_n 先定位第 N 条的时间点作为下界，再走同一套分页查询。

    注意:
        - 已撤回消息仍返回条目（前端渲染成"XX 撤回了一条消息"），但 ``content`` 置空；
        - 名片消息附带 ``card_user``（被推荐用户的头像与昵称）。
    """
    member = await assert_member(db, conversation_id, current.id)

    stmt = select(Message).where(Message.conversation_id == conversation_id)

    # 群聊历史可见性：since_join 模式下新成员只能看加入之后的消息
    conv = await db.get(Conversation, conversation_id)
    if conv is not None and conv.history_visible_mode == "since_join":
        stmt = stmt.where(Message.created_at >= member.joined_at)
    elif conv is not None and conv.history_visible_mode == "recent_n":
        # recent_n：先查第 N 条的 created_at 作为时间下界，再走同一条分页查询
        limit_n = conv.history_limit or 20
        boundary = await db.scalar(
            select(Message.created_at)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .offset(limit_n - 1)
            .limit(1)
        )
        if boundary is not None:
            stmt = stmt.where(Message.created_at >= boundary)

    if cursor:
        try:
            stmt = stmt.where(Message.created_at < dt.datetime.fromisoformat(cursor))
        except ValueError:
            raise HTTPException(status_code=400, detail="cursor 格式非法")

    rows = await db.execute(stmt.order_by(Message.created_at.desc()).limit(limit))
    messages = list(rows.scalars())
    return (await _to_out_list(db, messages))[::-1]


async def _to_out_list(db: AsyncSession, messages: list[Message]) -> list[MessageOut]:
    """把 Message 行集装配成 MessageOut（历史 / 搜索 / 锚点页共用，保证字段同源）。

    逐条查发送者：页容量上限 50，演示量级下无需批量优化。
    """
    out: list[MessageOut] = []
    for m in messages:
        sender = await db.scalar(select(User).where(User.id == m.sender_id))
        # 名片消息：补上被推荐用户信息（content 存的是其 id）
        card_user = None
        if m.msg_type == "card" and not m.recalled_at:
            try:
                card_user = await db.get(User, int(m.content))
            except (TypeError, ValueError):
                card_user = None
        out.append(
            MessageOut(
                id=m.id,
                conversation_id=m.conversation_id,
                sender_id=m.sender_id,
                sender_nickname=sender.nickname if sender else "",
                sender_avatar_url=sender.avatar_url if sender else None,
                msg_type=m.msg_type,
                sender_type=m.sender_type,
                content="" if m.recalled_at else m.content,
                file_name=m.file_name,
                file_size=m.file_size,
                reply_to_id=m.reply_to_id,
                recalled_at=m.recalled_at,
                is_pinned=m.is_pinned,
                mentions=mentions_of(m),
                created_at=m.created_at,
                card_user=CardUserOut.model_validate(card_user) if card_user else None,
            )
        )
    return out


@router.get("/{conversation_id}/search-messages")
async def search_messages(
    conversation_id: int,
    q: str = Query(default=..., min_length=1, max_length=50, description="搜索关键词"),
    limit: int = Query(default=30, le=50),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """会话内消息搜索：返回命中消息（时间倒序，前端列表展示后点击跳转）。

    两条通道：
    - 长度 ≥2 走全文索引（ngram 分词，建表补丁见 init_db._PATCHES），
      中文按二元组切分，单字不进索引；
    - 单字 / 索引未就绪时回退 LIKE，小库下代价可接受。
    已撤回消息不参与搜索（撤回只留审计原文，不对外可检）。
    """
    await assert_member(db, conversation_id, current.id)
    kw = q.strip()
    if not kw:
        raise HTTPException(status_code=400, detail="搜索词不能为空")

    stmt = select(Message).where(
        Message.conversation_id == conversation_id,
        Message.recalled_at.is_(None),
    )
    if len(kw) >= 2:
        stmt = stmt.where(
            text("MATCH(content) AGAINST (:q IN NATURAL LANGUAGE MODE)")
        ).params(q=kw)
    else:
        escaped = kw.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(Message.content.like(f"%{escaped}%", escape="\\"))

    rows = await db.execute(stmt.order_by(Message.created_at.desc()).limit(limit))
    return await _to_out_list(db, list(rows.scalars()))


@router.get("/{conversation_id}/messages/around/{message_id}")
async def messages_around(
    conversation_id: int,
    message_id: int,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """以目标消息为锚点取一页上下文（目标前后各 20 条，共 ≤41 条，时间正序）。

    搜索结果跳转的落点：命中消息往往不在已加载区间，直接把它前后一页装好，
    前端替换当前会话消息后滚动到锚点即可，无需逐页上滚。
    可见性不叠加 history_visible_mode：能看到这条消息即已是成员，
    上下文的历史可见性限制由正常分页入口保证，这里不做二次拦截。
    """
    await assert_member(db, conversation_id, current.id)
    anchor = await db.get(Message, message_id)
    if anchor is None or anchor.conversation_id != conversation_id:
        raise HTTPException(status_code=404, detail="消息不在该会话中")

    before = (
        await db.execute(
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.created_at <= anchor.created_at,
            )
            .order_by(Message.created_at.desc())
            .limit(21)  # 含锚点本身；同微秒并列多发一条也无害
        )
    ).scalars()
    older = list(before)[::-1]
    newer = (
        await db.execute(
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.created_at > anchor.created_at,
            )
            .order_by(Message.created_at.asc())
            .limit(20)
        )
    ).scalars()
    return await _to_out_list(db, older + list(newer))


@router.post("/{conversation_id}/read")
async def mark_read(
    conversation_id: int,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """标记会话已读：把 ``last_read_message_id`` 推到当前最新一条。

    未读红点表示"我还有多少条没看"，**与已读回执无关**——
    本系统不向对方暴露"是否已经读过我的消息"。
    """
    member = await assert_member(db, conversation_id, current.id)
    latest = await db.scalar(
        select(Message.id)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.id.desc())
        .limit(1)
    )
    member.last_read_message_id = latest
    await db.commit()
    return {"ok": True, "last_read_message_id": latest}


@router.post("/{conversation_id}/messages/{message_id}/pin")
async def pin_message(
    conversation_id: int,
    message_id: int,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """频道置顶话题帖：仅创建者可操作，置顶唯一化（新置顶顶掉旧置顶）。"""
    conv = await db.get(Conversation, conversation_id)
    if conv is None or conv.type != "channel":
        raise HTTPException(status_code=404, detail="仅频道支持置顶话题帖")

    await require_owner_or_admin(db, conversation_id, current.id)

    msg = await db.get(Message, message_id)
    if msg is None or msg.conversation_id != conversation_id:
        raise HTTPException(status_code=404, detail="消息不在该频道中")

    # 唯一化：一个频道同时只有一个置顶话题帖
    old = (
        await db.execute(
            select(Message).where(
                Message.conversation_id == conversation_id,
                Message.is_pinned == True,  # noqa: E712
            )
        )
    ).scalars()
    previous_pinned_id = None
    for m in old:
        if m.is_pinned:
            previous_pinned_id = m.id
        m.is_pinned = False

    msg.is_pinned = True
    await db.commit()

    # 广播置顶变更：其他在线端把旧置顶取消、目标置顶（前端幂等处理）
    await push_system_notice(
        db,
        conversation_id,
        "message_pinned",
        message_id=msg.id,
        previous_pinned_id=previous_pinned_id,
    )
    return {"ok": True, "pinned_message_id": msg.id}


@router.delete("/{conversation_id}/messages/{message_id}/pin")
async def unpin_message(
    conversation_id: int,
    message_id: int,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """取消频道置顶话题帖：仅频道创建者 / 管理员，并广播 ``system_notice`` 同步其他在线端。"""
    conv = await db.get(Conversation, conversation_id)
    if conv is None or conv.type != "channel":
        raise HTTPException(status_code=404, detail="仅频道支持置顶话题帖")

    await require_owner_or_admin(db, conversation_id, current.id)

    msg = await db.get(Message, message_id)
    if msg is None or msg.conversation_id != conversation_id:
        raise HTTPException(status_code=404, detail="消息不在该频道中")

    msg.is_pinned = False
    await db.commit()
    await push_system_notice(db, conversation_id, "message_unpinned", message_id=msg.id)
    return {"ok": True}


@router.post("/messages/{message_id}/recall")
async def recall(
    message_id: int,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """撤回本人消息：需在 ``RECALL_WINDOW_SECONDS``（默认 180 秒）内，且只能撤回自己发的。

    撤回是**打标记而非删除**（原文保留，便于审计）；成功后广播 ``system_notice``，
    让会话内其他在线端立即把气泡换成"XX 撤回了一条消息"，无需刷新。
    重复撤回是幂等的：已撤回则直接返回原时间，不再重复广播。
    """
    msg = await db.get(Message, message_id)
    if msg is None:
        raise HTTPException(status_code=404, detail="消息不存在")
    if msg.sender_id != current.id:
        raise HTTPException(status_code=403, detail="只能撤回自己的消息")

    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    if (now - msg.created_at).total_seconds() > settings.recall_window_seconds:
        raise HTTPException(status_code=400, detail="该消息已超过可撤回时间")

    # 撤回是标记不是删除，原文保留便于审计
    if msg.recalled_at is None:
        msg.recalled_at = now
        await db.commit()
        # 广播撤回通知：否则对方界面不会同步变化（需求 F10）
        await push_system_notice(
            db,
            msg.conversation_id,
            "message_recalled",
            message_id=msg.id,
            recalled_at=now.isoformat(),
        )
    return {"ok": True, "recalled_at": msg.recalled_at}
