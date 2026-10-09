"""初始化脚本：建表 + 插入演示数据。

前置：库必须已存在（create_all 不能建库）。在 Navicat 或命令行先执行：

    CREATE DATABASE campustalk
      DEFAULT CHARACTER SET utf8mb4
      DEFAULT COLLATE utf8mb4_0900_ai_ci;

运行：python init_db.py
"""
import asyncio

from sqlalchemy import select, text

from app.core.security import hash_password
from app.database import AsyncSessionLocal, engine
from app.models import Base, Conversation, ConversationMember, User

DEMO_USERS = [
    {
        "username": "alice",
        "password": "123456",
        "nickname": "爱丽丝",
        "student_id": "20230001",
        "department": "计算机学院",
        "class_name": "计科2301",
        "is_admin": True,
    },
    {
        "username": "bob",
        "password": "123456",
        "nickname": "鲍勃",
        "student_id": "20230002",
        "department": "计算机学院",
        "class_name": "计科2301",
        "is_admin": False,
    },
]


# 旧库补丁：create_all 只负责"建缺失的表"，不会给已存在的表加列或加外键，
# 因此模型演进产生的增量必须在这里显式补齐。
_PATCHES = (
    # ---- user：管理员标记、在线时间、学号变更留痕 ----
    "ALTER TABLE user ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT 0",
    "ALTER TABLE user ADD COLUMN last_seen_at DATETIME NULL",
    "ALTER TABLE user ADD COLUMN student_id_updated_at DATETIME NULL",
    "ALTER TABLE user ADD COLUMN student_id_updated_by INT NULL",
    # 账号禁用（管理端能力）：is_active 为假即禁用，另两列留痕
    "ALTER TABLE user ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1",
    "ALTER TABLE user ADD COLUMN disabled_at DATETIME NULL",
    "ALTER TABLE user ADD COLUMN disabled_by INT NULL",
    # ---- post / comment：频道内容层 ----
    # @我：消息表存被 @ 用户 id 的 JSON 数组文本（模型演进新增列）
    "ALTER TABLE message ADD COLUMN mentions VARCHAR(255) NULL",
    # 消息搜索：ngram 分词器支持中文（默认 ngram_token_size=2，单字不进索引），
    # 搜正文的 LIKE 慢查询靠这个全文索引接住；MySQL 语法：WITH PARSER 属于索引选项
    "ALTER TABLE message ADD FULLTEXT INDEX ft_message_content (content) WITH PARSER ngram",
    # 频道名片帖：被推荐用户 id
    "ALTER TABLE post ADD COLUMN card_user_id INT NULL",
    # 软删除留痕：status 保留不动，deleted_at 只记删除时间
    "ALTER TABLE post ADD COLUMN deleted_at DATETIME NULL",
    "ALTER TABLE comment ADD COLUMN deleted_at DATETIME NULL",
    # ---- 补外键：老库建表时未声明，新建库由 create_all 建表时自带 ----
    "ALTER TABLE post ADD CONSTRAINT fk_post_card_user"
    " FOREIGN KEY (card_user_id) REFERENCES `user`(id)",
    "ALTER TABLE student_id_request ADD CONSTRAINT fk_sidreq_user"
    " FOREIGN KEY (user_id) REFERENCES `user`(id)",
    "ALTER TABLE student_id_request ADD CONSTRAINT fk_sidreq_reviewer"
    " FOREIGN KEY (reviewer_id) REFERENCES `user`(id)",
)

# MySQL 的"已经存在"类错误码：出现即说明该补丁早已生效，跳过即可。
# 1060 列重复 / 1061 索引名重复 / 1826 外键约束名重复
_ALREADY_DONE = {
    1060: "列已存在",
    1061: "索引已存在",
    1826: "外键约束已存在",
}

# 时间精度补丁（系统测试缺陷 BG-001 的修复）：这些列参与时间比较或排序，
# 必须是微秒精度，否则同一秒内的多条记录时间戳完全相同，导致
# 游标翻页丢页、since_join / recent_n 历史可见性边界失准。
# 新库由 create_all 按模型（DateTime6）直接建成 DATETIME(6)；
# 老库靠下面的 MODIFY 补齐。先查 information_schema，只有精度不足才 ALTER。
_PRECISION_COLUMNS = (
    ("message", "created_at"),
    ("conversation_member", "joined_at"),
    ("post", "created_at"),
    ("comment", "created_at"),
    ("likes", "created_at"),
)


def _errno(exc: Exception) -> int | None:
    """取出 MySQL 错误码。

    SQLAlchemy 会把驱动异常包一层，真正的错误码在 ``exc.orig.args[0]``，
    即 aiomysql 抛出的 errno；不是整数就说明不是数据库层的错误。
    """
    args = getattr(getattr(exc, "orig", None), "args", None)
    if args and isinstance(args[0], int):
        return args[0]
    return None


async def patch_existing_tables() -> None:
    """为旧库补列与补外键。幂等，可重复执行。

    必须在 ``create_all`` 之后调用：新建库此时结构已是最新，各补丁会因
    "已存在"被跳过；老库则在这里补上模型演进新增的列与约束。

    只吞"已存在"类错误，其余错误一律抛出。早期版本把异常全部 pass 掉，
    导致补列失败也无任何提示——库与模型长期不一致（列缺失最终表现为
    接口 500）却查不出原因。
    """
    async with engine.begin() as conn:
        for ddl in _PATCHES:
            try:
                await conn.execute(text(ddl))
                print("补丁生效:", ddl[:60])
            except Exception as exc:
                code = _errno(exc)
                if code in _ALREADY_DONE:
                    print(f"跳过（{_ALREADY_DONE[code]}）:", ddl[:60])
                else:
                    print("补丁失败:", ddl)
                    raise


async def fix_datetime_precision() -> None:
    """把参与时间比较 / 排序的列升级为 DATETIME(6) 微秒精度（幂等）。

    只改精度不足的列：先查 information_schema，COLUMN_TYPE 为 datetime
    （秒级）才执行 MODIFY；已是 datetime(6) 或列不存在则跳过。
    """
    async with engine.begin() as conn:
        for table, column in _PRECISION_COLUMNS:
            row = await conn.execute(
                text(
                    "SELECT COLUMN_TYPE FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() "
                    "AND TABLE_NAME = :t AND COLUMN_NAME = :c"
                ),
                {"t": table, "c": column},
            )
            col_type = row.scalar()
            if col_type is None:
                print(f"跳过（列不存在）: {table}.{column}")
            elif col_type.lower() == "datetime":
                await conn.execute(
                    text(
                        f"ALTER TABLE {table} "
                        f"MODIFY COLUMN {column} DATETIME(6) NOT NULL"
                    )
                )
                print(f"精度补丁生效: {table}.{column} -> DATETIME(6)")
            else:
                print(f"跳过（已是微秒精度）: {table}.{column} = {col_type}")


async def main() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("建表完成")

    # 建表之后再补：新建库无需补丁，老库在此补齐（顺序不能颠倒，
    # 否则新库里表还不存在，ALTER 会直接失败）
    await patch_existing_tables()
    await fix_datetime_precision()

    async with AsyncSessionLocal() as db:
        users = []
        for item in DEMO_USERS:
            password = item.pop("password")
            user = await db.scalar(
                select(User).where(User.username == item["username"])
            )
            if user is None:
                user = User(**item, password_hash=hash_password(password))
                db.add(user)
                await db.flush()
                print(f"创建用户 {item['username']}")
            else:
                # 已存在的账号也要同步管理员标记（幂等）
                user.is_admin = item.get("is_admin", False)
                print(f"同步用户 {item['username']} is_admin={user.is_admin}")
            users.append(user)
        await db.commit()

        # 规则机器人虚拟账号（is_bot，无学号，不开放注册）。
        # 它的密码哈希只是满足表结构：登录接口会拒绝 is_bot 账号（routers/auth.py），
        # 所以这里填什么都可以，也不需要维护。机器人的指令、关键词与增删改办法
        # 见 services/bot_service.py 的模块注释。
        bot = await db.scalar(select(User).where(User.username == "helper_bot"))
        if bot is None:
            bot = User(
                username="helper_bot",
                password_hash=hash_password("bot-no-login-000"),  # 占位，不可用于登录
                nickname="小助手",
                is_bot=True,
                bio="规则机器人：发送 /help 查看指令",
            )
            db.add(bot)
            await db.flush()
            print("创建机器人 helper_bot")

        conv = await db.scalar(select(Conversation).where(Conversation.id == 1))
        if conv is None:
            conv = Conversation(
                id=1,
                type="group",
                name="W1 联调测试群",
                owner_id=users[0].id,
                description="用于验证两个窗口互发消息",
            )
            db.add(conv)
            await db.flush()
            print("创建演示会话 id=1")

        for u in users:
            exists = await db.scalar(
                select(ConversationMember).where(
                    ConversationMember.conversation_id == conv.id,
                    ConversationMember.user_id == u.id,
                )
            )
            if exists is None:
                db.add(
                    ConversationMember(
                        conversation_id=conv.id,
                        user_id=u.id,
                        role="owner" if u.id == users[0].id else "member",
                    )
                )
        await db.commit()

    print("初始化完成：可用 alice / bob 登录，密码均为 123456，会话 id = 1")

    # 显式释放连接池：否则进程退出时事件循环已关闭，aiomysql 析构会打印
    # "RuntimeError: Event loop is closed" 噪音，容易被误判为初始化失败。
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
