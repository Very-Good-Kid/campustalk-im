"""消息域服务：消息落库与推送的唯一入口。

铁律：消息先落库再推送。WebSocket 断开时消息仍在库里，刷新页面即可见。
用户消息与机器人消息都走 save_and_push，保证敏感词（调用方）、
推送、未读统计等逻辑统一生效——任何代码不得绕过它直接写 message 表。
"""
from __future__ import annotations

import json

from sqlalchemy import select

from app.models import ConversationMember, Message, User
from app.services import bus
from app.services.notify_service import conversation_member_ids


async def parse_mentions(db, conversation_id: int, sender_id: int, content: str) -> list[int]:
    """解析文本消息里的 @成员：内容含 "@昵称" 即算命中，返回被 @ 的用户 id 列表。

    - 只在会话成员里匹配（含机器人账号），路人昵称再像也不算；
    - 发送者自己不计入（自己 @ 自己没意义，前端也不会给自己弹提示）；
    - 昵称短的可能被长昵称包含误伤，例如 "an" 命中 "@andy"——
      演示量级下可接受，不做词边界分词。
    """
    rows = await db.execute(
        select(ConversationMember.user_id, User.nickname)
        .join(User, User.id == ConversationMember.user_id)
        .where(ConversationMember.conversation_id == conversation_id)
        .where(ConversationMember.user_id != sender_id)
    )
    return [uid for uid, nickname in rows if nickname and f"@{nickname}" in content]


def mentions_of(m: Message) -> list[int]:
    """Message.mentions 存的是 JSON 数组文本，解析失败当空处理，不阻断消息链路。

    WS 投递与 REST 历史接口共用这一个解析入口，保证两条通道返回同构。
    """
    try:
        return json.loads(m.mentions) if m.mentions else []
    except (TypeError, ValueError):
        return []


def message_payload(
    m: Message,
    nickname: str,
    avatar_url: str | None = None,
    card_user: User | None = None,
) -> dict:
    """把 ORM 消息对象转成前端直接可用的字典（即 WS 帧的 ``data`` 部分）。

    与 ``schemas.MessageOut`` 的字段保持一致——改一处务必同步另一处。

    - ``content``：已撤回消息置空字符串，撤回只做标记、原文不投递给前端；
    - ``card_user``：仅名片消息（``msg_type == "card"``）非空，供前端渲染名片；
    - 时间字段用 isoformat 输出（UTC 朴素时间，由前端补 Z 后转本地时区）。
    """
    return {
        "id": m.id,
        "conversation_id": m.conversation_id,
        "sender_id": m.sender_id,
        "sender_nickname": nickname,
        "sender_avatar_url": avatar_url,
        "msg_type": m.msg_type,
        "sender_type": m.sender_type,
        "content": "" if m.recalled_at else m.content,
        "file_name": m.file_name,
        "file_size": m.file_size,
        "reply_to_id": m.reply_to_id,
        "recalled_at": m.recalled_at.isoformat() if m.recalled_at else None,
        "is_pinned": m.is_pinned,
        "mentions": mentions_of(m),
        "created_at": m.created_at.isoformat(),
        # 名片消息的被推荐用户（头像 / 昵称）：前端据此渲染名片
        "card_user": (
            {
                "id": card_user.id,
                "nickname": card_user.nickname,
                "avatar_url": card_user.avatar_url,
            }
            if card_user is not None
            else None
        ),
    }


async def save_and_push(
    db,
    conversation_id: int,
    sender_id: int,
    msg_type: str,
    sender_type: str,
    content: str,
    file_name: str | None = None,
    file_size: int | None = None,
    reply_to_id: int | None = None,
) -> Message:
    """落库 → 向 Redis 总线 PUBLISH 一帧，投递给会话内全部成员（**含发送者本人**）。

    推送不再在本函数里循环本地连接：成员列表解析一次后交给总线信封，
    各进程实例的订阅任务各自投递自己本地的在线连接（见 services/bus.py）。

    参数:
        conversation_id: 目标会话。调用方负责先校验发送者是其成员（本函数不校验）。
        sender_id: 发送者 id，可以是机器人账号。
        msg_type: text / emoji / image / file / card。
        sender_type: user / bot，写入 ``message.sender_type``。
        content: 文本与表情传原文；图片与文件传 ``/uploads/...`` URL；名片传被推荐用户 id。
        file_name / file_size: 仅 image / file 会写入，其余类型强制置空。
        reply_to_id: 引用回复的目标消息 id；None 表示普通消息。

    返回:
        已落库并 ``refresh`` 过的 Message 实例（``id`` / ``created_at`` 可直接使用）。

    注意:
        - 推送对象包含发送者本人，前端以 WS 回显为准追加、不做本地乐观插入，
          因此调用方**不要再**自行插入一条消息；
        - 敏感词校验不在此处（在 router 层完成后才调用本函数），本函数只负责"存 + 发"；
        - publish 失败不回滚、不抛异常（bus.publish 内部记日志），
          "消息不丢"由"先落库"保证。
    """
    msg = Message(
        conversation_id=conversation_id,
        sender_id=sender_id,
        msg_type=msg_type,
        sender_type=sender_type,
        content=content,
        file_name=file_name if msg_type in ("image", "file") else None,
        file_size=file_size if msg_type in ("image", "file") else None,
        reply_to_id=reply_to_id,
    )
    # @我解析：仅文本消息，后端生成后随消息一起透传，前端不重复解析
    if msg_type == "text":
        ids = await parse_mentions(db, conversation_id, sender_id, content)
        if ids:
            msg.mentions = json.dumps(ids)
    db.add(msg)
    await db.commit()  # 先落库
    await db.refresh(msg)

    sender = await db.get(User, sender_id)
    nickname = sender.nickname if sender else ""

    # 名片消息：附带被推荐用户的昵称与头像，前端才能直接渲染名片
    card_user = None
    if msg_type == "card":
        try:
            card_user = await db.get(User, int(content))
        except (TypeError, ValueError):
            card_user = None

    payload = {
        "type": "receive_message",
        "data": message_payload(
            msg, nickname, sender.avatar_url if sender else None, card_user
        ),
    }
    await bus.publish(
        await conversation_member_ids(db, conversation_id), payload
    )
    return msg
