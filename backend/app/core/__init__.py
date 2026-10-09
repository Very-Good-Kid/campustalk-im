"""基础设施层：不依赖任何业务模型的可复用能力。

- security.py    密码哈希（bcrypt）与访问令牌（JWT HS256）的签发 / 解析
- sensitive.py   敏感词词库加载与命中判定

本层被 routers / services 共同调用，因此**不得反向导入 routers 或 services**，
保持"基础设施可被任意业务层引用、自身不依赖业务"的方向，避免循环依赖。
"""
