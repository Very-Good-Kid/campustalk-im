# CampusTalk 前端

校园即时通讯系统的 Web 前端：Vue 3 + Vite + Pinia + Vue Router，**无 UI 组件库依赖**（30 个 `.vue` 全部手写，统一引用一套设计令牌；令牌的灰阶体系参考腾讯 TDesign 开源设计规范，与其中性色阶同源、仅微调色温）。

对应设计文档：《系统设计》2.1 表现层、2.3 界面设计（用户端三栏骨架 + 管理端独立骨架）。

---

## 一、启动

```bash
# 1. 先启动后端（默认 127.0.0.1:5109，见 backend/.env）
cd ../backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 5109

# 2. 启动前端（默认 5108，/api /uploads /ws 由 Vite 代理转发到 5109）
cd ../frontend
npm install
npm run dev
```

- 用户端：<http://127.0.0.1:5108>
- 管理端：<http://127.0.0.1:5108/admin/login>（需管理员账号）
- 接口文档：<http://127.0.0.1:5109/docs>

演示账号由 `backend/init_db.py` 预置：`alice / 123456`（管理员）、`bob / 123456`。也可在项目根目录双击 `start.bat` 一键完成「环境检查 → 装依赖 → 初始化库 → 起前后端 → 开浏览器」。

| 脚本 | 作用 |
|---|---|
| `npm run dev` | 开发服务器（Vite，端口 5108，`strictPort` 被占用即失败不顺延） |
| `npm run build` | 生产构建，产物输出到 `dist/` |
| `npm run preview` | 预览构建产物 |

---

## 二、目录结构

```
frontend/
├── index.html
├── vite.config.js         开发期代理：/api /uploads（HTTP）、/ws（ws: true）
├── package.json           依赖仅 vue / vue-router / pinia + vite 插件
└── src/                   共 51 个源文件（30 .vue / 19 .js / 2 .css）
    ├── main.js            入口：先样式 → 再 Pinia → 套用本机偏好 → 挂载
    ├── App.vue            只承载 <router-view> 与全局 ToastHost
    ├── api/               接口层：REST 封装（fetch，无 axios）
    │   ├── request.js         全站唯一请求出口：Bearer 注入 / detail 解析 / 401 分流
    │   ├── token.js           localStorage 令牌读写唯一入口（key = ct_token）
    │   ├── auth.js            身份域：注册 / 登录 / 资料 / 改密 / 退出
    │   ├── friends.js         关系域：检索、申请、好友增删改、同班同学、开私聊
    │   ├── conversations.js   会话域 + 消息域：列表 / 建群 / 建频道 / 入群申请 / 成员 / 历史 / 已读 / 撤回 / 置顶
    │   ├── channelContent.js  频道内容域：帖子 / 评论 / 点赞
    │   ├── content.js         内容域：上传（图片 ≤10MB、文件 ≤50MB，前端预检 + 服务端复检）
    │   ├── governance.js      治理域：举报、学号变更申请与审核、证明材料读取
    │   └── admin.js           管理端：admin-login / 总览 / 账号列表 / 禁用启用 / 重置口令 / 授权 / 学号直改
    ├── stores/            状态层（Pinia，7 个）
    │   ├── auth.js            令牌 + 当前用户（含 adminLogin）；退出 = 清令牌 + 断 WS + 记最后在线
    │   ├── websocket.js       全站唯一 WS 连接：建连 / 指数退避重连（上限 30s）/ 按 type 分发
    │   ├── chat.js            会话列表（未读红点）/ 各会话历史与成员 / 发送 / 撤回 / 置顶 / 名片头像回写
    │   ├── friends.js         好友列表 + 收发申请（侧边栏角标与通知页共用）
    │   ├── groupRequests.js   加群申请（收到的 / 发出的），群通知角标数据源
    │   ├── settings.js        本机偏好：提示音 / 免打扰 / 界面缩放（localStorage，不入库）
    │   └── toast.js           全局轻提示（替代原生 alert）
    ├── layouts/
    │   ├── AppLayout.vue        用户端三栏骨架：顶栏 + 左侧分区导航 + 右侧内容；WS 在此建立、资料在此拉取
    │   ├── ContactsSidebar.vue  联系人分区专用侧边栏：好友管理 / 好友通知 / 群通知 + 好友|群聊切换 + 分组列表
    │   └── AdminLayout.vue      管理端独立骨架：主色顶栏 + 左侧管理导航（复用同一套设计令牌）
    ├── views/             用户端页面层
    │   ├── LoginView.vue          登录（居中卡片）
    │   ├── RegisterView.vue       注册（邀请码 / 协议勾选 / 学号院系班级）
    │   ├── HallView.vue           会话大厅（欢迎页 + 未读统计）
    │   ├── ChatView.vue           聊天（文本 / 表情 / 图片 / 文件 / 名片、引用回复、撤回、举报、成员侧栏）
    │   ├── ContactsView.vue       联系人页主壳：按路由切换右侧面板，具体内容见 views/contacts/
    │   ├── ChannelsView.vue       频道广场（square）与我的频道（mine）双模式
    │   ├── ChannelDetailView.vue  频道内容层：帖子流 / 发帖（含名片帖、最多 9 图）/ 两级评论 / 点赞 / 排序
    │   ├── ProfileView.vue        个人资料（个人资料 / 学号变更 / 设置三个子标签）
    │   ├── contacts/              联系人右侧面板
    │   │   ├── ManagePanel.vue        好友管理：检索、加好友、同班同学、群号加群
    │   │   ├── NotifyPanel.vue        通知：好友申请 / 加群申请（按 type 复用同一面板）
    │   │   ├── FriendPanel.vue        好友资料卡：发消息、备注 / 分组 / 特别关注、删除
    │   │   └── GroupPanel.vue         群资料卡：群成员、改群资料、退群
    │   └── admin/                 管理端页面（独立入口 /admin）
    │       ├── AdminLoginView.vue         独立登录口
    │       ├── AdminOverviewView.vue      总览（计数与待办卡）
    │       ├── AdminUsersView.vue         账号管理
    │       ├── AdminReportsView.vue       举报处置
    │       └── AdminVerificationsView.vue 学号审核
    ├── components/        通用组件（8 个）：MessageBubble / UserAvatar / EmojiPicker /
    │                      ModalDialog / ToastHost / ProfileCard / GroupCard / JoinGroupDialog
    ├── router/index.js    路由与守卫（用户端与管理端分别导向各自登录页）
    ├── utils/format.js    UTC 时间解析、文件大小、会话摘要文案、表情判定与词库
    └── assets/styles/     tokens.css 设计令牌（配色规范 v1.0）+ main.css 通用元件
```

---

## 三、路由表

| 路径 | name | 说明 |
|---|---|---|
| `/login`、`/register` | login / register | 公开页，不使用布局骨架 |
| `/` | hall | 会话大厅 |
| `/chat/:id` | chat | 聊天页 |
| `/contacts/:tab?`（manage / friend-notify / group-notify） | contacts | 联系人分区主页 |
| `/contacts/friend/:userId` | contacts-friend | 好友资料（`userId` = 自己时是「我」的资料） |
| `/contacts/group/:id` | contacts-group | 群资料 |
| `/channels`、`/channels/mine` | channels / channels-mine | 频道广场 / 我的频道 |
| `/channels/:id` | channel-detail | 频道内容流（帖子层） |
| `/profile/:tab?`（info / student-id / settings） | profile | 个人资料分区 |
| `/admin/login` | admin-login | 管理端独立登录口 |
| `/admin/overview|users|reports|verifications` | admin-* | 管理端四页 |
| `/:pathMatch(.*)*` | — | 兜底重定向到 `/` |

> `/friends/*` 为兼容旧链接，统一重定向到 `/contacts`。守卫只认「本地是否有令牌」，令牌是否有效由接口 401 统一判定（`request.js`）。

---

## 四、管理端（独立子应用）

- **入口独立**：`/admin/login` 独立登录口、`/admin` 独立骨架，**不复用** IM 三栏布局与 WebSocket。
- **视觉同源**：完全复用 `tokens.css` 设计令牌，不引入新色值；顶栏改用主色 `--brand-7` 实底白字，与用户端白底顶栏同源但具备后台辨识度。
- **权限三层**：入口层（用户端「我的」分区只保留一个「进入管理后台」链接）+ 路由层（`AdminLayout` 校验 `is_admin`）+ **接口层（服务端 `require_admin`，真正的安全边界）**。
- **功能**：总览（只做计数，不展示任何用户内容）、账号管理（禁用/启用、重置口令、授予/撤销管理员、学号直改）、举报处置（可一并封禁被举报作者）、学号审核（调阅证明材料后通过/驳回）。
- **账号禁用三处生效**：登录接口、鉴权依赖、WebSocket 握手；禁用后该账号已签发的旧令牌立即失效。

---

## 五、实时帧协议

WebSocket 连接由 `AppLayout` 建立：`ws(s)://<当前域名>/ws?token=<jwt>`（开发期经 Vite 代理），**仅用户端使用，管理端不建连**。

| 帧类型 | 方向 | 说明 |
|---|---|---|
| `send_message` | 客户端 → 服务端 | 发送消息；`msg_type` 限 `text` / `emoji` / `image` / `file` / `card` |
| `receive_message` | 服务端 → 客户端 | 新消息投递（推给会话内全部成员，含发送者） |
| `system_notice` | 服务端 → 客户端 | 系统通知：`message_recalled` / `message_pinned` / `message_unpinned` |
| `error` | 服务端 → 客户端 | 业务拒绝理由，由 `websocket.js` 统一弹 Toast |

帧分发契约：`websocket.js` 只负责建连 / 重连 / 按 `type` 派发给订阅者，业务数据交给 `chat` store 处理（`bindWebsocket()` 订阅 `receive_message` 与 `system_notice`，均为幂等更新）。

---

## 六、本机偏好设置（`/profile/settings`）

只放「真正会被消费」的项，全部存 `localStorage`（key = `ct_prefs`），不入库、不上传：

| 项 | 效果 |
|---|---|
| 提示音 | 非当前会话收到新消息时播放提示音（Web Audio 合成，无音频文件） |
| 免打扰 | 提示音静默 |
| 界面缩放 | 写入 `<html>` 的 `zoom`（小 0.9 / 中 1 / 大 1.1），整体界面（含字号）等比缩放 |

主题与语言属后续规划项，设置页仅保留入口并标注「开发中」。

---

## 七、架构约定

1. **前端不持有业务规则**——所有校验、权限、敏感词判定以后端为准，前端只展示拒绝理由（`request.js` 统一解析 `detail`，兼容字符串与 Pydantic 校验数组两种形态）。
2. **消息以 WS 回显为准**——后端 `receive_message` 推给会话全部成员（含发送者），前端不做本地乐观插入，天然去重；仅撤回 / 置顶做本地乐观更新，并由 `system_notice` 让其他在线端幂等同步。
3. **消息不丢靠后端先落库**——WS 断开时历史仍在库中，重连 / 刷新即补齐；前端只做指数退避重连，不做补偿队列。
4. **图片文件不进帧**——先调 `/api/upload` 拿 `/uploads/...` URL，再把 URL 作为消息 `content`；二进制绝不走 WebSocket。
5. **时间解析统一走 `utils/format.js`**——后端时间是「UTC 且不带时区」的 iso 字符串，必须补 `Z` 再解析，否则整体错一个时区。
6. **全部确认走页面内浮窗**（`ModalDialog` + `Toast`），不使用浏览器原生 `alert / confirm`。
7. **颜色 / 间距只引用 CSS 变量**（`tokens.css`），组件内不硬编码色值。

---

## 八、与后端的对齐与缺口

**已实现（本轮扫描确认）**

- 统一会话抽象三态（私聊 / 群聊 / 频道）在同一套组件中复用。
- 频道「内容层」：帖子流（时间序 / 热度序）、二级评论、帖子与评论点赞、频道置顶帖、名片帖。
- 联系人分区：分组折叠好友列表、好友通知与群通知角标、群号加群（申请 → 群主审批）、好友资料卡与群资料卡。
- 名片消息（聊天与频道帖两处）与引用回复；点击名片开资料卡，并顺带回写已加载名片消息的头像。
- 学号变更申请（上传证明材料）与管理端审核、管理员账号治理五件套。
- 好友在线状态（presence 帧驱动绿点）与「正在输入」提示（typing 帧；单聊不点名，群聊 / 频道拼最多三个昵称）。

**已知缺口（有意不做，与后端能力对齐）**

- 「禁言」（区别于封号）为后期项；本期内容治理的实质处置采用**封禁账号**。
- 主题切换、多语言、账号安全等设置项为范围外项，见《信息结构图》⏸ 后期清单。
- 联系人侧边栏的「顶置群聊」「班级群聊」为概念占位（依赖教务数据，本期不做）。
