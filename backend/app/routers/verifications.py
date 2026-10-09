"""实名变更域：学号变更的申请 — 审核闭环。

设计要点：
1. 学号是"后台实名"的载体，不允许自助修改；但转专业、留级、教务录入错误确实存在，
   因此需要一条"用户提交证明材料 → 管理员核实 → 通过后写入"的通道。
2. 证明材料（学生证照片 / 学信网截图）含姓名、学号与证件照，属敏感个人信息，
   存放在**未挂载静态路由**的私密目录，只能通过管理员鉴权接口读取。
3. 遵循数据最小化：审核结论作出后即删除证明材料原件，仅保留申请与审核记录。
"""
from __future__ import annotations

import datetime as dt
import os
import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.deps import get_current_user
from app.models import StudentIdRequest, User

router = APIRouter(prefix="/api/verifications", tags=["verifications"])

# 证明材料允许的类型与大小（证件照一般 1-5MB，给到 10MB 足够）
PROOF_TYPES = {"image/jpeg", "image/png", "image/webp"}
PROOF_MAX = 10 * 1024 * 1024
EXT_BY_TYPE = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


def _ensure_dir() -> str:
    """确保证明材料目录存在（首次运行时创建），返回目录路径。"""
    os.makedirs(settings.verify_dir, exist_ok=True)
    return settings.verify_dir


def _remove_proof(proof_file: str | None) -> None:
    """删除证明材料原件（审核结论作出后调用，落实数据最小化）。

    只取 basename 再拼接目录，防止脏数据里的路径片段越出私密目录；
    删除失败静默忽略——文件清理不应影响审核结果落库。
    """
    if not proof_file:
        return
    path = os.path.join(settings.verify_dir, os.path.basename(proof_file))
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


# ---------- 用户侧：提交申请 ----------


@router.post("/student-id", status_code=status.HTTP_201_CREATED)
async def submit_request(
    new_student_id: str = Form(min_length=1, max_length=32),
    user_note: str | None = Form(default=None, max_length=200),
    proof: UploadFile = File(...),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """提交学号变更申请：必须附带证明材料（学生证照片 / 学信网截图）。"""
    new_sid = new_student_id.strip()

    if current.student_id and new_sid == current.student_id:
        raise HTTPException(status_code=400, detail="新学号与当前学号相同")

    # 提前校验唯一性：避免用户白等一轮审核
    conflict = await db.scalar(
        select(User).where(User.student_id == new_sid, User.id != current.id)
    )
    if conflict is not None:
        raise HTTPException(status_code=400, detail="该学号已被其他账号使用")

    # 一人同时只允许一个待审核申请，防止重复提交堆积
    pending = await db.scalar(
        select(StudentIdRequest).where(
            StudentIdRequest.user_id == current.id,
            StudentIdRequest.status == "pending",
        )
    )
    if pending is not None:
        raise HTTPException(
            status_code=400, detail="你已有一个待审核的申请，请等待管理员处理"
        )

    if proof.content_type not in PROOF_TYPES:
        raise HTTPException(status_code=400, detail="证明材料仅支持 jpg / png / webp 图片")

    data = await proof.read()
    if len(data) > PROOF_MAX:
        raise HTTPException(status_code=400, detail="证明材料不能超过 10MB")
    if not data:
        raise HTTPException(status_code=400, detail="证明材料为空")

    safe_name = f"{uuid.uuid4().hex}{EXT_BY_TYPE[proof.content_type]}"
    with open(os.path.join(_ensure_dir(), safe_name), "wb") as f:
        f.write(data)

    req = StudentIdRequest(
        user_id=current.id,
        old_student_id=current.student_id,
        new_student_id=new_sid,
        proof_file=safe_name,
        user_note=user_note,
    )
    db.add(req)
    await db.commit()
    await db.refresh(req)
    return {
        "request_id": req.id,
        "status": req.status,
        "detail": "申请已提交，等待管理员核实证明材料",
    }


@router.get("/my")
async def my_requests(
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """我提交的学号变更申请及处理进展。"""
    rows = await db.execute(
        select(StudentIdRequest)
        .where(StudentIdRequest.user_id == current.id)
        .order_by(StudentIdRequest.created_at.desc())
        .limit(10)
    )
    out = []
    for r in rows.scalars():
        reviewer = await db.get(User, r.reviewer_id) if r.reviewer_id else None
        out.append(
            {
                "request_id": r.id,
                "old_student_id": r.old_student_id,
                "new_student_id": r.new_student_id,
                "user_note": r.user_note,
                "status": r.status,
                "review_note": r.review_note,
                "reviewer": reviewer.nickname if reviewer else None,
                "created_at": r.created_at.isoformat(),
                "reviewed_at": r.reviewed_at.isoformat() if r.reviewed_at else None,
            }
        )
    return out


# ---------- 管理员侧：审核 ----------


class ReviewBody(BaseModel):
    action: str  # approve / reject
    note: str | None = Field(default=None, max_length=200)


@router.get("")
async def list_requests(
    req_status: str = "pending",
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """管理员查看学号变更申请列表。"""
    if not current.is_admin:
        raise HTTPException(status_code=403, detail="仅管理员可查看")

    rows = await db.execute(
        select(StudentIdRequest)
        .where(StudentIdRequest.status == req_status)
        .order_by(StudentIdRequest.created_at.asc())
        .limit(50)
    )
    out = []
    for r in rows.scalars():
        user = await db.get(User, r.user_id)
        out.append(
            {
                "request_id": r.id,
                "user_id": r.user_id,
                "applicant": user.nickname if user else None,
                "username": user.username if user else None,
                "old_student_id": r.old_student_id,
                "new_student_id": r.new_student_id,
                "user_note": r.user_note,
                "created_at": r.created_at.isoformat(),
                "has_proof": bool(r.proof_file),
            }
        )
    return out


@router.get("/{request_id}/proof")
async def view_proof(
    request_id: int,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """管理员查看证明材料。

    这是唯一能读到证明材料原件的入口——私密目录未挂载静态路由，
    因此即便拿到文件名也无法绕过鉴权直接访问。
    """
    if not current.is_admin:
        raise HTTPException(status_code=403, detail="仅管理员可查看证明材料")

    req = await db.get(StudentIdRequest, request_id)
    if req is None or not req.proof_file:
        raise HTTPException(status_code=404, detail="证明材料不存在或已按最小化原则清除")

    path = os.path.join(settings.verify_dir, os.path.basename(req.proof_file))
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="证明材料已清除")
    return FileResponse(path)


@router.post("/{request_id}/review")
async def review_request(
    request_id: int,
    body: ReviewBody,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """管理员审核：通过则写入新学号并留痕，驳回需填写理由。

    无论通过或驳回，审核结论作出后即删除证明材料原件（数据最小化）。
    """
    if not current.is_admin:
        raise HTTPException(status_code=403, detail="仅管理员可执行审核")

    req = await db.get(StudentIdRequest, request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="申请不存在")
    if req.status != "pending":
        raise HTTPException(status_code=400, detail="该申请已处理完毕")

    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    req.reviewer_id = current.id
    req.reviewed_at = now

    if body.action == "approve":
        target = await db.get(User, req.user_id)
        if target is None:
            raise HTTPException(status_code=404, detail="申请人账号不存在")
        # 审核时二次校验：提交到审核之间可能有别人占用了该学号
        conflict = await db.scalar(
            select(User).where(
                User.student_id == req.new_student_id, User.id != req.user_id
            )
        )
        if conflict is not None:
            raise HTTPException(status_code=400, detail="该学号已被其他账号使用，请驳回")

        target.student_id = req.new_student_id
        target.student_id_updated_at = now
        target.student_id_updated_by = current.id
        req.status = "approved"
        req.review_note = body.note or "材料核实通过"
    elif body.action == "reject":
        if not body.note:
            raise HTTPException(status_code=400, detail="驳回必须填写理由")
        req.status = "rejected"
        req.review_note = body.note
    else:
        raise HTTPException(status_code=400, detail="action 只支持 approve / reject")

    await db.commit()
    # 数据最小化：结论作出后清除证明材料原件，仅保留申请与审核记录
    _remove_proof(req.proof_file)
    req.proof_file = ""
    await db.commit()

    return {"ok": True, "status": req.status, "reviewed_by": current.nickname}
