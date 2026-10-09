"""业务服务层。

路由层（routers/）只做 HTTP 编排：解析请求 → 调服务 → 返回响应；
所有可复用的业务逻辑收敛在 services/，与《系统设计》2.1 的六域划分对应：

- connections.py            连接管理（WebSocket 在线映射）
- message_service.py        消息域：落库与推送的唯一入口
- notify_service.py         通知域：系统通知广播（撤回 / 置顶变更）、会话成员 id 查询
- bot_service.py            机器人域：规则回复
- conversation_service.py   会话域：成员校验、私聊会话幂等创建

本包模块之间可以互相调用（如 message_service 依赖 notify_service 与 connections），
但**不得反向导入 routers**；如需请求上下文，由调用方把参数传进来。
"""
