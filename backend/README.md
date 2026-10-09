# CampusTalk 后端

校园即时通讯系统的服务端：**FastAPI + SQLAlchemy 2.0 async + aiomysql + MySQL + Redis**；实时广播走 Redis Pub/Sub 总线（课件方式③发布-订阅，见 `services/bus.py`），Windows 本机由 Redis 5.0.14.1 服务版提供，**硬依赖：连不上 Redis 应用拒绝启动**。

对应设计文档：《架构与数据设计》四层架构、六个域与独占表、接口边界；字段定义与《系统设计》2.4.3 物理结构一致。

---

## 一、技术栈与依赖

| 组件 | 用途 |
|---|---|
| FastAPI | HTTP 路由、依赖注入、Pydantic 校验、`/docs` 自动接口文档 |
| Uvicorn（standard） | ASGI 服务器，内置 WebSocket 支持 |
| SQLAlchemy 2.0（asyncio）+ aiomysql | 异步 ORM 与 MySQL 驱动；**WebSocket 中绝不可用同步驱动** |
| redis（asyncio，redis>=5） | Pub/Sub 广播总线；Windows 上连本机 Redis 5.0.14.1 服务，启动时 ping 探活 |
| PyJWT | 无状态 HS256 访问令牌 |
| bcrypt | 口令哈希（注意 72 字节上限，schema 已限制 `max_length=72`） |
| python-dotenv | 读取 `.env` |
| python-multipart | 表单 / 文件上传（聊天附件、学号证明材料） |

完整清单见 `requirements.txt`，Python 需 3.11+。

---

## 二、启动步骤

```bash
# 0. 前置：确认 Redis 与 MySQL 都在跑
#    netstat -ano | findstr ":6379 " | findstr LISTENING   # 无输出则去 services.msc 启动 Redis 服务
#    建库（create_all 只能建表不能建库，必须先手动创建）：
#    MySQL 命令行 / Navicat 均可：
#    CREATE DATABASE campustalk DEFAULT CHARACTER SET utf8mb4 DEFAULT COLLATE utf8mb4_0900_ai_ci;

cd backend
cp .env.example .env        # Windows: copy .env.example .env
#   编辑 .env，至少把 DATABASE_URL 里的密码改成本机 MySQL 密码

python -m pip install -r requirements.txt

# 1. 初始化数据库（幂等：建表 + 为旧库补列 / 补外键 + 预置演示账号 / 机器人 / 演示群）
#    旧库（缺列、缺外键）直接跑它即可自愈，无需手工改表；结构已是最新则逐条显示"跳过"
python init_db.py

# 2. 启动服务（默认 5109，与前端 Vite 代理约定一致）
python -m uvicorn app.main:app --host 127.0.0.1 --port 5109
```

| 地址 | 用途 |
|---|---|
| <http://127.0.0.1:5109/docs> | Swagger 接口文档 |
| <http://127.0.0.1:5109/api/health> | 健康检查，返回 `{"status": "ok"}` |
| `ws://127.0.0.1:5109/ws?token=<jwt>` | WebSocket 实时通道 |

> 端口改动需三处同步：`start.bat`、`frontend/vite.config.js`、本文档。

### 环境变量（`app/config.py` 集中读取，禁止散落到业务代码）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DATABASE_URL` | `mysql+aiomysql://root:root@localhost:3306/campustalk?charset=utf8mb4` | 异步连接串 |
| `REDIS_URL` | `redis://127.0.0.1:6379/0` | 广播总线地址（Redis 服务默认端口）；硬依赖，连不上拒绝启动 |
| `SECRET_KEY` | `please-change-this-secret` | JWT 签名密钥，演示环境务必替换 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `1440` | 令牌有效期（分钟），默认 24 小时 |
| `RECALL_WINDOW_SECONDS` | `180` | 消息可撤回时间窗（需求规定 3 分钟） |
| `INVITE_CODE` | `CAMPUS2026` | 注册邀请码；**留空即开放注册**，非空则强制校验 |
| `UPLOAD_DIR` | `uploads` | 聊天图片 / 文件目录，挂载为 `/uploads` 静态路由 |
| `VERIFY_DIR` | `private_uploads` | 学号证明材料私密目录，**不挂载静态路由** |

---

## 三、目录结构

```
backend/
├── app/
│   ├── main.py           应用装配：lifespan 异步建表、CORS、路由注册、/uploads 静态挂载、/api/health
│   ├── config.py         Settings：所有可变参数的唯一出口
│   ├── database.py       create_async_engine（pre_ping / recycle=3600）+ get_db 依赖
│   ├── deps.py           get_current_user（校验 is_active）/ require_admin（真正的权限边界）
│   ├── core/
│   │   ├── security.py       bcrypt 哈希、JWT 签发与解析（失败一律返回 None）
│   │   └── sensitive.py      敏感词加载与命中判定（模块级缓存 + reload_words）
│   ├── models/           数据层（12 张表），按域拆文件、__init__.py 汇总导出
│   │   ├── base.py           Base + utcnow()（统一存 UTC 朴素时间）
│   │   ├── user.py / friendship.py / conversation.py / message.py
│   │   ├── content.py / governance.py / group_request.py
│   ├── schemas/          请求 / 响应模型（Out 模型统一开 from_attributes）
│   │   ├── auth.py           注册 / 登录 / 令牌 / 资料 / 改密
│   │   └── social.py         好友 / 成员 / 消息 / 加群申请等
│   ├── services/         业务层（跨路由复用的规则全部收敛在此）
│   │   ├── connections.py        ConnectionManager：进程内 user_id → WebSocket 映射（只负责"最后一米"）
│   │   ├── bus.py                Redis 广播总线：publish + 每实例订阅任务投递本地在线连接
│   │   ├── conversation_service.py  私聊会话幂等创建、assert_member、require_owner_or_admin
│   │   ├── message_service.py    save_and_push：唯一合法的消息落库 + 总线发布入口
│   │   ├── notify_service.py     系统通知广播、会话成员 id 查询
│   │   └── bot_service.py        规则机器人：/help、/签到、关键词回复
│   └── routers/          接口层（10 个模块）
│       ├── auth.py / friends.py / conversations.py / messages.py
│       ├── channels.py（频道内容层：帖子 / 评论 / 点赞）
│       ├── uploads.py / reports.py / verifications.py / admin.py / ws.py
├── init_db.py            初始化：建表 + 为旧库补列 / 补外键，预置 alice / bob / helper_bot / 演示群 id=1
├── requirements.txt
├── sensitive_words.txt   敏感词库（一行一个，# 为注释；当前为演示词条）
├── .env / .env.example   环境变量（.env 不入版本库）
├── uploads/              运行时生成：聊天图片与文件（静态可访问）
└── private_uploads/      运行时生成：学号证明材料（仅管理员鉴权接口可读）
```

---

## 四、分层与铁律

| 层 | 技术 | 职责 |
|---|---|---|
| 接口层 | FastAPI 路由 | 只做 HTTP 编排与参数校验，业务判断下沉服务层 |
| 业务层 | `app/services/` + `app/core/` | 全系统**唯一**判断权限与业务规则的地方 |
| 数据层 | SQLAlchemy async + aiomysql | 表结构由 Model 定义；文件只落目录、库里只存 URL |

1. **消息先落库再推送**——`message_service.save_and_push` 是唯一入口，任何代码（含机器人）不得绕过它直接写 `message` 表。
2. **WebSocket 只搬运**——`ws.py` 不写库、不做业务决策，全部转交服务层；成员校验问会话域，敏感词问 `core`。
3. **文件只存 URL**——数据库存 `/uploads/xxx`，二进制绝不进库、绝不进 WS 帧。
4. **每个表只有一个域能写**——跨域的「能不能」必须问所属域，不直接查别人的表。
5. **前端不持有规则**——拒绝理由以 HTTP `detail` 或 WS `error` 帧返回，前端只负责展示。

---

## 五、数据模型（12 张表）

| 表 | 域 | 职责与关键字段 |
|---|---|---|
| `user` | 身份 | 账号本体。`username` 唯一（登录名 + 检索标识，不可改）、`student_id` 唯一可空（机器人无学号）、`password_hash`、`is_admin`、`is_bot`、`is_active` + `disabled_at` / `disabled_by`（禁用留痕）、`last_seen_at`、`student_id_updated_at` / `_by`（学号变更留痕） |
| `friendship` | 关系 | **好友关系必须双向两条**（`(user_id, friend_id)` 唯一）。`status` = pending / accepted / rejected，`remark` / `group_name` / `is_starred` 是持有者私有数据 |
| `conversation` | 会话 | 私聊 / 群聊 / 频道三态合一，靠 `type` 区分。`owner_id`、`description`、`history_visible_mode`（all / since_join / recent_n）、`history_limit` |
| `conversation_member` | 会话 | `(conversation_id, user_id)` 唯一，`role` = owner / admin / member，`joined_at`（历史可见性判断）、`last_read_message_id`（未读红点） |
| `message` | 消息 | `msg_type`(text/emoji/image/file/card) + `sender_type`(user/bot)、`content`、`file_name` / `file_size`、`reply_to_id`（引用回复）、`recalled_at`（撤回标记，**非删除**）、`is_pinned`。联合索引 `(conversation_id, created_at)` 支撑历史分页 |
| `post` | 内容 | 频道帖子。`images`(JSON，≤9 张)、`card_user_id`（名片帖）、冗余计数 `like_count` / `comment_count`、`is_pinned`、`status`(1 正常 / 0 软删) |
| `comment` | 内容 | 帖子评论，`parent_id` 指向一级评论即为二级回复（**最多两级**），软删保留占位 |
| `likes` | 内容 | 帖子与评论共用，`target_type`(1 帖子 / 2 评论)；`(user_id, target_type, target_id)` 唯一保证一人一赞 |
| `group_join_request` | 会话 | 加群申请，`(conversation_id, user_id)` 唯一；被拒后可复用同一条记录重发，避免刷表 |
| `report` | 治理 | 举报记录：`reporter_id` / `message_id` / `reason` / `status`(pending/resolved/rejected) / `handled_by` / `handled_at` |
| `sensitive_word` | 治理 | 敏感词库，`word` 唯一、`created_by` 记录添加者；表为唯一权威源（空表时从 `sensitive_words.txt` 导入种子），进程内由前缀树缓存，增删经总线控制帧通知全部实例重建，无需重启 |
| `student_id_request` | 治理 | 学号变更申请：`old_student_id` / `new_student_id` / `proof_file`（仅存文件名）/ `reviewer_id` / `review_note` / `reviewed_at` |

时间约定：**统一存 UTC 朴素时间**（`models/base.py::utcnow`），序列化为不带时区的 isoformat 字符串，由前端补 `Z` 后转本地展示。

---

## 六、REST 接口一览

### 身份域 `/api/auth`
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/register` | 注册：邀请码、协议勾选、两次一致、弱口令黑名单、用户名 / 学号唯一 |
| POST | `/login` | 登录签发 JWT；用户名不存在与密码错误返回同一句提示（防账号枚举） |
| POST | `/admin-login` | 管理端独立入口；非管理员直接 403 且**不签发令牌** |
| GET / PUT | `/me` | 当前用户资料读取 / 修改（昵称、签名、头像、院系、班级） |
| POST | `/me/password` | 自助改密：原密码校验 + 新密码强度校验 + 新旧不同 |
| POST | `/logout` | 记录最后在线时间（JWT 无状态，令牌失效由前端清本地完成） |

### 关系域 `/api`（`friends.py`）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/users/search` | **仅用户名精确匹配**——昵称与学号不可被检索（防按姓名骚扰） |
| GET | `/users/classmates` | 找同班同学（按班级精确匹配） |
| GET | `/users/{user_id}/profile` | 用户简要资料（名片消息点击后使用） |
| POST | `/friends/requests` | 发起好友申请（曾被拒可复用记录重发） |
| GET | `/friends/requests?box=received\|sent` | 收 / 发申请列表（保留 accepted，便于从记录直接开聊） |
| PUT | `/friends/requests/{id}` | 同意（**反向补写一条** + 自动建立私聊会话）/ 拒绝 |
| GET / PUT / DELETE | `/friends`、`/friends/{id}` | 好友列表（特别关注置顶）、改备注 / 分组 / 特别关注、**双向删除** |
| POST | `/friends/{id}/conversation` | 打开或创建私聊会话（`id` = 自己时为「给自己发消息」） |

### 会话域 `/api/conversations`（`conversations.py`）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `` | 会话列表：未读数、最后一条消息摘要、是否群主；私聊在好友关系删除后不再显示 |
| POST | `/group`、`/channel` | 建群（初始成员仅限好友）/ 建频道 |
| PUT | `/{id}` | 改群 / 频道名称、头像、简介（群主或 admin；单聊拒绝） |
| GET | `/channels?q=` | 频道广场（关键词匹配名称与简介，返回是否已加入） |
| POST | `/{id}/join` | **免审加入频道**（仅频道；群聊必须走申请） |
| GET | `/{id}/group-preview` | 按群号预览群信息（不要求是成员） |
| POST | `/{id}/join-requests` | 申请加群（附言可选） |
| GET | `/join-requests?box=` | 加群申请列表（received 仅群主 / admin 可见） |
| PUT | `/join-requests/{id}` | 审批加群：同意即写入成员表 |
| POST | `/{id}/leave` | 退群 / 退频道 |
| PUT | `/{id}/history-visibility` | 群聊历史可见性 all / since_join / recent_n（**仅群聊**） |
| GET / POST / DELETE | `/{id}/members[/{user_id}]` | 成员列表、邀请入群、移除成员 |

### 消息域 `/api/conversations`（`messages.py`）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/{id}/messages?cursor=&limit=` | 历史消息，游标分页（以 created_at 为游标），响应**时间正序**；受历史可见性约束 |
| POST | `/{id}/read` | 标记已读（更新 `last_read_message_id`，未读红点归零） |
| POST / DELETE | `/{id}/messages/{mid}/pin` | 频道置顶话题帖（唯一化：新置顶顶掉旧置顶，广播 `system_notice`） |
| POST | `/messages/{mid}/recall` | 撤回本人 3 分钟内消息（标记不删除，广播 `system_notice`） |

### 频道内容域 `/api/conversations`（`channels.py`）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/{id}/posts?sort=time\|hot&limit=&offset=` | 帖子列表：置顶优先；hot 再按点赞 / 评论数 |
| POST | `/{id}/posts` | 发帖：正文 / 图片 / 名片至少一项；敏感词过滤 |
| GET / PUT / DELETE | `/{id}/posts/{pid}` | 详情 / 编辑（仅本人）/ 软删（本人或管理） |
| POST / DELETE | `/{id}/posts/{pid}/pin` | 帖子置顶（仅频道管理） |
| GET / POST | `/{id}/posts/{pid}/comments` | 评论列表（两级扁平返回）/ 发表评论或回复 |
| DELETE | `/{id}/comments/{cid}` | 软删评论（其下回复保留） |
| POST / DELETE | `/{id}/posts/{pid}/like`、`/{id}/comments/{cid}/like` | 点赞 / 取消（幂等，重复调用结果一致） |

### 内容域 `/api/upload`
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `` | 上传图片或文件。图片限 jpg/png/gif ≤10MB，文件走 MIME 白名单 ≤50MB；只返回 `{url, file_name, file_size, kind}` |

### 治理域
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/reports` | 提交举报（同一人对同一消息只允许一条待处理） |
| GET | `/api/reports?status=` | 管理员举报列表（pending / resolved / rejected / all） |
| PUT | `/api/reports/{id}` | 处置：resolved / rejected，可选 `punish=ban` 一并封禁作者 |
| POST | `/api/verifications/student-id` | 提交学号变更申请（multipart：新学号 + 说明 + 证明材料图片） |
| GET | `/api/verifications/my` | 我的申请与处理进展 |
| GET | `/api/verifications?req_status=` | 管理员待审列表 |
| GET | `/api/verifications/{id}/proof` | 管理员调阅证明材料（**唯一可读入口**） |
| POST | `/api/verifications/{id}/review` | 审核：approve / reject（驳回必须填理由）；**出结论后即删除材料原件** |

### 管理域 `/api/admin`（全部经 `require_admin`）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/overview` | 总览计数：待办举报 / 待审学号 / 账号与内容规模（**不展示任何用户内容**） |
| GET | `/users?q=&status=&page=&page_size=` | 账号列表（用户名 / 昵称 / 学号模糊搜索 + 状态筛选 + 分页） |
| PUT | `/users/{id}/status` | 禁用 / 启用（禁止禁用自己与机器人，禁用留痕） |
| POST | `/users/{id}/reset-password` | 重置口令（bcrypt 存储） |
| PUT | `/users/{id}/admin` | 授予 / 撤销管理员（禁止撤销自己） |
| PUT | `/users/{id}/student-id` | 学号直改（记录修改人与时间） |

其它：`GET /api/health`；`/uploads/*` 静态文件（由 `StaticFiles` 挂载）。

---

## 七、WebSocket 协议与校验顺序

`WS /ws?token=<jwt>`，帧格式 `{"type": ..., ...}`。客户端发 `send_message` 与 `typing`，服务端推 `receive_message` / `system_notice` / `presence` / `typing` / `error`。处理顺序（`routers/ws.py`）：

1. **握手鉴权**：令牌无效 → `close(1008)`；账号不存在或 `is_active=False` → `close(1008)`（禁用第三处生效点）。
2. 非 `send_message` 帧直接忽略；`msg_type` 不在 `text/emoji/image/file/card` 内 → `error`。
3. 富媒体帧要求 `content` 以 `/uploads/` 开头（先上传拿 URL）；文本 / 表情要求内容非空。
4. **成员校验**：非会话成员 → `error`。
5. 名片帧校验被推荐用户存在且非机器人。
6. **敏感词过滤**（仅文本 / 表情）：命中即拒绝，**不落库**。
7. 引用回复校验：目标必须是同会话的已存在消息。
8. `save_and_push` 落库后推给会话内全部成员（含发送者，前端据此去重）。
9. 文本消息触发规则机器人（`/help`、`/签到`、含「帮助」），机器人以 `sender_type=bot` 走同一入口，天然不会循环。

---

## 八、鉴权与安全设计

- **口令**：bcrypt 加盐哈希，明文不入库、不回显；注册与改密共用弱口令黑名单，且禁止与用户名 / 学号相同。
- **令牌**：JWT HS256，`sub` 为用户 id；前端放 `Authorization: Bearer`，WS 放 query。解析失败一律返回 `None` 而非抛异常（WS 侧可直接关连接）。
- **权限边界在接口层**：`deps.require_admin` 是真正的安全边界，前端隐藏入口与路由守卫只是体验层，绕过它们直接调接口同样 403。
- **账号禁用三处生效（缺一不可）**：登录接口（`auth.login`）、鉴权依赖（`deps.get_current_user`）、WebSocket 握手（`ws.py`）——否则会出现「禁用后仍能用旧令牌收发消息」。
- **隐私边界**：管理端**不提供浏览任意用户聊天记录的能力**，只能经举报处置看到被举报的那一条。
- **敏感个人信息的存储隔离**：学号证明材料落在未挂载静态路由的 `verify_dir`，只能通过管理员鉴权接口读取，并在审核出结论后立即删除原件（数据最小化）。
- **内容安全三道防线**：事中敏感词过滤（`core/sensitive.py`，消息与帖子 / 评论共用同一实现）、事后举报 + 封号处置、注册邀请码把注册面收窄到「被允许的人」。
- **CORS**：开发期放开（`allow_origins=["*"]`），实际浏览器侧走 Vite 同源代理，不依赖 CORS。

---

## 九、实现约定与踩过的坑

- **异步建表必须用 `run_sync`**：`async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)`，MySQL 下不能用同步 `create_all`。
- **引擎参数**：`pool_pre_ping=True` 防空闲被 MySQL 踢连接；`pool_recycle=3600` 必须小于 MySQL `wait_timeout`。
- **`expire_on_commit=False`**：commit 后仍可读对象属性，避免在异步上下文里触发隐式 IO。
- **路由注册顺序**：FastAPI 按注册顺序匹配，`/users/search` 与 `/users/{user_id}/profile` 必须避开 `{user_id}` 吞掉静态段的写法（代码中已改用 `/profile` 子路径）。
- **加入判断不能用 `assert_member`**：它在「非成员」时抛 403，会让所有未加入的人都无法加入频道；此处只能查询判断。
- **Schema 的 `from_attributes`**：所有 Out 模型必须开启，否则 `model_validate(orm)` 直接 500。
- **`init_db.py` 幂等**：先 `create_all`（建缺失的表）再跑补丁（老库补列 / 补外键），顺序不能颠倒——反过来的话，新库上会对还不存在的表执行 `ALTER`。补丁只把 MySQL 的"已存在"错误码（1060 / 1061 / 1826）当作跳过，其余异常一律抛出：早期版本把所有异常都 `pass` 掉了，导致补丁失败无声无息、库与模型长期不一致（表现为接口 500）却查不出原因。另会同步演示账号的 `is_admin` 标记，结尾显式 `engine.dispose()`，避免退出时打印 `Event loop is closed` 噪音。
- **Redis 总线是硬依赖**：启动时 `bus.ping()` 失败直接拒绝启动——"起来了但广播静默失效"比"起不来"难排查得多；运行中 publish 失败只记日志不上抛（消息已先落库，推送尽力而为）。Windows 无官方 Redis，本机用 Redis 5.0.14.1（tporadowski/redis 便携版 zip）解压后以 `redis-server --service-install` 注册为名为 Redis 的 Windows 服务，开机自启、默认只监听 127.0.0.1:6379。

---

## 十、演示账号

| 账号 | 口令 | 说明 |
|---|---|---|
| `alice` | `123456` | 管理员（`is_admin=True`），昵称「爱丽丝」 |
| `bob` | `123456` | 普通用户，昵称「鲍勃」，与 alice 同班 |
| `helper_bot` | — | 规则机器人（`is_bot=True`，不可登录、不可被封禁、不可被加好友） |
| 会话 id=1 | — | 演示群「W1 联调测试群」，alice 为群主，bob 为成员 |

注册需邀请码 `CAMPUS2026`（由 `INVITE_CODE` 控制，留空即开放注册）。

---

## 十一、范围外与后续

- AI 群聊总结为可选项，未接入（`bot_service.py` 已预留 `sender_type=bot` 的扩展位）。`typing`（正在输入）与 `presence`（上下线跳变）帧已实现：均不落库，只经 Redis 总线转发，连接断开即失效。
- 「禁言」（区别于封号）为后期项，本期内容治理的实质处置为封禁账号。
- 不引入消息队列 / Nginx / 对象存储 / 容器编排（技术栈边界；Redis 仅做瞬态 Pub/Sub 总线，不存持久数据，E-R 与表结构不受影响）。
- 部署边界：仅本机 `localhost` 运行，不备案、不内网穿透、不对外提供服务。
