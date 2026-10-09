"""异步数据库引擎与会话。

要点：
1. 使用 create_async_engine + aiomysql，WebSocket 中绝不可使用同步驱动。
2. pool_pre_ping 防止 MySQL 长时间空闲后踢连接导致的报错。
3. pool_recycle 必须小于 MySQL 的 wait_timeout（默认 8 小时）。
"""
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
    pool_recycle=3600,
)

AsyncSessionLocal = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db():
    """FastAPI 依赖：每个请求一个会话，结束后自动关闭。"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
