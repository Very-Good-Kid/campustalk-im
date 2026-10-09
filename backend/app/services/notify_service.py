"""通知域服务：系统通知（撤回 / 置顶变更等）的统一广播入口。

与 message_service 的区别：这里**不产生消息记录**，只推送"事件通知"帧，
用于让会话内的在线端即时同步状态变化，避免"一方操作、另一方要刷新才看得到"。

帧格式：{"type": "system_notice", "data": {"event": ..., "conversation_id": ...}}
前端 chat store 订阅 system_notice 后做幂等更新（重复收到同一事件结果一致）。
"""
from __future__ import annotations

from sqlalchemy import select

from app.models import ConversationMember
from app.services import bus


async def conversation_member_ids(db, conversation_id: int) -> list[int]:
    """会话内全部成员 id（含消息发送者本人）。

    消息推送与系统通知共用同一套成员查询，避免两处各写一份而漂移。
    """
    return list(
        (
            await db.execute(
                select(ConversationMember.user_id).where(
                    ConversationMember.conversation_id == conversation_id
                )
            )
        ).scalars()
    )


async def push_system_notice(db, conversation_id: int, event: str, **data) -> None:
    """向会话内全部成员广播一条系统通知。

    有意**不排除操作者本人**：前端处理是幂等的，"统一广播给所有人"比
    "给谁发、不给谁发"的分支更少、更不容易出错（发起端本来也已做了乐观更新）。

    不在线成员由订阅任务自然跳过（本实例连接表里没有对应连接），
    他们下次刷新页面时会从历史消息中读到最新状态——与"消息不丢"同一套保证。
    """
    payload = {
        "type": "system_notice",
        "data": {"event": event, "conversation_id": conversation_id, **data},
    }
    await bus.publish(await conversation_member_ids(db, conversation_id), payload)
