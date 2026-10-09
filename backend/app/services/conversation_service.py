"""会话域服务：会话建立与成员校验的可复用逻辑。

统一会话抽象的配套件：私聊 / 群聊 / 频道共用同一套成员模型，
因此"成员校验""角色校验""私聊会话幂等创建"全部收敛在这里，
路由层（conversations / friends / messages）只做 HTTP 编排。
"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation, ConversationMember


async def get_or_create_single_conversation(
    db: AsyncSession, user_a: int, user_b: int
) -> Conversation:
    """私聊会话幂等创建。

    双方成为好友后私聊会话自动成立；user_a == user_b 时是"给自己发消息"，
    对应一个只有自己一个成员的单聊会话（备忘录形态）。
    """
    if user_a == user_b:
        # 先取本人参与的全部单聊，再挑出"成员只有自己"的那个。
        # 不能直接 where user_id == 自己后 count：那样每个分组只剩一条，
        # count 恒为 1，普通双人私聊也会被误判成自我会话。
        candidate_ids = (
            await db.execute(
                select(ConversationMember.conversation_id)
                .join(Conversation, Conversation.id == ConversationMember.conversation_id)
                .where(Conversation.type == "single")
                .where(ConversationMember.user_id == user_a)
            )
        ).scalars().all()
        for cid in candidate_ids:
            total = await db.scalar(
                select(func.count())
                .select_from(ConversationMember)
                .where(ConversationMember.conversation_id == cid)
            )
            if total == 1:
                conv = await db.get(Conversation, cid)
                if conv is not None:
                    return conv

        conv = Conversation(type="single")
        db.add(conv)
        await db.flush()
        db.add(ConversationMember(conversation_id=conv.id, user_id=user_a))
        await db.commit()
        return conv

    rows = await db.execute(
        select(ConversationMember.conversation_id)
        .join(Conversation, Conversation.id == ConversationMember.conversation_id)
        .where(Conversation.type == "single")
        .where(ConversationMember.user_id.in_([user_a, user_b]))
        .group_by(ConversationMember.conversation_id)
        .having(func.count(ConversationMember.user_id) == 2)
    )
    conv_id = rows.scalars().first()
    if conv_id is not None:
        conv = await db.get(Conversation, conv_id)
        if conv is not None:
            return conv

    conv = Conversation(type="single")
    db.add(conv)
    await db.flush()
    db.add_all(
        [
            ConversationMember(conversation_id=conv.id, user_id=user_a),
            ConversationMember(conversation_id=conv.id, user_id=user_b),
        ]
    )
    await db.commit()
    return conv


async def assert_member(
    db: AsyncSession, conversation_id: int, user_id: int
) -> ConversationMember:
    """校验"是成员"，否则 403。注意：判断"是否已加入"不要用它（会抛异常）。"""
    member = await db.scalar(
        select(ConversationMember).where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == user_id,
        )
    )
    if member is None:
        raise HTTPException(status_code=403, detail="你不是该会话成员")
    return member


async def require_owner_or_admin(
    db: AsyncSession, conversation_id: int, user_id: int
) -> ConversationMember:
    member = await assert_member(db, conversation_id, user_id)
    if member.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="仅群主或创建者可执行此操作")
    return member
