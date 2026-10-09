"""模型层公共基础：Base 与统一时间函数。"""
import datetime as dt

from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase


def utcnow() -> dt.datetime:
    """统一存 UTC 朴素时间，展示时再转本地时区。"""
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


# 微秒精度时间列：MySQL 默认 DATETIME 只有秒级精度，同一秒内写入的多条
# 记录时间戳完全相同，会导致"游标翻页丢页 / since_join、recent_n 边界不准"
#（系统测试 BG-001 的修复）。凡参与时间比较或排序的列一律用它。
DateTime6 = DateTime(6)


class Base(DeclarativeBase):
    pass
