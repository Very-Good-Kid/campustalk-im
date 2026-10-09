"""连接管理：进程内维护 user_id -> WebSocket 集合。

定位（引入 Redis 总线后）：本表仍是**进程本地**的在线连接表，
只负责"最后一米"投递；跨进程/多副本的广播由 Redis 总线承担
（见 services/bus.py：每实例订阅总线，各自投自己表里的连接）。
因此多进程部署下跨进程推送不再静默丢失——本注释此前写下的
前提条件已在 10-02 的总线改造中兑现。

多端登录（10-02 升级）：同一用户可同时挂多条连接（电脑＋手机
或多个标签页），每条消息会投给该用户在本进程的**全部**连接；
某一端读过消息后由 REST 接口清未读，其余端靠收帧刷新角标。
"""
from __future__ import annotations

from fastapi import WebSocket


class ConnectionManager:
    """进程内在线连接表：一个用户可对应**多条**连接（多端同时在线）。

    只登记本进程的连接；同一用户若连到了另一实例，由那一实例的
    订阅任务负责投递，本表不感知。总线信封按 uids 循环时，
    不在本表的用户自然被跳过，无需共享在线状态查询。
    """

    def __init__(self) -> None:
        """``active``：user_id → 该用户当前存活的 WebSocket 集合。"""
        self.active: dict[int, set[WebSocket]] = {}

    async def connect(self, user_id: int, ws: WebSocket) -> None:
        """完成握手并把这条连接并入该用户的连接集合。"""
        await ws.accept()
        self.active.setdefault(user_id, set()).add(ws)

    def disconnect(self, user_id: int, ws: WebSocket | None = None) -> None:
        """注销连接。传 ws 时只摘那一条（多端下不误伤其他设备）；
        不传则移除该用户全部连接。集合空了顺手把键删掉，
        用户不在表中时静默返回（断开是幂等操作）。"""
        conns = self.active.get(user_id)
        if conns is None:
            return
        if ws is None:
            self.active.pop(user_id, None)
        else:
            conns.discard(ws)
            if not conns:
                self.active.pop(user_id, None)

    def is_online(self, user_id: int) -> bool:
        """该用户在本进程是否有至少一条存活连接。"""
        return bool(self.active.get(user_id))

    def online_ids(self) -> set[int]:
        """本进程当前在线的 user_id 集合（presence 初始快照用）。"""
        return set(self.active)

    async def send(self, user_id: int, payload: dict) -> None:
        """向指定用户的**全部**本地连接各推一帧；不在线则直接跳过。

        这是"消息不丢"策略的一部分：推送失败不影响投递语义，
        该用户下次刷新会从历史消息里读到全部内容。
        发送异常（某条连接已死但 onclose 尚未触发）只摘掉那一条，
        且不向调用方抛出——批量推送不能因为一个坏连接中断整轮循环。
        """
        # 迭代快照：send 挂起期间 disconnect 可能改动原集合
        for ws in list(self.active.get(user_id, ())):
            try:
                await ws.send_json(payload)
            except Exception:
                self.disconnect(user_id, ws)


manager = ConnectionManager()
