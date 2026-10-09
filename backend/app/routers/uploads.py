"""内容域：图片 / 文件上传。

铁律：数据库只存 URL、文件名与大小，绝不把二进制写进库或 WebSocket 帧。
前端校验只是体验，服务端必须重复校验。
"""
from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel

from app.config import settings
from app.deps import get_current_user
from app.models import User

router = APIRouter(prefix="/api/upload", tags=["upload"])

IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif"}
IMAGE_MAX = 10 * 1024 * 1024         # 10MB：手机拍照普遍 3-8MB，2MB 基本传不了东西
FILE_MAX = 50 * 1024 * 1024          # 50MB：覆盖常见课件与压缩包
# 文件类型白名单，不在名单内一律拒绝
FILE_TYPES = {
    "text/plain",
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/zip",
    "audio/mpeg",
    "audio/wav",
    "video/mp4",
}

# MIME → 落盘扩展名。扩展名一律由服务端按 MIME 推导，
# 绝不沿用客户端传来的原始文件名，避免伪造扩展名（如把 .html 伪装成图片）。
EXT_BY_TYPE = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "text/plain": ".txt",
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/zip": ".zip",
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "video/mp4": ".mp4",
}


class UploadOut(BaseModel):
    """上传响应：前端把 ``url`` 作为消息的 content 发出，二进制不进 WS 帧。

    ``file_name`` 是原始文件名，仅用于展示与下载时还原；
    实际落盘名是 uuid（见 EXT_BY_TYPE 说明）。
    """

    url: str
    file_name: str
    file_size: int
    kind: str


@router.post("", response_model=UploadOut)
async def upload(
    file: UploadFile,
    current: User = Depends(get_current_user),
):
    """接收单个文件并落盘，返回可公开访问的 URL。

    参数:
        file: multipart 文件字段。类型判定**只认 MIME**（``file.content_type``）。

    返回:
        UploadOut，其中 ``kind`` = image / file，前端据此决定内联预览还是下载卡片。

    异常:
        400 —— 类型不在白名单，或超过该类型的体积上限（图片 10MB / 文件 50MB）。

    注意:
        - 需登录才能上传（本系统所有上传都发生在会话内）；
        - 落盘名用 uuid，避免路径穿越与重名覆盖；
        - 前端已做过同样的类型与大小预检，但那只是体验优化，这一层才是安全边界。
    """
    content_type = file.content_type or ""

    if content_type in IMAGE_TYPES:
        kind, max_size = "image", IMAGE_MAX
    elif content_type in FILE_TYPES:
        kind, max_size = "file", FILE_MAX
    else:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型：{content_type}")

    data = await file.read()
    if len(data) > max_size:
        limit_mb = max_size // (1024 * 1024)
        raise HTTPException(status_code=400, detail=f"文件超过 {limit_mb}MB 上限")

    ext = EXT_BY_TYPE.get(content_type, "")
    safe_name = f"{uuid.uuid4().hex}{ext}"

    os.makedirs(settings.upload_dir, exist_ok=True)
    with open(os.path.join(settings.upload_dir, safe_name), "wb") as f:
        f.write(data)

    return UploadOut(
        url=f"/uploads/{safe_name}",
        file_name=file.filename or safe_name,
        file_size=len(data),
        kind=kind,
    )
