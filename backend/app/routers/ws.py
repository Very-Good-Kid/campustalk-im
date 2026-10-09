"""WebSocket 端点：只负责实时投递与帧分发，不做业务判断、不直接写库。

铁律：消息先落库再推送。断线时消息仍在库里，刷新页面即可见。
业务规则全部在服务层：成员校验（会话域）、敏感词（core）、
落库与推送（message_service）、机器人回复（bot_service）。
"""
from __future__ import annotations

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.core.sensitive import hit_sensitive
from app.core.security import decode_access_token
from app.database import AsyncSessionLocal
from app.models import ConversationMember, Message, User
from app.services import bus, presence_service
from app.services.bot_service import bot_id as get_bot_id
from app.services.bot_service import reply_for
from app.services.connections import manager
from app.services.message_service import save_and_push
from app.services.notify_service import conversation_member_ids

router = APIRouter(tags=["ws"])

# 消息类型白名单：与前端 utils/format.js 的 detectMsgType 约定保持一致
ALLOWED_MSG_TYPES = ("text", "emoji", "image", "file", "card")


@router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket, token: str = Query(...)):
    """WebSocket 端点：接收 send_message，校验后转交服务层落库并广播。

    参数:
        token: 连接时经 query 传入的 JWT —— 浏览器 WebSocket API 无法自定义请求头，
        故认证信息只能走 query（HTTPS/WSS 下仍在链路加密范围内）。

    帧协议:
        客户端 → 服务端：
            ``{"type": "send_message", "conversation_id": int, "msg_type": str,
            "content": str, "file_name"?: str, "file_size"?: int, "reply_to_id"?: int}``
            ``{"type": "typing", "conversation_id": int}``（输入中提示，不落库）
        服务端 → 客户端：
            ``receive_message``（新消息，推给会话全体成员含发送者）、
            ``system_notice``（撤回 / 置顶变更，见 notify_service）、
            ``presence``（好友上下线跳变，见 presence_service）、
            ``typing``（同会话其他成员的输入中提示，不推给发起者本人）、
            ``error``（业务拒绝理由，前端统一弹 Toast）。

    校验顺序（任一步失败只回 error 帧，不断开连接）：
        握手鉴权与账号状态（失败直接 close(1008)）→ 消息类型白名单 →
        富媒体 URL / 文本非空 → 会话成员 → 名片目标存在 → 敏感词 →
        引用回复目标存在 → 落库并推送 → 文本消息触发规则机器人。

    注意:
        - 本函数不写库、不做业务判断，只做上述准入校验并转交服务层；
        - 每帧使用独立的 ``AsyncSessionLocal``，避免长连接复用同一会话
          造成事务残留或脏读；
        - 断连与任何异常都会注销连接，防止连接表泄漏；多端登录下
          只摘本条连接（connections.active 是集合），不影响同一用户的
          其他设备；上下线广播按连接数增减，只在 0↔非0 跳变时发帧。
    """
    user_id = decode_access_token(token)
    if user_id is None:
        await websocket.close(code=1008)  # 令牌无效直接关连接
        return

    # 账号禁用第三处生效点：握手即校验，避免"禁用后仍能继续收发消息"
    async with AsyncSessionLocal() as db:
        account = await db.get(User, user_id)
    if account is None or not account.is_active:
        await websocket.close(code=1008)
        return

    await manager.connect(user_id, websocket)

    # presence：每条连接都让集群计数 +1，只有 0→1 跳变才广播"上线"
    if await bus.online_add(user_id):
        async with AsyncSessionLocal() as db:
            await presence_service.announce(db, user_id, True)

    try:
        while True:
            data = await websocket.receive_json()

            # typing 帧：不落库，经总线转给同会话其他成员；频率由前端
            # 节流（3s 冷却）控制，演示规模下后端不再设限
            if data.get("type") == "typing":
                typing_cid = int(data.get("conversation_id", 0))
                async with AsyncSessionLocal() as db:
                    ok = await db.scalar(
                        select(ConversationMember).where(
                            ConversationMember.conversation_id == typing_cid,
                            ConversationMember.user_id == user_id,
                        )
                    )
                    if ok is not None:
                        others = [
                            m
                            for m in await conversation_member_ids(db, typing_cid)
                            if m != user_id
                        ]
                        await bus.publish(
                            others,
                            {"type": "typing", "data": {
                                "conversation_id": typing_cid, "user_id": user_id,
                            }},
                        )
                continue

            if data.get("type") != "send_message":
                continue

            conversation_id = int(data.get("conversation_id", 0))
            content = (data.get("content") or "").strip()
            msg_type = data.get("msg_type", "text")
            file_name = data.get("file_name")
            file_size = data.get("file_size")
            reply_to_id = data.get("reply_to_id")

            if msg_type not in ALLOWED_MSG_TYPES:
                await websocket.send_json({"type": "error", "detail": "不支持的消息类型"})
                continue

            if msg_type in ("image", "file"):
                # 富媒体：content 存的是上传接口返回的 URL，绝不传二进制
                if not content.startswith("/uploads/"):
                    await websocket.send_json(
                        {"type": "error", "detail": "请先调用上传接口获取文件 URL"}
                    )
                    continue
            elif not content:
                await websocket.send_json({"type": "error", "detail": "消息内容不能为空"})
                continue

            async with AsyncSessionLocal() as db:
                member = await db.scalar(
                    select(ConversationMember).where(
                        ConversationMember.conversation_id == conversation_id,
                        ConversationMember.user_id == user_id,
                    )
                )
                if member is None:
                    await websocket.send_json(
                        {"type": "error", "detail": "你不是该会话成员"}
                    )
                    continue

                # 名片：content 存被推荐用户的 id，服务端验证目标存在
                if msg_type == "card":
                    target = await db.get(User, int(content))
                    if target is None or target.is_bot:
                        await websocket.send_json(
                            {"type": "error", "detail": "被推荐的用户不存在"}
                        )
                        continue

                # 敏感词过滤：事中防线，命中即拒绝且不落库（仅作用于文本类内容）
                if msg_type in ("text", "emoji"):
                    hit = hit_sensitive(content)
                    if hit:
                        await websocket.send_json(
                            {"type": "error", "detail": f"消息包含敏感词：{hit}"}
                        )
                        continue

                # 引用回复：目标必须是同会话的已存在消息
                if reply_to_id is not None:
                    target = await db.get(Message, int(reply_to_id))
                    if target is None or target.conversation_id != conversation_id:
                        await websocket.send_json(
                            {"type": "error", "detail": "被引用的消息不存在"}
                        )
                        continue

                await save_and_push(
                    db, conversation_id, user_id, msg_type, "user",
                    content, file_name, file_size,
                    reply_to_id=int(reply_to_id) if reply_to_id is not None else None,
                )

                # 规则机器人：仅文本触发；回复走同一消息域入口，天然不会循环
                if msg_type == "text":
                    reply = reply_for(content)
                    if reply:
                        bid = await get_bot_id(db)
                        if bid:
                            await save_and_push(
                                db, conversation_id, bid, "text", "bot", reply
                            )

    except WebSocketDisconnect:
        pass
    except Exception:
        raise
    finally:
        # 只摘本条连接；本条是最后一条时集群计数归零 → 广播"下线"
        manager.disconnect(user_id, websocket)
        if await bus.online_remove(user_id):
            async with AsyncSessionLocal() as db:
                await presence_service.announce(db, user_id, False)
