"""接口层：按业务域拆分的 10 个路由模块，由 main.py 统一注册。

| 模块 | 前缀 / 路径 | 职责 |
|---|---|---|
| auth.py | /api/auth | 注册、登录、管理端登录、资料、改密、退出 |
| admin.py | /api/admin | 管理端账号治理与总览（全部经 require_admin） |
| verifications.py | /api/verifications | 学号变更申请与审核（含私密证明材料读取） |
| friends.py | /api | 好友检索、申请、增删改、找同班同学 |
| conversations.py | /api/conversations | 会话列表、建群 / 建频道、加入、加群申请、成员管理 |
| channels.py | /api/conversations | 频道内容层：帖子 / 评论 / 点赞 |
| messages.py | /api/conversations | 历史拉取、已读、置顶、撤回 |
| uploads.py | /api/upload | 图片 / 文件上传（只返回 URL） |
| reports.py | /api/reports | 举报提交与管理员处置 |
| ws.py | /ws | WebSocket 实时通道（非 REST） |

需要注意的两点：

1. **三个模块共用 /api/conversations 前缀**（conversations / channels / messages）。
   拆文件只是为了按文档域组织代码，对外路径不变，因此三者内部的路由顺序
   会相互影响——新增同形路径时务必确认不会遮蔽已有规则。
2. **本包不做业务判断**。这里只解析请求、校验参数、调用 services 与 models，
   权限与规则一律由 services / core / deps 决定。

本文件有意不导出任何符号（不写 __all__）：注册动作集中在 main.py，
新成员看 main.py 即可掌握完整的接口清单。
"""
