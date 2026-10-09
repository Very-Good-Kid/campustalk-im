"""身份域 schema：注册 / 登录 / 资料。"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RegisterIn(BaseModel):
    """注册入参。这里只约束长度（如 bcrypt 的 72 字节上限），业务规则在 auth.py 校验。

    ``agree_terms`` 与 ``invite_code`` 是准入的两个开关：协议未勾选直接拒绝；
    ``INVITE_CODE`` 非空时邀请码必填（留空即开放注册）。
    """

    username: str = Field(min_length=4, max_length=50)
    password: str = Field(min_length=6, max_length=72)  # bcrypt 上限 72 字节
    confirm_password: str = Field(min_length=6, max_length=72)
    nickname: str = Field(min_length=1, max_length=50)
    student_id: str | None = Field(default=None, max_length=32)
    department: str | None = Field(default=None, max_length=100)
    class_name: str | None = Field(default=None, max_length=100)
    agree_terms: bool
    invite_code: str | None = Field(default=None, description="注册邀请码；服务端开启校验时必填")


class LoginIn(BaseModel):
    """登录入参：用户名 + 明文密码（服务端 bcrypt 比对）。

    用户名不存在与密码错误返回同一句提示，防止账号枚举。
    """

    username: str
    password: str


class TokenOut(BaseModel):
    """登录成功响应：令牌 + 首页展示所需的最小用户信息。

    只带 user_id / nickname / is_admin，完整资料由 ``GET /api/auth/me`` 拉取，
    避免"登录响应塞一整套资料"导致的字段漂移。
    """

    model_config = ConfigDict(from_attributes=True)

    access_token: str
    token_type: str = "bearer"
    user_id: int
    nickname: str
    is_admin: bool = False


class UserOut(BaseModel):
    """当前用户资料（注册响应、``GET /api/auth/me``）。

    刻意不含 ``password_hash``：任何接口都不得回显密码相关字段。
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    nickname: str
    student_id: str | None = None
    avatar_url: str | None = None
    bio: str | None = None
    department: str | None = None
    class_name: str | None = None
    is_admin: bool = False  # 管理员区入口（个人资料页 2.3.9）依赖此字段
    is_active: bool = True  # 账号可用性：为假即"已禁用"，管理端账号列表展示


class ProfileUpdateIn(BaseModel):
    """资料修改入参。全部字段可选，``None`` 表示"不修改"而非"清空"。

    学号与用户名刻意不在其中：前者必须走学号变更审核（F4），
    后者是登录凭据兼检索标识，注册后不可修改。
    """

    nickname: str | None = Field(default=None, max_length=50)
    bio: str | None = Field(default=None, max_length=200)
    avatar_url: str | None = None
    department: str | None = Field(default=None, max_length=100)
    class_name: str | None = Field(default=None, max_length=100)


class ChangePasswordIn(BaseModel):
    """修改密码：旧密码校验 + 新密码两次一致（后端为准，前端提示仅是体验）。"""

    old_password: str = Field(min_length=6, max_length=72)
    new_password: str = Field(min_length=6, max_length=72)
    confirm_password: str = Field(min_length=6, max_length=72)
