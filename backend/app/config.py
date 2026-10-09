"""全局配置：所有可变参数集中在此，禁止散落到业务代码。"""
import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    def __init__(self) -> None:
        self.database_url: str = os.getenv(
            "DATABASE_URL",
            "mysql+aiomysql://root:root@localhost:3306/campustalk?charset=utf8mb4",
        )
        # Redis 广播总线地址（Windows 本机用 Redis 5.0.14.1 服务版，默认端口 6379）。
        # 硬依赖：启动时连不上直接拒绝启动，见 services/bus.py。
        self.redis_url: str = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
        self.secret_key: str = os.getenv("SECRET_KEY", "please-change-this-secret")
        self.access_token_expire_minutes: int = int(
            os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440")
        )
        # 撤回时间窗，需求规定 3 分钟
        self.recall_window_seconds: int = int(os.getenv("RECALL_WINDOW_SECONDS", "180"))
        # 注册邀请码：准入强制手段。
        # 设为非空（如 CAMPUS2026）= 开启校验；设为空字符串 = 开放注册，无需邀请码。
        self.invite_code: str = os.getenv("INVITE_CODE", "CAMPUS2026")
        self.upload_dir: str = os.getenv("UPLOAD_DIR", "uploads")
        # 证明材料（学生证 / 学信网截图）的私密存储目录。
        # 该目录**不挂载静态路由**，只能通过管理员鉴权接口读取——
        # 学生证含姓名、学号与证件照，属敏感个人信息，绝不能像聊天图片那样公开访问。
        self.verify_dir: str = os.getenv("VERIFY_DIR", "private_uploads")


settings = Settings()
