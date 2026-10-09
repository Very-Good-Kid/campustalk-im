"""Schema 层汇总导出。

保持 `from app.schemas import UserOut, ...` 的旧用法兼容；
所有 Out 模型统一开 from_attributes：允许直接从 SQLAlchemy ORM 对象校验，
漏掉这个会导致 model_validate(orm) 直接 500（已踩坑：用户搜索接口）。
"""
from app.schemas.auth import (
    ChangePasswordIn,
    LoginIn,
    ProfileUpdateIn,
    RegisterIn,
    TokenOut,
    UserOut,
)
from app.schemas.social import (
    CardUserOut,
    ConversationBriefOut,
    FriendOut,
    GroupPreviewOut,
    GroupRequestOut,
    MemberOut,
    MessageOut,
    RequestOut,
    UserBriefOut,
)

__all__ = [
    "RegisterIn",
    "LoginIn",
    "TokenOut",
    "UserOut",
    "ProfileUpdateIn",
    "ChangePasswordIn",
    "UserBriefOut",
    "FriendOut",
    "RequestOut",
    "MemberOut",
    "MessageOut",
    "ConversationBriefOut",
    "GroupRequestOut",
    "GroupPreviewOut",
    "CardUserOut",
]
