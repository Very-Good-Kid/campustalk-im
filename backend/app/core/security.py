"""密码哈希与 JWT。

注意：bcrypt 有 72 字节上限，超长密码需在前置校验拦掉。
"""
from __future__ import annotations

import datetime as dt

import bcrypt
import jwt

from app.config import settings

ALGORITHM = "HS256"


def hash_password(plain: str) -> str:
    """生成 bcrypt 哈希（内含随机盐）供入库，明文绝不落库。

    注意：bcrypt 只使用前 72 字节，超长密码会被静默截断，
    因此入参长度已在 schemas 层限制为 max_length=72。
    """
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """校验明文与库中哈希是否匹配。

    库里的 hashed 可能是脏数据（手工改库等），bcrypt 会抛 ValueError，
    此处统一按"校验失败"处理，避免把脏数据变成接口 500。
    """
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(user_id: int) -> str:
    """签发访问令牌：payload 只放 sub（用户 id）与 exp（过期时间）。

    刻意不放昵称 / 权限等信息——JWT 无状态、签发后无法撤回，
    用户资料一律以服务端为准实时查询（见 deps.get_current_user），
    避免"改了资料但令牌里还是旧值"。
    """
    expire = dt.datetime.now(dt.timezone.utc) + dt.timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> int | None:
    """解析失败一律返回 None，不抛异常，方便 WebSocket 侧直接关连接。"""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        return int(payload["sub"])
    except Exception:
        return None
