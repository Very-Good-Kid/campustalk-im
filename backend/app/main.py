"""应用装配入口：把配置、数据库、模型与各域路由组装成一个 FastAPI 实例。

装配顺序（改这里时请保持该顺序与注释）：

1. ``lifespan`` 建表 —— 启动时 create_all 补建缺失的表，退出时释放连接池；
2. CORS —— 开发期放开，浏览器侧实际走 Vite 同源代理（见 frontend/vite.config.js），
   生产按同样方式用 Nginx 反代即可，因此不依赖这里的 CORS 配置；
3. 注册 10 个路由模块 —— 清单见 routers/__init__.py；
4. 挂载 ``/uploads`` 静态目录 —— 聊天图片与文件由浏览器直接取。
   注意：学号证明材料**不在**其中（存 ``settings.verify_dir``，未挂载静态路由，
   只能经管理员鉴权接口读取，见 routers/verifications.py）。

启动方式：``uvicorn app.main:app --host 127.0.0.1 --port 5109``
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import engine
from app.models import Base
from app.routers import (
    admin,
    auth,
    channels,
    conversations,
    friends,
    messages,
    reports,
    uploads,
    verifications,
    ws,
)
from app.services import bus, wordlist_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：探活总线 → 建表 → 挂订阅任务；退出时释放连接。

    Redis 是硬依赖：ping 失败直接抛异常让应用拒绝启动——"起来了但
    广播静默失效"比"起不来"难排查得多，宁可启动即失败。
    建表用途是**补建新表**（幂等），字段级变更仍需 init_db.py 的补列逻辑或
    手工 DDL，create_all 不会给已存在的表加列。
    """
    await bus.ping()
    # 冷启动先把上一代进程残留的在线计数清零，presence 从"全员离线"重建
    await bus.reset_online()
    # 异步建表：MySQL 下必须用 run_sync，不能用同步的 create_all
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # 敏感词库：空表先从旧文件播种 → 读库建立本进程前缀树 → 接线控制帧处理器
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        await wordlist_service.seed_if_empty(db)
        await wordlist_service.refresh_local(db)
    wordlist_service.install_handler()
    bus.start_subscriber()
    yield
    await bus.stop_subscriber()
    await engine.dispose()


app = FastAPI(title="CampusTalk", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(verifications.router)
app.include_router(friends.router)
app.include_router(conversations.router)
app.include_router(channels.router)
app.include_router(messages.router)
app.include_router(uploads.router)
app.include_router(reports.router)
app.include_router(ws.router)

# 上传的图片与文件通过静态目录暴露，数据库只存 URL。
# 目录必须先存在：StaticFiles 挂载时会检查目录，缺失会让整个应用起不来。
# （这行原先藏在 core/sensitive.py 的模块末尾，属于放错地方的副作用）
os.makedirs(settings.upload_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=settings.upload_dir), name="uploads")


@app.get("/api/health")
async def health():
    """存活探针：仅表示进程能响应请求，**不检查数据库连通性**。

    部署脚本与一键启动可据此判断服务是否已起来，重不重数据库不在此职责内。
    """
    return {"status": "ok"}
