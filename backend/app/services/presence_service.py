"""在线状态（presence）：跳变广播 + REST 快照。

数据分两半，各用顺手的存储：
- "谁在线"的**计数**在 Redis（bus.py 的 campustalk:online:<uid>），
  因为连接建立/断开是高频小事件，且多实例下必须合并判定；
- "推给谁"的**好友列表**在 MySQL（friendship 表），只在 0→1 / 1→0
  跳变时查一次，频率等于用户上线/下线次数，不构成压力。

帧协议：``{"type":"presence","data":{"user_id":int,"online":bool}}``，
发给该用户的全部已接受好友＋本人（本人多端时另一端也能感知）。
presence 是纯展示帧：不落库、断线错过无所谓——快照接口
（/friends/online）随时能把当前状态补齐，收帧只是省一次轮询。
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Friendship
from app.services import bus


async def friend_ids(db: AsyncSession, user_id: int) -> list[int]:
    """该用户全部已接受好友的 id（friendship 双向各存一条，查一侧即可）。"""
    return list(
        (
            await db.scalars(
                select(Friendship.friend_id).where(
                    Friendship.user_id == user_id,
                    Friendship.status == "accepted",
                )
            )
        ).all()
    )


async def announce(db: AsyncSession, user_id: int, online: bool) -> None:
    """上下线跳变发生后，把 presence 帧经总线推给好友集合（含本人）。"""
    uids = await friend_ids(db, user_id)
    if user_id not in uids:
        uids.append(user_id)
    await bus.publish(
        uids, {"type": "presence", "data": {"user_id": user_id, "online": online}}
    )


async def snapshot(db: AsyncSession, user_id: int) -> dict[int, bool]:
    """某用户视角的在线快照：{好友id: 是否在线}，前端进联系人页时拉一次。"""
    ids = await friend_ids(db, user_id)
    return await bus.online_flags(ids)
