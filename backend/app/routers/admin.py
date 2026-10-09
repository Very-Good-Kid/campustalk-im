"""管理域：管理端所需的账号治理与统计接口（设计 2.3.9）。

安全边界：所有端点统一走 `require_admin` 依赖（定义在 app/deps.py）——
前端隐藏入口与路由守卫都只是体验层，绕过它们直接调接口同样被 403 拒绝。

隐私边界（有意不做的事）：本模块**不提供浏览任意用户聊天记录的能力**，
管理员只能经由「举报处置」看到被举报的那一条消息（见 routers/reports.py）。
这是权限最小化与数据最小化原则的落地。

禁用三处生效点（缺一不可）：登录接口（auth.py）、鉴权依赖（deps.py）、
WebSocket 握手（ws.py）。本模块只负责改写 `is_active` 并留痕。
"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.database import get_db
from app.deps import require_admin
from app.models import Conversation, Message, Report, SensitiveWord, StudentIdRequest, User
from app.services import bus, wordlist_service

router = APIRouter(prefix="/api/admin", tags=["admin"])


class StudentIdIn(BaseModel):
    """管理员直改学号的入参（改写会记录修改人与时间，供审计）。"""

    student_id: str = Field(min_length=1, max_length=32)


class UserStatusIn(BaseModel):
    """禁用 / 启用账号入参：``active=False`` 即禁用。"""

    active: bool


class ResetPasswordIn(BaseModel):
    """重置密码入参（上限 72 字节以适配 bcrypt 的截断规则）。"""

    new_password: str = Field(min_length=6, max_length=72)


class GrantAdminIn(BaseModel):
    """授予 / 撤销管理员权限入参。"""

    is_admin: bool


class WordIn(BaseModel):
    """新增敏感词入参（多字少字都没意义，限 1–50 字符）。"""

    word: str = Field(min_length=1, max_length=50)


def _now() -> dt.datetime:
    """统一取 UTC 朴素时间，口径与 ``models.base.utcnow`` 一致，用于留痕字段。"""
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def _user_row(u: User) -> dict:
    """把 User 转成管理端账号列表的一行。

    时间字段转 isoformat 便于前端直接解析；**不含 password_hash**——
    管理端同样没有查看密码的能力（重置只能设新值，不能读旧值）。
    """
    return {
        "user_id": u.id,
        "username": u.username,
        "nickname": u.nickname,
        "student_id": u.student_id,
        "department": u.department,
        "class_name": u.class_name,
        "is_admin": u.is_admin,
        "is_bot": u.is_bot,
        "is_active": u.is_active,
        "disabled_at": u.disabled_at.isoformat() if u.disabled_at else None,
        "created_at": u.created_at.isoformat(),
    }


def _last_days_bounds(days: int) -> list[tuple[dt.date, dt.datetime, dt.datetime]]:
    """近 ``days`` 天（按演示机器本地时区）的 [当天0点, 次日0点) UTC 朴素边界。

    库内时间统一 UTC 朴素存储，看板口径要跟"管理员今天看到的本地日"对齐，
    先按本地日算边界再转 UTC。naive astimezone() 按系统本地时区解释，
    与 _now() 同口径——不硬编偏移量。
    """
    out = []
    today_local = dt.datetime.now().date()
    for i in range(days - 1, -1, -1):
        d = today_local - dt.timedelta(days=i)
        start_local = dt.datetime.combine(d, dt.time())
        s = start_local.astimezone(dt.timezone.utc)
        e = (start_local + dt.timedelta(days=1)).astimezone(dt.timezone.utc)
        out.append((d, s.replace(tzinfo=None), e.replace(tzinfo=None)))
    return out


@router.get("/overview")
async def overview(
    current: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """总览：计数 + 活跃度看板（在线/日活/近 7 日消息趋势）。

    仍然只做统计，**不展示任何用户内容**。趋势按小库逐日 COUNT（7 条轻量
    查询），数据量上去后可换成分组一条 SQL，演示量级不预优化。
    """

    async def count(stmt) -> int:
        return int(await db.scalar(stmt) or 0)

    bounds = _last_days_bounds(7)
    trend = [
        {
            "date": d.strftime("%m-%d"),
            "count": await count(
                select(func.count())
                .select_from(Message)
                .where(Message.created_at >= s, Message.created_at < e)
            ),
        }
        for d, s, e in bounds
    ]
    day_start = bounds[-1][1]
    return {
        "pending_reports": await count(
            select(func.count()).select_from(Report).where(Report.status == "pending")
        ),
        "pending_verifications": await count(
            select(func.count())
            .select_from(StudentIdRequest)
            .where(StudentIdRequest.status == "pending")
        ),
        "users_total": await count(
            select(func.count()).select_from(User).where(User.is_bot == False)  # noqa: E712
        ),
        "users_active": await count(
            select(func.count())
            .select_from(User)
            .where(User.is_bot == False, User.is_active == True)  # noqa: E712
        ),
        "users_disabled": await count(
            select(func.count()).select_from(User).where(User.is_active == False)  # noqa: E712
        ),
        "users_admin": await count(
            select(func.count()).select_from(User).where(User.is_admin == True)  # noqa: E712
        ),
        "messages_total": await count(select(func.count()).select_from(Message)),
        "conversations_total": await count(select(func.count()).select_from(Conversation)),
        "channels_total": await count(
            select(func.count()).select_from(Conversation).where(Conversation.type == "channel")
        ),
        # ---- 活跃度看板 ----
        "online_now": await bus.online_count(),
        "messages_today": trend[-1]["count"],
        # 日活口径：今天发过言的用户（机器人不计，distinct 天然去重多渠道）
        "dau_today": await count(
            select(func.count(func.distinct(Message.sender_id)))
            .where(Message.created_at >= day_start, Message.sender_type == "user")
        ),
        "trend_7d": trend,
    }


@router.get("/users")
async def list_users(
    q: str | None = Query(default=None, max_length=50),
    status: str = Query(default="all", pattern="^(all|active|disabled)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """账号列表：按用户名 / 昵称 / 学号模糊搜索，按状态筛选，分页返回。"""
    stmt = select(User).where(User.is_bot == False)  # noqa: E712
    if q:
        kw = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(User.username.like(kw), User.nickname.like(kw), User.student_id.like(kw))
        )
    if status == "active":
        stmt = stmt.where(User.is_active == True)  # noqa: E712
    elif status == "disabled":
        stmt = stmt.where(User.is_active == False)  # noqa: E712

    total = int(await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = await db.execute(
        stmt.order_by(User.id.asc()).offset((page - 1) * page_size).limit(page_size)
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_user_row(u) for u in rows.scalars()],
    }


@router.put("/users/{user_id}/status")
async def set_user_status(
    user_id: int,
    body: UserStatusIn,
    current: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """禁用 / 启用账号，并记录禁用时间与操作人。

    禁止禁用自己（否则立即把自己锁在门外）；系统机器人账号不可禁用。
    """
    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if target.id == current.id:
        raise HTTPException(status_code=400, detail="不能禁用当前登录的管理员账号")
    if target.is_bot:
        raise HTTPException(status_code=400, detail="系统机器人账号不可禁用")

    target.is_active = body.active
    if body.active:
        target.disabled_at = None
        target.disabled_by = None
    else:
        target.disabled_at = _now()
        target.disabled_by = current.id
    await db.commit()
    return {"ok": True, "user_id": target.id, "is_active": target.is_active}


@router.post("/users/{user_id}/reset-password")
async def reset_password(
    user_id: int,
    body: ResetPasswordIn,
    current: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """重置用户密码。新密码同样以 bcrypt 哈希存储，绝不存明文。"""
    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    target.password_hash = hash_password(body.new_password)
    await db.commit()
    return {"ok": True, "user_id": target.id}


@router.put("/users/{user_id}/admin")
async def set_admin(
    user_id: int,
    body: GrantAdminIn,
    current: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """授予 / 撤销管理员权限。撤销自己会立即失去管理端访问权，故禁止。"""
    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if target.id == current.id and not body.is_admin:
        raise HTTPException(status_code=400, detail="不能撤销自己的管理员权限")
    target.is_admin = body.is_admin
    await db.commit()
    return {"ok": True, "user_id": target.id, "is_admin": target.is_admin}


@router.put("/users/{user_id}/student-id")
async def change_student_id(
    user_id: int,
    body: StudentIdIn,
    current: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """管理员修改学号。

    真实场景下应由用户提交教务证明、管理员核实后执行；
    本系统保留"审核通道 + 直改"两条路径，直改同样记录修改人与时间，便于审计。
    """
    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="用户不存在")

    new_sid = body.student_id.strip()
    if target.student_id == new_sid:
        raise HTTPException(status_code=400, detail="学号未发生变化")

    conflict = await db.scalar(
        select(User).where(User.student_id == new_sid, User.id != user_id)
    )
    if conflict is not None:
        raise HTTPException(status_code=400, detail="该学号已被其他账号使用")

    target.student_id = new_sid
    target.student_id_updated_at = _now()
    target.student_id_updated_by = current.id
    await db.commit()
    return {
        "ok": True,
        "user_id": user_id,
        "student_id": new_sid,
        "updated_by": current.nickname,
    }


# ---------- 敏感词库（10-02：从文件词库升级为数据库管理） ----------

@router.get("/sensitive-words")
async def list_sensitive_words(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """词库全量列表（按添加时间倒序）。词库量级几十到几百条，不分页。"""
    rows = (await db.scalars(
        select(SensitiveWord).order_by(SensitiveWord.created_at.desc(), SensitiveWord.id.desc())
    )).all()
    return [
        {
            "id": w.id,
            "word": w.word,
            "created_at": w.created_at.isoformat(),
            "created_by": w.created_by,
        }
        for w in rows
    ]


@router.post("/sensitive-words", status_code=201)
async def add_sensitive_word(
    body: WordIn,
    current: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """新增敏感词：写库后立即刷新本实例缓存并经总线通知其他实例。

    命中判定取**最长匹配**（core/sensitive.py），所以"开票"和"代开发票"
    共存时提示会优先报更准的那个，不存在"加短词屏蔽长词"的顾虑。
    """
    word = body.word.strip()
    if not word:
        raise HTTPException(status_code=400, detail="词不能为空白")
    dup = await db.scalar(select(SensitiveWord).where(SensitiveWord.word == word))
    if dup is not None:
        raise HTTPException(status_code=400, detail="该词已在词库中")
    db.add(SensitiveWord(word=word, created_by=current.id))
    await db.commit()
    await wordlist_service.reload_all_instances()
    return {"ok": True, "word": word}


@router.delete("/sensitive-words/{word_id}")
async def delete_sensitive_word(
    word_id: int,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """删除敏感词：同样走"本实例先刷＋控制帧广播"的同步链路。"""
    row = await db.get(SensitiveWord, word_id)
    if row is None:
        raise HTTPException(status_code=404, detail="词条不存在")
    await db.delete(row)
    await db.commit()
    await wordlist_service.reload_all_instances()
    return {"ok": True}
