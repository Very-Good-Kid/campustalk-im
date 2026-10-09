"""治理域：举报提交与管理员处置。"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services import bus
from app.deps import get_current_user
from app.models import Message, Report, User

router = APIRouter(prefix="/api/reports", tags=["reports"])


class ReportIn(BaseModel):
    """提交举报入参：举报对象是**具体的一条消息**（本系统不支持举报用户）。"""

    message_id: int
    reason: str = Field(min_length=1, max_length=200)


class ReportActionIn(BaseModel):
    """处置入参：``action`` 是举报结论，``punish`` 决定是否顺带封禁消息作者。"""

    action: str  # resolved / rejected
    punish: str = "none"  # none / ban —— resolved 时可一并封禁被举报消息的发布者


async def _require_admin(current: User) -> None:
    """本模块的管理员校验。

    与 admin.py 使用 ``deps.require_admin`` 依赖不同：这里需要拿到当前用户对象
    写 ``handled_by``（处置留痕），故写成接收用户对象的显式校验函数。
    """
    if not current.is_admin:
        raise HTTPException(status_code=403, detail="仅管理员可执行此操作")


@router.post("", status_code=201)
async def create_report(
    body: ReportIn,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """提交举报：写一条 pending 记录，等待管理员处置。

    同一举报人对同一条消息同时只允许存在一条待处理举报（重复提交返回 400）；
    已被处理过的消息可以再次举报。
    """
    msg = await db.get(Message, body.message_id)
    if msg is None:
        raise HTTPException(status_code=404, detail="被举报的消息不存在")

    # 防重复：同一人对同一条消息的待处理举报只保留一条
    dup = await db.scalar(
        select(Report).where(
            Report.reporter_id == current.id,
            Report.message_id == body.message_id,
            Report.status == "pending",
        )
    )
    if dup is not None:
        raise HTTPException(status_code=400, detail="你已举报过该消息，请等待处理")

    report = Report(reporter_id=current.id, message_id=body.message_id, reason=body.reason)
    db.add(report)
    await db.commit()
    return {"ok": True, "report_id": report.id}


@router.get("")
async def report_list(
    status: str = Query(default="pending", pattern="^(pending|resolved|rejected|all)$"),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """管理员查看举报列表（默认只看待处理，最多返回 50 条，按时间倒序）。

    只回被举报消息的前 50 字摘要，**不提供全文与上下文浏览**——
    这是"管理员不浏览任意用户聊天记录"这一隐私边界的落地。
    """
    await _require_admin(current)

    stmt = select(Report).order_by(Report.created_at.desc())
    if status != "all":
        stmt = stmt.where(Report.status == status)
    rows = await db.execute(stmt.limit(50))

    out = []
    for r in rows.scalars():
        reporter = await db.get(User, r.reporter_id)
        msg = await db.get(Message, r.message_id)
        out.append(
            {
                "report_id": r.id,
                "reporter": reporter.nickname if reporter else str(r.reporter_id),
                "message_id": r.message_id,
                "message_content": (msg.content or "")[:50] if msg else "",
                "reason": r.reason,
                "status": r.status,
                "handled_by": r.handled_by,
                "handled_at": r.handled_at.isoformat() if r.handled_at else None,
                "created_at": r.created_at.isoformat(),
            }
        )
    return out


@router.put("/{report_id}")
async def handle_report(
    report_id: int,
    body: ReportActionIn,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """处置举报：更新状态并记录处理人与时间；可选顺带封禁被举报消息的作者。

    ``punish="ban"`` 复用账号禁用机制（登录 / 鉴权 / WS 握手三处同时生效），
    并写入 disabled_at / disabled_by 留痕。三类账号不可封禁：
    当前登录的管理员自己、其他管理员、系统机器人（返回 400 并说明原因）。
    """
    await _require_admin(current)

    report = await db.get(Report, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="举报不存在")
    if report.status != "pending":
        raise HTTPException(status_code=400, detail="该举报已处理")

    if body.action not in ("resolved", "rejected"):
        raise HTTPException(status_code=400, detail="action 只能是 resolved 或 rejected")
    if body.punish not in ("none", "ban"):
        raise HTTPException(status_code=400, detail="punish 只能是 none 或 ban")

    # 实质处置：封禁被举报消息的发布者。
    # 复用账号禁用机制（登录 / 鉴权 / WS 握手三处同时生效），并留痕便于追责。
    banned = None
    if body.action == "resolved" and body.punish == "ban":
        msg = await db.get(Message, report.message_id)
        target = await db.get(User, msg.sender_id) if msg else None
        if target is None:
            raise HTTPException(status_code=404, detail="被举报消息的发布者不存在")
        if target.id == current.id:
            raise HTTPException(status_code=400, detail="不能封禁当前登录的管理员账号")
        if target.is_admin:
            raise HTTPException(status_code=400, detail="不能封禁管理员账号")
        if target.is_bot:
            raise HTTPException(status_code=400, detail="系统机器人账号不可封禁")
        target.is_active = False
        target.disabled_at = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
        target.disabled_by = current.id
        banned = target.nickname

    report.status = body.action
    report.handled_by = current.id
    report.handled_at = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    await db.commit()

    # 处置回执：只推举报人一个（结论对被举报方不公开，避免纠纷）。
    # 走总线 system_notice 通道；举报人不在线则错过——结果在"我的举报"列表里始终可查，
    # 帧只是省一次刷新的锦上添花
    await bus.publish(
        [report.reporter_id],
        {"type": "system_notice", "data": {
            "event": "report_handled",
            "report_id": report.id,
            "status": report.status,
            "handled_at": report.handled_at.isoformat(),
        }},
    )
    return {"ok": True, "status": report.status, "banned": banned}
