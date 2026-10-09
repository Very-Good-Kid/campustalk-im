"""模型层汇总导出。

保持 `from app.models import User, Base, ...` 的旧用法兼容；
新代码推荐按域导入，如 `from app.models.user import User`。

字段定义与《系统设计》2.4.3 物理结构完全一致，改表请同步改文档。
"""
from app.models.base import Base, utcnow
from app.models.content import Comment, Like, Post
from app.models.conversation import Conversation, ConversationMember
from app.models.friendship import Friendship
from app.models.governance import Report, SensitiveWord, StudentIdRequest
from app.models.group_request import GroupJoinRequest
from app.models.message import Message
from app.models.user import User

__all__ = [
    "Base",
    "utcnow",
    "User",
    "Friendship",
    "Conversation",
    "ConversationMember",
    "Message",
    "Post",
    "Comment",
    "Like",
    "Report",
    "SensitiveWord",
    "StudentIdRequest",
    "GroupJoinRequest",
]
