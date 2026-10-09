"""CampusTalk 后端应用包。

包内分层（自下向上，每层只依赖紧邻的下层）：

- config.py / database.py   配置与异步数据库引擎，所有可变参数的唯一出口
- models/                   数据层：11 张表的 ORM 定义，每个域独占自己的表
- schemas/                  请求 / 响应模型（Pydantic），负责出入参的形状与校验
- core/                     无业务依赖的基础设施：密码与 JWT、敏感词
- services/                 业务层：跨路由复用的规则全部收敛在此
- deps.py                   公共依赖：当前用户、管理员校验
- routers/                  接口层：只做 HTTP 编排，业务判断一律下沉 services
- main.py                   应用装配入口

维护铁律（详见各模块 docstring 与《架构与数据设计》）：
1. 消息先落库再推送，且只能走 services/message_service.save_and_push；
2. WebSocket 处理函数只搬运，不写库、不做业务判断；
3. 文件只存 URL，二进制绝不进数据库与 WebSocket 帧；
4. 每个表只有一个域能写，跨域判断必须问所属域。
"""
