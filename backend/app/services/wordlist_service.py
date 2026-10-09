"""敏感词库服务：数据库 ↔ 进程缓存的唯一同步通道。

职责分工（core/sensitive.py 保持纯同步的原因就在这）：
- 本模块负责**读库与推消息**：启动 seed、管理端增删后的本地刷新、
  经总线控制帧通知其他实例；
- core/sensitive.py 负责**判定**：只认 set_words 注入进来的词表，
  不感知数据库的存在——热路径（每条消息都要过一遍）零 IO。

多实例一致性：管理端改词后先刷本实例、再 publish_control 让其他
实例各自重建缓存。控制帧丢失（Redis 恰好抖动）时新旧词表最多
分歧到下一次改词或重启，属演示规模可接受的最终一致。
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import sensitive
from app.models import SensitiveWord
from app.services import bus

logger = logging.getLogger(__name__)

_SEEDED = False  # 本进程是否已做过"读库 or 文件导入"的初始化


async def _file_words() -> list[str]:
    """旧词库文件内容（仅建库种子用，运行期不再读）。"""
    return sensitive.load_words()


async def seed_if_empty(db: AsyncSession) -> None:
    """表为空时把 sensitive_words.txt 一次性导入（幂等，进程内只做一次）。

    文件本身不删除不改动：它仍是"出厂词库"的版本化载体，
    新环境 clone 后跑一次即有基础词表，无需手工建数据。
    """
    global _SEEDED
    if _SEEDED:
        return
    count = await db.scalar(select(SensitiveWord.id).limit(1))
    if count is None:
        words = await _file_words()
        db.add_all(SensitiveWord(word=w) for w in dict.fromkeys(words))
        await db.commit()
        logger.info("敏感词库初始化：从文件导入 %d 条", len(words))
    _SEEDED = True


async def refresh_local(db: AsyncSession) -> int:
    """读全表并注入进程缓存，返回词数。"""
    words = list((await db.scalars(select(SensitiveWord.word))).all())
    sensitive.set_words(words)
    return len(words)


async def reload_all_instances() -> None:
    """管理端写库后调用：先刷本实例，再广播控制帧让其他实例跟进。

    本实例先刷是刻意的顺序——若反过来先广播，自己反而是最后（或
    依赖自己订阅自己）生效；先刷保证操作者立刻看到新词表生效。
    调用方需已 commit。
    """
    # 局部导入避免 database ↔ bus 循环依赖
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        await refresh_local(db)
    await bus.publish_control(bus.CONTROL_RELOAD_WORDS)


async def _handler_reload() -> None:
    """控制帧处理器：开独立会话重读词表（订阅循环里没有现成 db）。"""
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        n = await refresh_local(db)
    logger.info("收到总线控制帧，敏感词缓存已重建（%d 条）", n)


def install_handler() -> None:
    """lifespan 启动时注册控制帧处理器（重复注册覆盖，无害）。"""
    bus.register_control_handler(bus.CONTROL_RELOAD_WORDS, _handler_reload)
