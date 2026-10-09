"""机器人域：规则机器人。

定位：它既是 W3 的功能点，也是消息域设计的"验证器"——
机器人以 `sender_type = bot` 的特殊用户身份走 save_and_push 发消息，
证明"非人类发送者也能走通整条消息链路"。
AI 总结（可选）同样以 bot 身份产生 ai_summary 类型消息。

机器人账号怎么管理（改动点都在这两个文件里，不需要动别处）：

1. 账号：由 ``init_db.py`` 创建，username 固定为 ``BOT_USERNAME``、``is_bot=True``、
   没有学号。它带一个密码哈希只是为了满足 user 表结构——登录接口会拒绝 is_bot
   账号（见 routers/auth.py），所以那个占位密码不能用来登录，也不必维护。
2. 换昵称 / 头像：直接改库即可（管理端账号列表里也能看到它）；或改 init_db.py
   里的默认值后重建账号。
3. 加指令：往 ``BOT_COMMANDS`` 加一行；加关键词：往 ``BOT_KEYWORDS`` 加一行。
   两张表都是纯数据，触发逻辑不用改。
4. 停用：把 ``is_active`` 置 0，或删掉这行账号。``bot_id()`` 查不到会返回 None，
   调用方跳过回复，聊天主流程不受影响。
5. 改触发范围：触发点在 routers/ws.py 的消息处理末尾，目前只对文本消息生效。
"""
from __future__ import annotations

from sqlalchemy import select

from app.models import User

BOT_USERNAME = "helper_bot"

BOT_COMMANDS = {
    "/help": "可用指令：/help 查看帮助 · /签到 每日打卡 · 消息里包含「帮助」也能唤醒我",
    "/签到": "签到成功！今天也是元气满满的一天",
}
BOT_KEYWORDS = {
    "帮助": "发送 /help 查看指令；/签到 打卡；其余时间安心聊天～",
}


async def bot_id(db) -> int | None:
    """按用户名查机器人账号 id。

    返回 None 表示机器人账号尚未初始化（init_db.py 未执行），
    调用方应跳过回复而不是中断本次消息处理——聊天主流程不依赖机器人。
    """
    bot = await db.scalar(select(User).where(User.username == BOT_USERNAME))
    return bot.id if bot else None


def reply_for(text: str) -> str | None:
    """规则机器人：指令优先，关键词其次。返回 None 表示不回复。"""
    t = text.strip()
    if t.startswith("/"):
        return BOT_COMMANDS.get(t, "未知指令，发送 /help 查看可用指令")
    for keyword, reply in BOT_KEYWORDS.items():
        if keyword in t:
            return reply
    return None
