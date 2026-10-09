"""Redis 广播总线：跨进程消息投递的唯一通道（课件"发布-订阅"方式的落地）。

演进背景：初版在 save_and_push 里按成员列表循环调用本地连接表推送，
即课件《群聊——多线程与广播讲解》的方式①"循环逐个发送"；连接表
（services/connections.py）是进程内存字典，多进程/多副本部署时跨进程
推送会静默丢失。现改为：发送端解析一次成员列表后向总线 PUBLISH 一条
信封，每个进程实例各持一个订阅任务，收到信封后只投递给本进程在线的
连接——方式③发布-订阅，connections 里的前提注释在此兑现。

信封结构：``{"uids": [int, ...], "payload": {帧内容}}``。
选择单频道＋显式 uids 而不是"按会话/按用户建频道"：
- 按会话建频道，订阅端还得回查成员表，每条消息多一次 DB 往返；
- 按用户建频道，发送端又退化成循环 publish，绕回老路。
成员列表在发送端（本来就持有 db 会话）解析一次，全链路只查一遍。

依赖策略（有意为之的不对称）：
- 启动时 ping 失败 → 直接抛异常，应用拒绝启动（fail fast，
  避免"服务起来了但广播静默失效"这种最难发现的故障）；
- 运行中 publish 失败 → 只记日志不上抛。消息已先落库，推送失败
  不影响投递语义——用户刷新页面仍能从历史里读到全部消息，
  与 manager.send "一个坏连接不中断整轮广播"的既有约定一致。
"""
from __future__ import annotations

import asyncio
import json
import logging

from redis.asyncio import Redis

from app.config import settings
from app.services.connections import manager

logger = logging.getLogger(__name__)

# 单总线频道：所有实例订阅同一频道，收到后按 uids 过滤本地连接
BUS_CHANNEL = "campustalk:bus"

# 在线计数键前缀：campustalk:online:<user_id> → 该用户全集群连接数。
# 用 Redis 而非直接查本地连接表，是为了多实例下 presence 判定也正确：
# 计数 0→1 / 1→0 的跳变才广播上线/下线，某设备另一块屏连在另一实例也算在线。
ONLINE_KEY_PREFIX = "campustalk:online:"

# protocol=2：redis-py 新版默认发 HELLO 握手（RESP3），Windows 便携版 Redis 5.x 不认该命令会直接拒连；
# 本模块只用 PUBLISH/SUBSCRIBE，RESP2 完全够用，显式锁协议版本保证服务端兼容面。
_client = Redis.from_url(settings.redis_url, decode_responses=True, protocol=2)

_subscriber_task: asyncio.Task | None = None


async def ping() -> None:
    """启动探活：连不上让 redis 异常直接上抛，由 lifespan 拒绝启动。"""
    await _client.ping()


async def reset_online() -> None:
    """实例冷启动时清空在线计数（lifespan 在 ping 之后调用）。

    权衡：上一代进程崩溃会留下虚高的计数（用户早已全部断开）。
    重启时把所有人归零，浏览器秒级自动重连会重新 INCR 建数；
    代价是重启后短暂窗口内"全员离线"，对演示场景可接受，
    也避免了给每条连接配心跳续期这套重量级机制。
    """
    try:
        keys = []
        async for key in _client.scan_iter(match=ONLINE_KEY_PREFIX + "*", count=200):
            keys.append(key)
        if keys:
            await _client.delete(*keys)
    except Exception:
        logger.exception("清理在线计数失败（不阻断启动，presence 短暂不准自愈）")


async def online_add(user_id: int) -> bool:
    """登记一条连接，返回是否触发"上线"跳变（计数 0→1）。

    失败（Redis 运行中抽风）返回 False：宁可不报上线，也不能
    报错把 WS 握手流程带崩——消息主链路另有"先落库后推送"兜底。
    """
    try:
        return await _client.incr(ONLINE_KEY_PREFIX + str(user_id)) == 1
    except Exception:
        logger.exception("在线计数 INCR 失败 user=%s", user_id)
        return False


async def online_remove(user_id: int) -> bool:
    """注销一条连接，返回是否触发"下线"跳变（计数降到 0）。

    键已不存在（被 reset 或异常丢过）时不写成负数：删键并返回
    False，让用户下次连接重新 INCR 建键，计数自愈回正轨。
    """
    try:
        key = ONLINE_KEY_PREFIX + str(user_id)
        left = await _client.decr(key)
        if left <= 0:
            await _client.delete(key)
            return left == 0
        return False
    except Exception:
        logger.exception("在线计数 DECR 失败 user=%s", user_id)
        return False


async def online_flags(user_ids: list[int]) -> dict[int, bool]:
    """批量查在线状态（REST 快照接口用）；Redis 异常时全部报离线。"""
    try:
        counts = await _client.mget([ONLINE_KEY_PREFIX + str(i) for i in user_ids])
        return {
            int(uid): (int(c) if c is not None else 0) > 0
            for uid, c in zip(user_ids, counts)
        }
    except Exception:
        logger.exception("在线计数 MGET 失败，快照全部按离线处理")
        return {int(uid): False for uid in user_ids}


async def online_count() -> int:
    """全集群在线用户数（管理端看板用）：连接数 > 0 的键个数。

    SCAN 遍历而非维护一个集合键：在线用户量级小（百级），看板低频轮询，
    不值得为计数再建一套增删同步机制。Redis 异常时返回 0，不抛。
    """
    try:
        keys = [k async for k in _client.scan_iter(match=ONLINE_KEY_PREFIX + "*", count=200)]
        if not keys:
            return 0
        vals = await _client.mget(keys)
        return sum(1 for v in vals if v and int(v) > 0)
    except Exception:
        logger.exception("在线用户数统计失败，按 0 返回")
        return 0


async def publish(uids: list[int], payload: dict) -> None:
    """把一帧内容广播给指定用户集合：一次 PUBLISH，替代原来的本地循环推送。

    调用方（message_service / notify_service）负责已经解析好成员 id 列表；
    本函数不校验 uids 是否为会话成员——成员校验在各自调用链上游已完成。
    失败只记日志：消息已落库，"消息不丢"由数据库保证，推送是尽力而为。
    """
    envelope = json.dumps({"uids": list(uids), "payload": payload})
    try:
        await _client.publish(BUS_CHANNEL, envelope)
    except Exception:
        logger.exception("Redis 总线 publish 失败（消息已落库，不重试不上抛）")


# ---- 实例间控制帧：复用同一条总线，但不面向任何用户 ----
# 信封里 uids 为空、payload.type 为 CONTROL_TYPE 即视为控制帧：
# 订阅循环命中已注册的动作处理器就地执行，不进用户投递。这样
# "改完配置让所有实例生效"不用新开频道、不用轮询，语义也和
# 数据帧同生同灭（Redis 挂了两者一起暂停，不出现半新半旧）。
CONTROL_TYPE = "__bus_control__"
CONTROL_RELOAD_WORDS = "reload_sensitive_words"

_control_handlers: dict[str, object] = {}


def register_control_handler(action: str, handler) -> None:
    """注册控制帧处理器（lifespan 启动时接线，异步函数）。"""
    _control_handlers[action] = handler


async def publish_control(action: str) -> None:
    """向全部实例（含自己）广播一条控制指令；失败只记日志。"""
    envelope = json.dumps({"uids": [], "payload": {"type": CONTROL_TYPE, "action": action}})
    try:
        await _client.publish(BUS_CHANNEL, envelope)
    except Exception:
        logger.exception("控制帧 publish 失败 action=%s（本实例仍会自行刷新）", action)


async def _deliver(uids, payload) -> None:
    """把一帧投递给本进程在线的连接；不在本实例的连接由其他实例各自投递。

    manager.send 对不在线用户静默跳过、对坏连接顺手清理，因此这里
    无需先过滤在线状态，直接循环即可（单实例内仍是顺序 await，不乱序）。
    """
    for uid in uids:
        try:
            await manager.send(int(uid), payload)
        except (TypeError, ValueError):
            continue  # 信封被非本系统客户端污染时跳过坏 id，不炸整个循环


async def _subscribe_loop() -> None:
    """常驻订阅任务：断线指数退避重连，重连后总线恢复投递（不补投历史）。"""
    backoff = 1.0
    while True:
        pubsub = _client.pubsub()
        try:
            await pubsub.subscribe(BUS_CHANNEL)
            backoff = 1.0  # 连接成功即重置退避
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue  # subscribe 确认帧等管理消息直接忽略
                try:
                    envelope = json.loads(message["data"])
                    payload = envelope["payload"]
                    if isinstance(payload, dict) and payload.get("type") == CONTROL_TYPE:
                        # 控制帧：就地执行本实例的刷新动作，不进用户投递
                        handler = _control_handlers.get(payload.get("action", ""))
                        if handler is not None:
                            await handler()
                        continue
                    await _deliver(envelope["uids"], payload)
                except (KeyError, TypeError, json.JSONDecodeError):
                    logger.warning("忽略总线消息: %r", message["data"][:200])
        except asyncio.CancelledError:
            await pubsub.aclose()
            raise
        except Exception:
            logger.exception("总线订阅中断，%.1fs 后重连", backoff)
            await pubsub.aclose()
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)


def start_subscriber() -> None:
    """lifespan 启动时挂起订阅任务（每进程一个，与 WS 事件循环同线程）。"""
    global _subscriber_task
    if _subscriber_task is None:
        _subscriber_task = asyncio.create_task(_subscribe_loop())


async def stop_subscriber() -> None:
    """lifespan 退出时取消订阅任务并关闭客户端连接，避免挂起任务泄漏。"""
    global _subscriber_task
    if _subscriber_task is not None:
        _subscriber_task.cancel()
        try:
            await _subscriber_task
        except asyncio.CancelledError:
            pass
        _subscriber_task = None
    await _client.aclose()
