# -*- coding: utf-8 -*-
"""CampusTalk 系统测试执行脚本（对应文档《系统测试》4.4 / 4.5）。

用真实 HTTP / WebSocket 请求打真实运行中的服务，逐条记录预期与实际。
运行前置条件：
  1. MySQL 可用，backend/.env 已配置数据库连接
  2. Redis 服务已启动（127.0.0.1:6379，本机为 Redis 5.0.14.1 Windows 服务版）——硬依赖，连不上后端拒绝启动
  3. python init_db.py 已执行（预置 alice / bob / helper_bot / 演示群）
  4. python -m uvicorn app.main:app --host 127.0.0.1 --port 5109 已在运行
  5. 前端 npm run dev 已在 5108 运行（仅 F1 用例依赖）

运行：pytest tests/（推荐，逐条用例独立报告）或 python backend/tests/system_test.py（原生单流）
输出：backend/tests/test_results.json（运行时生成，不入库）+ 控制台逐条 PASS/FAIL

pytest 模式说明：用例仍在导入期按登记顺序立即执行，与原生模式同一时序
（模块级 glue 语句与用例的交织顺序本身就是用例语义的一部分，延后执行
会破坏前置状态）。差异只在收尾：不打印汇总、不 sys.exit，而是按已算好
的 RESULTS 逐条生成 test_xxx 断言函数（序号前缀保住注册顺序——pytest
默认按字母序收集模块函数）。结果回写 test_results.json 由
 tests/conftest.py 的 sessionfinish 完成。
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import re
import sys
import time

import aiomysql
import requests
from websockets.sync.client import connect

BASE = "http://127.0.0.1:5109"
FE = "http://127.0.0.1:5108"
WS = "ws://127.0.0.1:5109/ws"

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RESULTS: list[dict] = []

# pytest 跑起来时 pytest 会在子进程环境里注入 PYTEST_VERSION；据此切换收尾方式
RUNNING_PYTEST = os.environ.get("PYTEST_VERSION") is not None

PWD = "Abc123456"     # 测试用非弱口令
WEAK = "123456"       # 弱口令黑名单内
INVITE = "CAMPUS2026"  # .env 默认邀请码
TS = time.strftime("%m%d%H%M%S")


def uname(suffix: str) -> str:
    return f"t{TS}{suffix}"  # 全局唯一，避免重复运行时用户名冲突


def _db_info():
    """从 backend/.env 解析 DATABASE_URL（测试辅助：取预置账号 id 用）。"""
    with open(os.path.join(ROOT, "backend", ".env"), encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("DATABASE_URL="):
                url = line.strip().split("=", 1)[1]
                m = re.match(
                    r"mysql\+aiomysql://([^:]+):([^@]+)@([^:]+):(\d+)/([^?]+)", url)
                return m.groups()
    raise RuntimeError("DATABASE_URL 未找到")


def db_scalar(sql: str, *args):
    async def _q():
        user, pwd, host, port, db = _db_info()
        conn = await aiomysql.connect(host=host, port=int(port), user=user,
                                      password=pwd, db=db)
        try:
            cur = await conn.cursor()
            await cur.execute(sql, args)
            row = await cur.fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    return asyncio.new_event_loop().run_until_complete(_q())


BOT_ID = db_scalar("SELECT id FROM user WHERE username = 'helper_bot'")


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------
def api(method, path, token=None, *, json_body=None, data=None, files=None,
        params=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return requests.request(
        method, BASE + path, headers=headers, json=json_body, data=data,
        files=files, params=params, timeout=60,
    )


def det(r):
    """取响应 detail（兼容字符串与 Pydantic 校验数组两种形态）。"""
    try:
        j = r.json()
        if isinstance(j, dict):
            d = j.get("detail")
            if isinstance(d, list) and d:
                return "422校验: " + str(d[0].get("msg", d[0]))
            if d is not None:
                return str(d)
    except Exception:
        pass
    return None


def register(username, nickname, student_id=None, class_name=None, **kw):
    body = {
        "username": username, "nickname": nickname,
        "password": PWD, "confirm_password": PWD,
        "agree_terms": True, "invite_code": INVITE,
        "student_id": student_id, "class_name": class_name,
    }
    body.update(kw)
    return api("POST", "/api/auth/register", json_body=body)


def login(username, password=PWD):
    return api("POST", "/api/auth/login", json_body={
        "username": username, "password": password})


def case(cid, title, pre, steps, expected, priority, fn):
    """执行一条用例并记录；两种模式都在登记点立即执行，保证时序一致。"""
    try:
        ok, actual = fn()
    except Exception as e:  # noqa
        ok, actual = False, f"执行异常 {type(e).__name__}: {e}"
    RESULTS.append({
        "cid": cid, "title": title, "pre": pre, "steps": steps,
        "expected": expected, "actual": actual, "priority": priority,
        "result": "通过" if ok else "失败",
    })
    if not RUNNING_PYTEST:
        print(("  [PASS] " if ok else "  [FAIL] ") + f"{cid} {title}")
        if not ok:
            print(f"          预期: {expected}")
            print(f"          实际: {actual}")
    return ok


def ws_send(ws, payload):
    ws.send(json.dumps(payload, ensure_ascii=False))


def ws_recv(ws, timeout=8, expect=None):
    """读取一帧；expect 为期望的 type 集合（元组/集合/字符串）。
    presence / typing 是本轮新增的在线状态与输入提示广播帧，属于预期外的
    噪声帧：不带 expect 时自动跳过，带 expect 时读到 expect 内 type 才返回
    （timeout 为整体超时，非单帧超时）。避免连接期 presence 广播插队导致
    用例读到错误帧（KeyError / type 不符）。"""
    if isinstance(expect, str):
        expect = {expect}
    deadline = time.monotonic() + timeout
    noise = set()
    while True:
        frame = json.loads(ws.recv(timeout=max(0.1, deadline - time.monotonic())))
        if expect is None:
            if frame.get("type") in ("presence", "typing"):
                noise.add(frame.get("type"))
                continue
            return frame
        if frame.get("type") in expect:
            return frame
        if time.monotonic() >= deadline:
            return frame  # 超时返回最后一帧，让用例断言给出有意义的失败信息


# ---------------------------------------------------------------------------
# 0. 环境冒烟 + 测试账号准备
# ---------------------------------------------------------------------------
print("== 0. 环境冒烟与账号准备 ==")


def f0_health():
    r = requests.get(f"{BASE}/api/health", timeout=10)
    return r.status_code == 200 and r.json().get("status") == "ok", \
        f"GET /api/health -> {r.status_code} {r.text[:60]}"


case("TC-F0-01", "后端健康检查", "后端已在 5109 运行",
     "1、GET /api/health", "200 且 status=ok", "高", f0_health)


def f0_env():
    r1 = requests.get(FE, timeout=10)
    r2 = requests.get(f"{FE}/api/health", timeout=10)
    ok = r1.status_code == 200 and r2.status_code == 200
    return ok, f"前端 {r1.status_code}；同源代理 /api/health -> {r2.status_code}"


case("TC-F0-02", "前端可达且同源代理正常", "前端已在 5108 运行",
     "1、GET http://127.0.0.1:5108\n2、GET http://127.0.0.1:5108/api/health",
     "前端 200；代理转发到后端返回 ok", "高", f0_env)

# 预置演示账号
r = login("alice", "123456")
alice_tok = r.json()["access_token"] if r.status_code == 200 else None
r = login("bob", "123456")
bob_tok = r.json()["access_token"] if r.status_code == 200 else None
assert alice_tok and bob_tok, "alice/bob 登录失败，请确认 init_db 已执行"

# 本轮测试专用账号（UA~TF）
USER = {}
for suffix, nick, sid, cls in [
    ("a", "甲同学", f"{TS}01", "通信2023级1班"),
    ("b", "乙同学", f"{TS}02", "通信2023级1班"),
    ("c", "丙同学", f"{TS}03", "计算机2023级2班"),
    ("d", "丁同学", f"{TS}04", "计算机2023级2班"),
    ("e", "戊同学", f"{TS}05", "自动化2023级1班"),
    ("f", "己同学", f"{TS}06", "自动化2023级1班"),
]:
    ru = uname(suffix)
    rp = register(ru, nick, student_id=sid, class_name=cls)
    rl = login(ru)
    USER[suffix] = {
        "username": ru, "sid": sid, "class": cls, "nickname": nick,
        "id": rl.json()["user_id"],
        "token": rl.json()["access_token"] if rl.status_code == 200 else None,
    }
    assert USER[suffix]["token"], f"{ru} 注册/登录失败: {rp.status_code} {rp.text[:200]}"

A, B, C, D, E, F = (USER[x]["token"] for x in "abcdef")
print(f"  测试账号: " + ", ".join(f"{USER[x]['username']}(id={USER[x]['id']})" for x in "abcdef"))

# ---------------------------------------------------------------------------
# F1 统一界面框架
# ---------------------------------------------------------------------------
print("== F1 统一界面框架 ==")


def f1_user_home():
    r = requests.get(FE, timeout=10)
    return r.status_code == 200 and "<div id=\"app\">" in r.text, \
        f"用户端入口 -> {r.status_code}"


case("TC-F1-01", "用户端入口页面可达", "前端已启动",
     "1、浏览器 GET http://127.0.0.1:5108", "200，返回 Vue 应用入口 HTML", "中", f1_user_home)


def f1_admin():
    r = requests.get(f"{FE}/admin/login", timeout=10)
    return r.status_code == 200, f"/admin/login -> {r.status_code}"


case("TC-F1-02", "管理端独立入口可达", "前端已启动",
     "1、GET http://127.0.0.1:5108/admin/login", "200（SPA 路由由前端守卫控制）", "中", f1_admin)

# ---------------------------------------------------------------------------
# F2 用户注册
# ---------------------------------------------------------------------------
print("== F2 用户注册 ==")


def f2_invite():
    r = register(uname("x1"), "测试", invite_code="WRONG")
    return r.status_code == 403 and det(r) == "邀请码无效，请向管理员获取", \
        f"{r.status_code} {det(r)}"


case("TC-F2-01", "邀请码错误被拦截", "INVITE_CODE 非空",
     f"1、POST /api/auth/register，invite_code=WRONG\n2、其余字段合法",
     "403 邀请码无效，请向管理员获取", "高", f2_invite)


def f2_terms():
    r = register(uname("x2"), "测试", agree_terms=False)
    return r.status_code == 400 and det(r) == "请先阅读并同意用户协议", \
        f"{r.status_code} {det(r)}"


case("TC-F2-02", "未勾选用户协议被拦截",
     "打开注册页", "1、agree_terms=false 提交", "400 请先阅读并同意用户协议", "高", f2_terms)


def f2_pwd_mismatch():
    r = register(uname("x3"), "测试", confirm_password="Xyz999888")
    return r.status_code == 400 and det(r) == "两次输入的密码不一致", \
        f"{r.status_code} {det(r)}"


case("TC-F2-03", "两次密码不一致被拦截", "打开注册页",
     "1、password=Abc123456, confirm_password=Xyz999888", "400 两次输入的密码不一致", "高", f2_pwd_mismatch)


def f2_pwd_eq_user():
    u = uname("x4")
    r = register(u, "测试", password=u, confirm_password=u)
    return r.status_code == 400 and det(r) == "密码不能与用户名相同", \
        f"{r.status_code} {det(r)}"


case("TC-F2-04", "密码与用户名相同被拦截", "打开注册页",
     "1、密码填成与用户名相同", "400 密码不能与用户名相同", "中", f2_pwd_eq_user)


def f2_weak():
    r = register(uname("x5"), "测试", password=WEAK, confirm_password=WEAK)
    return r.status_code == 400 and det(r) == "密码过于简单，请更换", \
        f"{r.status_code} {det(r)}"


case("TC-F2-05", "弱口令被拦截", "打开注册页",
     "1、password=123456（黑名单内）", "400 密码过于简单，请更换", "高", f2_weak)


def f2_dup_user():
    r = register(USER["a"]["username"], "重复注册")
    return r.status_code == 400 and det(r) == "该用户名已被注册", f"{r.status_code} {det(r)}"


case("TC-F2-06", "重复用户名被拦截", f"{USER['a']['username']} 已注册",
     f"1、以已存在用户名 {USER['a']['username']} 注册", "400 该用户名已被注册", "高", f2_dup_user)


def f2_dup_sid():
    r = register(uname("x6"), "学号重复", student_id=USER["a"]["sid"])
    return r.status_code == 400 and det(r) == "该学号已注册", f"{r.status_code} {det(r)}"


case("TC-F2-07", "重复学号被拦截", f"学号 {USER['a']['sid']} 已被使用",
     f"1、注册时填写已被使用的学号 {USER['a']['sid']}", "400 该学号已注册", "高", f2_dup_sid)


def f2_short_name():
    r = register("ab", "过短用户名")
    return r.status_code == 422, f"{r.status_code} {det(r)}"


case("TC-F2-08", "用户名校验长度边界", "打开注册页",
     "1、username=ab（<4 位）", "422 参数校验失败", "中", f2_short_name)


def f2_ok():
    r = register(uname("x7"), "注册成功用户")
    return r.status_code == 201 and "password" not in r.text, \
        f"{r.status_code}；响应不含口令字段={'password' not in r.text}"


case("TC-F2-09", "正常注册成功", "打开注册页，字段全部合法",
     "1、填写合法字段并勾选协议提交", "201；响应为 UserOut 且不含任何口令字段", "高", f2_ok)

# ---------------------------------------------------------------------------
# F3 登录与退出
# ---------------------------------------------------------------------------
print("== F3 登录与退出 ==")


def f3_wrong_pwd():
    r = login(USER["a"]["username"], "WrongPass999")
    return r.status_code == 400 and det(r) == "用户名或密码错误", f"{r.status_code} {det(r)}"


case("TC-F3-01", "密码错误登录被拒绝", f"{USER['a']['username']} 已注册",
     "1、用错误密码登录", "400 用户名或密码错误", "高", f3_wrong_pwd)


def f3_no_user():
    r = login(uname("zz"), "AnyPass999")
    return r.status_code == 400 and det(r) == "用户名或密码错误", \
        f"{r.status_code} {det(r)}（与不存在的用户返回同一句）"


case("TC-F3-02", "不存在用户名返回相同提示（防账号枚举）", "—",
     "1、用不存在的用户名登录", "400 用户名或密码错误，与密码错误同文案", "高", f3_no_user)


def f3_bot():
    # 用 init_db.py 预置的占位口令，凭据正确才能走到 is_bot 分支
    r = login("helper_bot", "bot-no-login-000")
    return r.status_code == 403 and det(r) == "机器人账号无法登录", f"{r.status_code} {det(r)}"


case("TC-F3-03", "机器人账号拒绝登录", "helper_bot 为 is_bot 账号",
     "1、以 helper_bot 登录", "403 机器人账号无法登录", "中", f3_bot)


def f3_admin_login_denied():
    r = api("POST", "/api/auth/admin-login",
            json_body={"username": USER["a"]["username"], "password": PWD})
    return r.status_code == 403 and det(r) == "该账号无管理员权限", f"{r.status_code} {det(r)}"


case("TC-F3-04", "非管理员走管理端登录被拒绝", f"{USER['a']['username']} 为普通用户",
     "1、POST /api/auth/admin-login", "403 该账号无管理员权限，且不签发令牌", "高", f3_admin_login_denied)


def f3_admin_login_ok():
    r = api("POST", "/api/auth/admin-login",
            json_body={"username": "alice", "password": "123456"})
    return r.status_code == 200 and r.json().get("is_admin") is True, \
        f"{r.status_code} is_admin={r.json().get('is_admin')}"


case("TC-F3-05", "管理员登录管理端", "alice 口令 123456",
     "1、POST /api/auth/admin-login", "200 且 is_admin=true", "高", f3_admin_login_ok)


def f3_logout():
    r = api("POST", "/api/auth/logout", token=A)
    return r.status_code == 200 and r.json().get("ok") is True, f"{r.status_code}"


case("TC-F3-06", "退出登录记录最后在线", f"{USER['a']['username']} 已登录",
     "1、POST /api/auth/logout", "200 ok=true（更新 last_seen_at）", "中", f3_logout)

# ---------------------------------------------------------------------------
# F4 个人信息管理
# ---------------------------------------------------------------------------
print("== F4 个人信息管理 ==")


def f4_no_token():
    r = api("GET", "/api/auth/me")
    return r.status_code == 401 and det(r) == "缺少令牌", f"{r.status_code} {det(r)}"


case("TC-F4-01", "未携带令牌访问受保护接口", "—",
     "1、GET /api/auth/me（无 Authorization 头）", "401 缺少令牌", "高", f4_no_token)


def f4_get_me():
    r = api("GET", "/api/auth/me", token=A)
    j = r.json()
    return r.status_code == 200 and j["username"] == USER["a"]["username"] \
        and j["class_name"] == "通信2023级1班", f"{r.status_code} {j.get('username')}"


case("TC-F4-02", "读取当前用户资料", f"{USER['a']['username']} 已登录",
     "1、GET /api/auth/me", "200 返回本人资料（用户名/学号/院系/班级）", "高", f4_get_me)


def f4_update_me():
    r = api("PUT", "/api/auth/me", token=A, json_body={
        "nickname": "甲同学·改", "bio": "系统测试签名",
        "department": "通信与信息工程学院", "class_name": "通信2023级1班"})
    j = r.json()
    return r.status_code == 200 and j["nickname"] == "甲同学·改" \
        and j["bio"] == "系统测试签名", f"{r.status_code} {j.get('nickname')}"


case("TC-F4-03", "修改昵称/签名/院系", f"{USER['a']['username']} 已登录",
     "1、PUT /api/auth/me 提交新昵称与签名", "200 返回更新后的资料", "高", f4_update_me)


def f4_pwd_old_wrong():
    r = api("POST", "/api/auth/me/password", token=B, json_body={
        "old_password": "WrongPass999", "new_password": "NewPass123",
        "confirm_password": "NewPass123"})
    return r.status_code == 400 and det(r) == "原密码不正确", f"{r.status_code} {det(r)}"


case("TC-F4-04", "改密：原密码错误被拦截", f"{USER['b']['username']} 已登录",
     "1、旧密码填错提交", "400 原密码不正确", "高", f4_pwd_old_wrong)


def f4_pwd_same():
    r = api("POST", "/api/auth/me/password", token=B, json_body={
        "old_password": PWD, "new_password": PWD, "confirm_password": PWD})
    return r.status_code == 400 and det(r) == "新密码不能与原密码相同", f"{r.status_code} {det(r)}"


case("TC-F4-05", "改密：新旧密码相同被拦截", f"{USER['b']['username']} 已登录",
     "1、新密码与旧密码相同提交", "400 新密码不能与原密码相同", "中", f4_pwd_same)


def f4_pwd_ok():
    r = api("POST", "/api/auth/me/password", token=B, json_body={
        "old_password": PWD, "new_password": "NewPass123",
        "confirm_password": "NewPass123"})
    rl = login(USER["b"]["username"], "NewPass123")
    ok = r.status_code == 200 and rl.status_code == 200
    if rl.status_code == 200:
        USER["b"]["token"] = rl.json()["access_token"]  # 后续用例用新令牌
    return ok, f"改密 {r.status_code}；新口令登录 {rl.status_code}"


case("TC-F4-06", "改密成功且新口令可登录", f"{USER['b']['username']} 已登录",
     "1、POST /api/auth/me/password 修改口令\n2、用新口令重新登录",
     "200 ok=true；新口令登录 200", "高", f4_pwd_ok)
B = USER["b"]["token"]

# ---------------------------------------------------------------------------
# F5 好友管理
# ---------------------------------------------------------------------------
print("== F5 好友管理 ==")


def f5_search_miss():
    r = api("GET", "/api/users/search", token=A, params={"q": uname("zz")})
    return r.status_code == 200 and r.json() == [], f"{r.status_code} 结果数={len(r.json())}"


case("TC-F5-01", "精确检索不存在用户", f"{USER['a']['username']} 已登录",
     "1、GET /api/users/search?q=<不存在的用户名>", "200 空列表", "中", f5_search_miss)


def f5_search_hit():
    r = api("GET", "/api/users/search", token=A, params={"q": USER["b"]["username"]})
    j = r.json()
    return r.status_code == 200 and len(j) == 1 and j[0]["username"] == USER["b"]["username"], \
        f"{r.status_code} 命中数={len(j)}"


case("TC-F5-02", "按用户名精确检索命中", f"{USER['a']['username']} 已登录",
     f"1、GET /api/users/search?q={USER['b']['username']}",
     "200 恰好 1 条且为目标用户", "高", f5_search_hit)


def f5_search_by_nick():
    r = api("GET", "/api/users/search", token=A, params={"q": "乙同学"})
    return r.status_code == 200 and r.json() == [], \
        f"{r.status_code} 结果数={len(r.json())}（按昵称不可检索）"


case("TC-F5-03", "按昵称检索不可命中（隐私边界）", f"{USER['a']['username']} 已登录",
     "1、GET /api/users/search?q=乙同学（昵称）", "200 空列表——仅用户名可检索", "高", f5_search_by_nick)


def f5_add_self():
    r = api("POST", "/api/friends/requests", token=A,
            json_body={"friend_id": USER["a"]["id"]})
    return r.status_code == 400 and det(r) == "不能添加自己为好友", f"{r.status_code} {det(r)}"


case("TC-F5-04", "添加自己为好友被拦截", f"{USER['a']['username']} 已登录",
     "1、friend_id 填自己", "400 不能添加自己为好友", "中", f5_add_self)


def f5_add_bot():
    # 检索接口按设计排除机器人（隐私边界），直接用库里的 bot id 验证申请拦截
    r = api("POST", "/api/friends/requests", token=A, json_body={"friend_id": BOT_ID})
    return r.status_code == 404 and det(r) == "用户不存在", f"{r.status_code} {det(r)}"


case("TC-F5-05", "添加机器人账号被拦截", "helper_bot 存在且 is_bot",
     "1、向机器人账号发好友申请", "404 用户不存在", "中", f5_add_bot)


def f5_request():
    r = api("POST", "/api/friends/requests", token=A, json_body={
        "friend_id": USER["b"]["id"], "request_message": "我是同班同学"})
    return r.status_code == 201 and r.json().get("ok") is True, f"{r.status_code} {det(r)}"


case("TC-F5-06", "发起好友申请", f"A 已登录，B 存在",
     "1、POST /api/friends/requests friend_id=B", "201 申请已发送", "高", f5_request)


def f5_request_dup():
    r = api("POST", "/api/friends/requests", token=A,
            json_body={"friend_id": USER["b"]["id"]})
    return r.status_code == 400 and det(r) == "已提交过申请，等待对方处理", \
        f"{r.status_code} {det(r)}"


case("TC-F5-07", "重复发起申请被拦截", "A 已向 B 发过申请",
     "1、再次向 B 发申请", "400 已提交过申请，等待对方处理", "中", f5_request_dup)


def f5_received():
    r = api("GET", "/api/friends/requests", token=B, params={"box": "received"})
    j = r.json()
    req_id = next((x["request_id"] for x in j if x["user"]["id"] == USER["a"]["id"]), None)
    return r.status_code == 200 and req_id is not None, f"{r.status_code} 收到申请数={len(j)}"
    # req_id 被下一用例重新查询，这里只验证可见


case("TC-F5-08", "B 收到好友申请", "A 已申请",
     "1、GET /api/friends/requests?box=received", "200 列表含 A 的申请", "高", f5_received)


def f5_accept():
    rl = api("GET", "/api/friends/requests", token=B, params={"box": "received"})
    req_id = next(x["request_id"] for x in rl.json()
                  if x["user"]["id"] == USER["a"]["id"])
    r = api("PUT", f"/api/friends/requests/{req_id}", token=B,
            json_body={"action": "accept"})
    fl = api("GET", "/api/friends", token=A)
    f_b = any(x["friend_user_id"] == USER["b"]["id"] for x in fl.json())
    return r.status_code == 200 and det(r) == "已同意" and f_b, \
        f"同意 {r.status_code}；A 的好友列表已含 B = {f_b}"


case("TC-F5-09", "同意申请后双向互为好友", "A 申请、B 登录",
     "1、B PUT /api/friends/requests/{id} action=accept\n2、A GET /api/friends",
     "200 已同意；A 好友列表含 B（反向补写生效）", "高", f5_accept)


def f5_reject_then_resend():
    # A 向 C 申请，C 拒绝，A 再申请应可重发
    api("POST", "/api/friends/requests", token=A, json_body={"friend_id": USER["c"]["id"]})
    rl = api("GET", "/api/friends/requests", token=C, params={"box": "received"})
    req_id = next(x["request_id"] for x in rl.json()
                  if x["user"]["id"] == USER["a"]["id"])
    api("PUT", f"/api/friends/requests/{req_id}", token=C, json_body={"action": "reject"})
    r = api("POST", "/api/friends/requests", token=A, json_body={"friend_id": USER["c"]["id"]})
    return r.status_code == 201 and det(r) == "申请已重新发送", f"{r.status_code} {det(r)}"


case("TC-F5-10", "被拒后可重新申请", "A 申请 C，C 拒绝",
     "1、C 拒绝 A 的申请\n2、A 再次发起申请",
     "第二次 201 申请已重新发送（复用同一记录不刷表）", "中", f5_reject_then_resend)


def f5_update_friend():
    r = api("PUT", f"/api/friends/{USER['b']['id']}", token=A, json_body={
        "remark": "同桌", "group_name": "同班同学", "is_starred": True})
    fl = api("GET", "/api/friends", token=A).json()
    f_b = next(x for x in fl if x["friend_user_id"] == USER["b"]["id"])
    return r.status_code == 200 and f_b["remark"] == "同桌" and f_b["is_starred"] is True, \
        f"{r.status_code} remark={f_b['remark']} starred={f_b['is_starred']}"


case("TC-F5-11", "设置备注/分组/特别关注", "A、B 已互为好友",
     "1、PUT /api/friends/{B} 提交备注分组与特别关注\n2、GET /api/friends 核对",
     "200；好友列表回显 remark=同桌、is_starred=true", "中", f5_update_friend)


def f5_open_conv():
    r = api("POST", f"/api/friends/{USER['b']['id']}/conversation", token=A)
    j = r.json()
    case.__dict__["conv_ab"] = j.get("conversation_id")
    return r.status_code == 200 and "conversation_id" in j, \
        f"{r.status_code} conversation_id={j.get('conversation_id')}"


case("TC-F5-12", "打开好友私聊会话", "A、B 已互为好友",
     "1、POST /api/friends/{B}/conversation", "200 返回 conversation_id（不存在则创建）", "高", f5_open_conv)
CONV_AB = case.__dict__.get("conv_ab")


def f5_open_conv_not_friend():
    r = api("POST", f"/api/friends/{USER['d']['id']}/conversation", token=A)
    return r.status_code == 403 and det(r) == "对方还不是你的好友", f"{r.status_code} {det(r)}"


case("TC-F5-13", "非好友开私聊被拦截", "A 与 D 非好友",
     "1、POST /api/friends/{D}/conversation", "403 对方还不是你的好友", "高", f5_open_conv_not_friend)


def f5_classmates():
    r = api("GET", "/api/users/classmates", token=A)
    j = r.json()
    hit = any(x["id"] == USER["b"]["id"] for x in j)
    no_c = all(x["id"] != USER["c"]["id"] for x in j)
    return r.status_code == 200 and hit and no_c, \
        f"{r.status_code} 含同班B={hit}，不含异班C={no_c}"


case("TC-F5-14", "找同班同学（按班级精确匹配）", "A、B 同班，A、C 不同班",
     "1、GET /api/users/classmates", "200 含 B 且不含 C", "中", f5_classmates)


def f5_user_profile():
    r = api("GET", f"/api/users/{USER['b']['id']}/profile", token=A)
    j = r.json()
    rb = api("GET", f"/api/users/{BOT_ID}/profile", token=A)
    ok = (r.status_code == 200 and j["nickname"] == USER["b"]["nickname"]
          and rb.status_code == 404)
    return ok, f"好友资料 {r.status_code}（昵称={j.get('nickname')}）；机器人资料 {rb.status_code}"


case("TC-F5-16", "查看用户简要资料（名片点击场景）", "A、B 互为好友",
     f"1、A GET /api/users/{{B}}/profile\n2、再查机器人 id 的资料",
     "200 返回昵称/院系/班级；机器人账号 404 用户不存在", "中", f5_user_profile)


def f5_delete():
    api("POST", "/api/friends/requests", token=A, json_body={"friend_id": USER["d"]["id"]})
    rl = api("GET", "/api/friends/requests", token=D, params={"box": "received"})
    req_id = next(x["request_id"] for x in rl.json()
                  if x["user"]["id"] == USER["a"]["id"])
    api("PUT", f"/api/friends/requests/{req_id}", token=D, json_body={"action": "accept"})
    r = api("DELETE", f"/api/friends/{USER['d']['id']}", token=A)
    fl_a = api("GET", "/api/friends", token=A).json()
    fl_d = api("GET", "/api/friends", token=D).json()
    gone = all(x["friend_user_id"] != USER["d"]["id"] for x in fl_a) \
        and all(x["friend_user_id"] != USER["a"]["id"] for x in fl_d)
    return r.status_code == 200 and gone, f"删除 {r.status_code}；双向均已消失={gone}"


case("TC-F5-15", "删除好友双向生效", "A、D 已互为好友",
     "1、A DELETE /api/friends/{D}\n2、分别查 A、D 的好友列表",
     "200；A、D 双方列表都不再出现对方（双向删除）", "高", f5_delete)

# ---------------------------------------------------------------------------
# F6 单聊通信（含 WebSocket）
# ---------------------------------------------------------------------------
print("== F6 单聊通信 ==")


def f6_ws_send():
    ws_a = connect(f"{WS}?token={A}", open_timeout=8)
    ws_b = connect(f"{WS}?token={B}", open_timeout=8)
    try:
        ws_send(ws_a, {"type": "send_message", "conversation_id": CONV_AB,
                       "msg_type": "text", "content": "单聊测试消息1"})
        ma = ws_recv(ws_a)   # 推送含发送者
        mb = ws_recv(ws_b)   # 对方实时收到
        ok = (ma.get("type") == "receive_message"
              and mb.get("type") == "receive_message"
              and mb["data"]["content"] == "单聊测试消息1"
              and mb["data"]["sender_id"] == USER["a"]["id"])
        return ok, f"A回显={ma.get('type')} B收到content={mb['data'].get('content')}"
    finally:
        ws_a.close()
        ws_b.close()


case("TC-F6-01", "WebSocket 实时收发（发送者与对方均收到）", "A、B 互为好友且已开私聊",
     "1、A、B 分别建立 WS 连接\n2、A 发送文本消息",
     "两端均收到 receive_message，内容为原文", "高", f6_ws_send)


def f6_history():
    ws_a = connect(f"{WS}?token={A}", open_timeout=8)
    try:
        for i in range(25):
            ws_send(ws_a, {"type": "send_message", "conversation_id": CONV_AB,
                           "msg_type": "text", "content": f"历史消息{i}"})
            ws_recv(ws_a)
        time.sleep(0.5)
    finally:
        ws_a.close()
    r1 = api("GET", f"/api/conversations/{CONV_AB}/messages", token=A,
             params={"limit": 20})
    msgs = r1.json()
    cursor = msgs[0]["created_at"]
    r2 = api("GET", f"/api/conversations/{CONV_AB}/messages", token=A,
             params={"limit": 20, "cursor": cursor})
    ok = (r1.status_code == 200 and r2.status_code == 200
          and len(msgs) == 20 and len(r2.json()) == 6
          and msgs[-1]["content"] == "历史消息24"
          and any(m["content"] == "单聊测试消息1" for m in r2.json()))
    return ok, (f"首页 {len(msgs)} 条（最新一页，时间正序，末条={msgs[-1]['content']}）；"
                f"翻页 {len(r2.json())} 条且含最早一条")


case("TC-F6-02", "历史消息游标分页", "A 已向 B 发足够多消息",
     "1、GET messages?limit=20 取首页\n2、用首页最早 created_at 作 cursor 翻页",
     "两次均 200；首页 20 条且时间正序，翻页取到更早消息", "高", f6_history)


def f6_reply():
    r = api("GET", f"/api/conversations/{CONV_AB}/messages", token=A, params={"limit": 5})
    target = r.json()[-1]["id"]
    ws_a = connect(f"{WS}?token={A}", open_timeout=8)
    try:
        ws_send(ws_a, {"type": "send_message", "conversation_id": CONV_AB,
                       "msg_type": "text", "content": "引用回复内容",
                       "reply_to_id": target})
        m = ws_recv(ws_a)
        return m["data"]["reply_to_id"] == target, \
            f"reply_to_id={m['data'].get('reply_to_id')} 目标={target}"
    finally:
        ws_a.close()


case("TC-F6-03", "引用回复", "会话内已有消息",
     "1、A 发消息并携带 reply_to_id 指向已有消息",
     "receive_message 的 reply_to_id 指向目标消息", "中", f6_reply)


def f6_card():
    ws_a = connect(f"{WS}?token={A}", open_timeout=8)
    try:
        ws_send(ws_a, {"type": "send_message", "conversation_id": CONV_AB,
                       "msg_type": "card", "content": str(USER["c"]["id"])})
        m = ws_recv(ws_a)
        return m["data"]["msg_type"] == "card" and m["data"]["card_user"] \
            and m["data"]["card_user"]["id"] == USER["c"]["id"], \
            f"card_user={m['data'].get('card_user')}"
    finally:
        ws_a.close()


case("TC-F6-04", "名片消息（推荐好友）", "C 是普通用户",
     "1、A 发 msg_type=card，content 为 C 的用户 id",
     "收到名片消息，card_user 含被推荐人资料", "中", f6_card)


def f6_offline_reconnect():
    """断线后消息已落库，刷新即补齐。"""
    ws_a = connect(f"{WS}?token={A}", open_timeout=8)
    ws_send(ws_a, {"type": "send_message", "conversation_id": CONV_AB,
                   "msg_type": "text", "content": "断线前最后一条"})
    ws_recv(ws_a)
    ws_a.close()  # 主动断开
    r = api("GET", f"/api/conversations/{CONV_AB}/messages", token=A,
            params={"limit": 1})
    ok = r.status_code == 200 and r.json() and r.json()[-1]["content"] == "断线前最后一条"
    return ok, f"断开后重取历史，最后一条={r.json()[-1]['content'] if r.json() else None}"


case("TC-F6-05", "断线后消息不丢（先落库再推送）", "A 已连 WS",
     "1、A 发消息后主动断开 WS\n2、重新拉取历史",
     "消息仍在库中，历史可查（不依赖在线推送）", "高", f6_offline_reconnect)


def f6_ws_not_member():
    # B 建一个 C 不在其中的群（初始成员必须是好友，B 的好友是 A），C 发消息应被拒
    rg = api("POST", "/api/conversations/group", token=B,
             json_body={"name": "B的私密群", "member_ids": [USER["a"]["id"]]})
    conv = rg.json()["conversation_id"]
    ws_c = connect(f"{WS}?token={C}", open_timeout=8)
    try:
        ws_send(ws_c, {"type": "send_message", "conversation_id": conv,
                       "msg_type": "text", "content": "闯入消息"})
        m = ws_recv(ws_c)
        return m.get("type") == "error" and "成员" in m.get("detail", ""), \
            f"{m.get('type')} {m.get('detail')}"
    finally:
        ws_c.close()


case("TC-F6-06", "非会话成员发消息被 WS 拒绝", "A 不是 B 私密群成员",
     "1、A 建立 WS 连接\n2、向非成员会话发送消息",
     "收到 error 帧：你不是该会话成员，消息不落库", "高", f6_ws_not_member)


def f6_bad_type():
    ws_a = connect(f"{WS}?token={A}", open_timeout=8)
    try:
        ws_send(ws_a, {"type": "send_message", "conversation_id": CONV_AB,
                       "msg_type": "voice", "content": "x"})
        m = ws_recv(ws_a)
        return m.get("type") == "error" and "不支持的消息类型" in m.get("detail", ""), \
            f"{m.get('type')} {m.get('detail')}"
    finally:
        ws_a.close()


case("TC-F6-07", "非法消息类型被 WS 拒绝", "A 已连 WS",
     "1、发送 msg_type=voice（不在白名单）",
     "error 帧：不支持的消息类型", "中", f6_bad_type)


def f6_empty_content():
    ws_a = connect(f"{WS}?token={A}", open_timeout=8)
    try:
        ws_send(ws_a, {"type": "send_message", "conversation_id": CONV_AB,
                       "msg_type": "text", "content": ""})
        m = ws_recv(ws_a)
        return m.get("type") == "error" and "不能为空" in m.get("detail", ""), \
            f"{m.get('type')} {m.get('detail')}"
    finally:
        ws_a.close()


case("TC-F6-08", "空文本消息被 WS 拒绝", "A 已连 WS",
     "1、发送空字符串文本消息", "error 帧：消息内容不能为空", "中", f6_empty_content)

# ---------------------------------------------------------------------------
# F7 群聊通信
# ---------------------------------------------------------------------------
print("== F7 群聊通信 ==")


def f7_create_with_non_friend():
    r = api("POST", "/api/conversations/group", token=A,
            json_body={"name": "含非好友的群", "member_ids": [USER["c"]["id"]]})
    return r.status_code == 400 and det(r) == "初始成员必须是你的好友", f"{r.status_code} {det(r)}"


case("TC-F7-01", "建群初始成员含非好友被拦截", "A 与 C 不是好友",
     "1、POST /api/conversations/group member_ids=[C]",
     "400 初始成员必须是你的好友", "高", f7_create_with_non_friend)

# A 与 C 加好友，便于后续建群/邀请
api("POST", "/api/friends/requests", token=A, json_body={"friend_id": USER["c"]["id"]})
_rl = api("GET", "/api/friends/requests", token=C, params={"box": "received"})
_rid = next(x["request_id"] for x in _rl.json() if x["user"]["id"] == USER["a"]["id"])
api("PUT", f"/api/friends/requests/{_rid}", token=C, json_body={"action": "accept"})


def f7_create():
    r = api("POST", "/api/conversations/group", token=A,
            json_body={"name": "系统测试群", "member_ids": [USER["b"]["id"]]})
    gid = r.json().get("conversation_id")
    case.__dict__["group_id"] = gid
    return r.status_code == 201 and gid, f"{r.status_code} group_id={gid}"


case("TC-F7-02", "创建群聊", "A 与 B 是好友",
     "1、A POST /api/conversations/group name=系统测试群 member_ids=[B]",
     "201 返回 conversation_id", "高", f7_create)
GROUP = case.__dict__.get("group_id")


def f7_invite():
    r = api("POST", f"/api/conversations/{GROUP}/members", token=A,
            json_body={"user_id": USER["c"]["id"]})
    return r.status_code == 201, f"{r.status_code} {det(r)}"


case("TC-F7-03", "群主邀请成员入群", "A 为群主，C 为 A 好友",
     "1、A POST members user_id=C", "201 邀请成功", "高", f7_invite)


def f7_invite_dup():
    r = api("POST", f"/api/conversations/{GROUP}/members", token=A,
            json_body={"user_id": USER["c"]["id"]})
    return r.status_code == 400 and det(r) == "对方已在群里", f"{r.status_code} {det(r)}"


case("TC-F7-04", "邀请已在群成员被拦截", "C 已在群内",
     "1、再次邀请 C 入群", "400 对方已在群里", "中", f7_invite_dup)


def f7_group_chat():
    ws_c = connect(f"{WS}?token={C}", open_timeout=8)
    ws_b = connect(f"{WS}?token={B}", open_timeout=8)
    try:
        ws_send(ws_c, {"type": "send_message", "conversation_id": GROUP,
                       "msg_type": "text", "content": "群消息广播测试"})
        mc = ws_recv(ws_c)
        mb = ws_recv(ws_b)
        return mc["data"]["content"] == "群消息广播测试" and mb["data"]["content"] == "群消息广播测试", \
            f"C收到={mc['data'].get('content')} B收到={mb['data'].get('content')}"
    finally:
        ws_c.close()
        ws_b.close()


case("TC-F7-05", "群消息实时广播到全部成员", "B、C 均在群内且在线",
     "1、C 建 WS 并发群消息\n2、B 的 WS 应实时收到",
     "发送者与接收者均收到 receive_message", "高", f7_group_chat)


def f7_preview():
    r = api("GET", f"/api/conversations/{GROUP}/group-preview", token=D)
    j = r.json()
    return r.status_code == 200 and j["name"] == "系统测试群" and j["joined"] is False, \
        f"{r.status_code} name={j.get('name')} joined={j.get('joined')}"


case("TC-F7-06", "非成员可预览群信息", "D 不在群内",
     "1、D GET /api/conversations/{群}/group-preview",
     "200 返回群名/成员数/群主，joined=false（预览≠可读消息）", "中", f7_preview)


def f7_join_request():
    r = api("POST", f"/api/conversations/{GROUP}/join-requests", token=D,
            json_body={"message": "想进系统测试群"})
    return r.status_code == 201, f"{r.status_code} {det(r)}"


case("TC-F7-07", "申请加入群聊", "D 不在群内",
     "1、D POST join-requests 附申请理由", "201 申请已发送", "高", f7_join_request)


def f7_join_request_dup():
    r = api("POST", f"/api/conversations/{GROUP}/join-requests", token=D,
            json_body={"message": "再次申请"})
    return r.status_code == 400 and det(r) == "已提交申请，等待群主处理", f"{r.status_code} {det(r)}"


case("TC-F7-08", "重复申请加群被拦截", "D 已申请过",
     "1、D 再次申请加群", "400 已提交申请，等待群主处理", "中", f7_join_request_dup)


def f7_join_not_owner():
    rl = api("GET", "/api/conversations/join-requests", token=A,
             params={"box": "received"})
    req_id = next(x["request_id"] for x in rl.json()
                  if x["user"]["id"] == USER["d"]["id"])
    case.__dict__["join_req_id"] = req_id
    r = api("PUT", f"/api/conversations/join-requests/{req_id}", token=C,
            json_body={"action": "accept"})
    return r.status_code == 403 and "群主或创建者" in det(r), f"{r.status_code} {det(r)}"


case("TC-F7-09", "非群主审批加群申请被拦截", "C 是普通成员",
     "1、C PUT join-requests/{id} action=accept",
     "403 仅群主或创建者可执行此操作", "高", f7_join_not_owner)
JOIN_REQ = case.__dict__.get("join_req_id")


def f7_join_accept():
    r = api("PUT", f"/api/conversations/join-requests/{JOIN_REQ}", token=A,
            json_body={"action": "accept"})
    mem = api("GET", f"/api/conversations/{GROUP}/members", token=A).json()
    has_d = any(m["user_id"] == USER["d"]["id"] for m in mem)
    return r.status_code == 200 and det(r) == "已同意入群" and has_d, \
        f"{r.status_code} {det(r)}；成员表含 D = {has_d}"


case("TC-F7-10", "群主同意加群申请", "D 已申请，A 为群主",
     "1、A PUT join-requests/{id} accept\n2、查群成员列表",
     "200 已同意入群；成员列表出现 D", "高", f7_join_accept)


def f7_leave():
    r = api("POST", f"/api/conversations/{GROUP}/leave", token=D)
    mem = api("GET", f"/api/conversations/{GROUP}/members", token=A).json()
    has_d = any(m["user_id"] == USER["d"]["id"] for m in mem)
    return r.status_code == 200 and not has_d, f"退群 {r.status_code}；D 已不在成员表 = {not has_d}"


case("TC-F7-11", "成员退群", "D 已是群成员",
     "1、D POST /{群}/leave\n2、群主查成员列表",
     "200；成员列表不再含 D", "中", f7_leave)


def f7_rename_by_non_owner():
    r = api("PUT", f"/api/conversations/{GROUP}", token=C,
            json_body={"name": "普通成员改名"})
    return r.status_code == 403 and "群主或创建者" in det(r), f"{r.status_code} {det(r)}"


case("TC-F7-12", "普通成员改群资料被拦截", "C 是普通成员",
     "1、C PUT /api/conversations/{群} 改名", "403 仅群主或创建者可执行此操作", "高", f7_rename_by_non_owner)


def f7_rename_single():
    r = api("PUT", f"/api/conversations/{CONV_AB}", token=A,
            json_body={"name": "单聊改名"})
    return r.status_code == 400 and det(r) == "单聊会话不支持修改信息", f"{r.status_code} {det(r)}"


case("TC-F7-13", "单聊会话禁止改资料", "CONV_AB 为私聊",
     "1、A PUT /api/conversations/{私聊} 改名", "400 单聊会话不支持修改信息", "中", f7_rename_single)


def f7_kick():
    r = api("DELETE", f"/api/conversations/{GROUP}/members/{USER['c']['id']}", token=A)
    mem = api("GET", f"/api/conversations/{GROUP}/members", token=A).json()
    has_c = any(m["user_id"] == USER["c"]["id"] for m in mem)
    return r.status_code == 200 and not has_c, f"{r.status_code}；C 已移除 = {not has_c}"


case("TC-F7-14", "群主移除成员", "C 是群成员",
     "1、A DELETE members/{C}", "200；成员列表不再含 C", "中", f7_kick)


def f7_history_mode_single():
    r = api("PUT", f"/api/conversations/{CONV_AB}/history-visibility", token=A,
            json_body={"mode": "since_join"})
    return r.status_code == 400 and det(r) == "仅群聊支持设置历史可见性", f"{r.status_code} {det(r)}"


case("TC-F7-15", "单聊设置历史可见性被拦截", "CONV_AB 为私聊",
     "1、A PUT history-visibility mode=since_join",
     "400 仅群聊支持设置历史可见性", "中", f7_history_mode_single)

# 重新邀请 C 回来做历史可见性测试
api("POST", f"/api/conversations/{GROUP}/members", token=A,
    json_body={"user_id": USER["c"]["id"]})


def f7_history_since_join():
    # 群主先记录一条"加入前"消息，再设置 since_join
    ws_a = connect(f"{WS}?token={A}", open_timeout=8)
    try:
        ws_send(ws_a, {"type": "send_message", "conversation_id": GROUP,
                       "msg_type": "text", "content": "C重新入群前的历史"})
        ws_recv(ws_a)
    finally:
        ws_a.close()
    api("PUT", f"/api/conversations/{GROUP}/history-visibility", token=A,
        json_body={"mode": "since_join"})
    # C 退群再申请加入，joined_at 将晚于上面这条消息
    api("POST", f"/api/conversations/{GROUP}/leave", token=C)
    api("POST", f"/api/conversations/{GROUP}/join-requests", token=C,
        json_body={"message": "重进"})
    rl = api("GET", "/api/conversations/join-requests", token=A, params={"box": "received"})
    rid = next(x["request_id"] for x in rl.json() if x["user"]["id"] == USER["c"]["id"])
    api("PUT", f"/api/conversations/join-requests/{rid}", token=A,
        json_body={"action": "accept"})
    r = api("GET", f"/api/conversations/{GROUP}/messages", token=C, params={"limit": 50})
    texts = [m["content"] for m in r.json()]
    ok = "C重新入群前的历史" not in texts
    # 发一条新消息，C 应可见
    ws_a = connect(f"{WS}?token={A}", open_timeout=8)
    try:
        ws_send(ws_a, {"type": "send_message", "conversation_id": GROUP,
                       "msg_type": "text", "content": "C入群后的新消息"})
        ws_recv(ws_a)
    finally:
        ws_a.close()
    r2 = api("GET", f"/api/conversations/{GROUP}/messages", token=C, params={"limit": 50})
    texts2 = [m["content"] for m in r2.json()]
    return ok and "C入群后的新消息" in texts2, \
        f"加入前历史不可见={ok}；加入后消息可见={'C入群后的新消息' in texts2}"


case("TC-F7-16", "群历史可见性=加入后(since_join)", "群消息已有多条",
     "1、群主设置 since_join\n2、C 退群重进\n3、C 拉历史并接收新消息",
     "C 看不到加入前的消息，能看到加入后的消息", "高", f7_history_since_join)


def f7_history_recent_n_no_limit():
    r = api("PUT", f"/api/conversations/{GROUP}/history-visibility", token=A,
            json_body={"mode": "recent_n"})
    return r.status_code == 400 and det(r) == "选择「最近 N 条」时必须填写条数", \
        f"{r.status_code} {det(r)}"


case("TC-F7-17", "recent_n 模式缺少数值被拦截", "A 为群主",
     "1、PUT history-visibility mode=recent_n 不带 limit",
     "400 选择「最近 N 条」时必须填写条数", "中", f7_history_recent_n_no_limit)


def f7_history_recent_n():
    for i in range(3):
        ws_a = connect(f"{WS}?token={A}", open_timeout=8)
        try:
            ws_send(ws_a, {"type": "send_message", "conversation_id": GROUP,
                           "msg_type": "text", "content": f"recentN消息{i}"})
            ws_recv(ws_a)
        finally:
            ws_a.close()
    api("PUT", f"/api/conversations/{GROUP}/history-visibility", token=A,
        json_body={"mode": "recent_n", "limit": 2})
    r = api("GET", f"/api/conversations/{GROUP}/messages", token=A, params={"limit": 50})
    texts = [m["content"] for m in r.json() if m["content"].startswith("recentN消息")]
    return len(texts) == 2, f"recent_n=2 时仅可见 {len(texts)} 条 recentN 消息"


case("TC-F7-18", "群历史可见性=最近N条(recent_n)", "群内已有 3 条 recentN 消息",
     "1、群主设置 recent_n limit=2\n2、A 拉取全部历史",
     "仅返回最近 2 条 recentN 消息", "高", f7_history_recent_n)


def f7_join_free_only_channel():
    r = api("POST", f"/api/conversations/{GROUP}/join", token=D)
    return r.status_code == 403 and det(r) == "仅频道支持免审加入", f"{r.status_code} {det(r)}"


case("TC-F7-19", "群聊不支持免审加入", "GROUP 为群聊",
     "1、D POST /{群}/join", "403 仅频道支持免审加入", "中", f7_join_free_only_channel)

# ---------------------------------------------------------------------------
# F8 兴趣频道
# ---------------------------------------------------------------------------
print("== F8 兴趣频道 ==")


def f8_create():
    r = api("POST", "/api/conversations/channel", token=A, json_body={
        "name": f"系统测试频道{TS}", "description": "系统测试用频道"})
    cid = r.json().get("conversation_id")
    case.__dict__["channel_id"] = cid
    return r.status_code == 201 and cid, f"{r.status_code} channel_id={cid}"


case("TC-F8-01", "创建频道", "A 已登录",
     "1、POST /api/conversations/channel 提交名称与简介", "201 返回 conversation_id", "高", f8_create)
CH = case.__dict__.get("channel_id")


def f8_square():
    r = api("GET", "/api/conversations/channels", token=D, params={"q": "系统测试频道"})
    j = r.json()
    hit = any(x["conversation_id"] == CH for x in j)
    joined = next((x["joined"] for x in j if x["conversation_id"] == CH), None)
    return r.status_code == 200 and hit and joined is False, \
        f"{r.status_code} 命中={hit} joined={joined}"


case("TC-F8-02", "频道广场可检索且标记未加入", "D 未加入该频道",
     "1、D GET /api/conversations/channels?q=系统测试频道",
     "200 列表含该频道且 joined=false", "中", f8_square)


def f8_join_free():
    r = api("POST", f"/api/conversations/{CH}/join", token=D)
    return r.status_code == 200, f"{r.status_code} {det(r)}"


case("TC-F8-03", "频道免审加入", "D 未加入频道",
     "1、D POST /{频道}/join", "200 免审直接加入", "高", f8_join_free)


def f8_join_dup():
    r = api("POST", f"/api/conversations/{CH}/join", token=D)
    return r.status_code == 400 and det(r) == "你已在该频道中", f"{r.status_code} {det(r)}"


case("TC-F8-04", "重复加入频道被拦截", "D 已加入",
     "1、D 再次 join", "400 你已在该频道中", "中", f8_join_dup)


def f8_post_not_member():
    # E 未加入频道，直接对频道发帖应 403
    r = api("POST", f"/api/conversations/{CH}/posts", token=E,
            json_body={"content": "非成员闯入帖"})
    return r.status_code == 403 and det(r) == "你不是该会话成员", f"{r.status_code} {det(r)}"


case("TC-F8-05", "非频道成员发帖被拦截", "E 未加入频道",
     "1、E POST /{频道}/posts", "403 你不是该会话成员", "高", f8_post_not_member)


def f8_post_empty():
    r = api("POST", f"/api/conversations/{CH}/posts", token=A, json_body={"content": ""})
    return r.status_code == 400 and det(r) == "帖子内容不能为空", f"{r.status_code} {det(r)}"


case("TC-F8-06", "空帖子被拦截", "A 是频道创建者",
     "1、POST posts content 为空、无图、无名片", "400 帖子内容不能为空", "中", f8_post_empty)


def f8_post_ok():
    r = api("POST", f"/api/conversations/{CH}/posts", token=A, json_body={
        "content": "频道第一条帖子：欢迎加入系统测试频道"})
    pid = r.json().get("id")
    case.__dict__["post1"] = pid
    return r.status_code == 201 and pid, f"{r.status_code} post_id={pid}"


case("TC-F8-07", "发布文字帖子", "A 是频道创建者",
     "1、POST posts 提交正文", "201 返回帖子详情", "高", f8_post_ok)
POST1 = case.__dict__.get("post1")


def f8_post_sensitive():
    r = api("POST", f"/api/conversations/{CH}/posts", token=A,
            json_body={"content": "这里有代考服务"})
    return r.status_code == 400 and det(r) and "敏感词" in det(r), f"{r.status_code} {det(r)}"


case("TC-F8-08", "帖子敏感词过滤", "词库含「代考」",
     "1、A 发含敏感词帖子", "400 内容包含敏感词：代考", "高", f8_post_sensitive)


def f8_post_too_many_images():
    imgs = [f"/uploads/fake{i}.jpg" for i in range(10)]
    r = api("POST", f"/api/conversations/{CH}/posts", token=A,
            json_body={"content": "十张图", "images": imgs})
    return r.status_code == 400 and det(r) == "图片最多 9 张", f"{r.status_code} {det(r)}"


case("TC-F8-09", "帖子图片数量上限 9 张", "—",
     "1、POST posts 携带 10 张图 URL", "400 图片最多 9 张", "中", f8_post_too_many_images)


def f8_post_fake_url():
    r = api("POST", f"/api/conversations/{CH}/posts", token=A,
            json_body={"content": "假图", "images": ["http://evil.com/a.jpg"]})
    return r.status_code == 400 and "上传接口" in det(r), f"{r.status_code} {det(r)}"


case("TC-F8-10", "帖子图片必须为上传接口返回的 URL", "—",
     "1、images 填站外 URL", "400 图片需先通过上传接口获取 URL", "中", f8_post_fake_url)


def f8_comment_two_levels():
    # 一级评论
    r1 = api("POST", f"/api/conversations/{CH}/posts/{POST1}/comments", token=D,
             json_body={"content": "一级评论"})
    c1 = r1.json()["id"]
    # 二级回复
    r2 = api("POST", f"/api/conversations/{CH}/posts/{POST1}/comments", token=A,
             json_body={"content": "二级回复", "parent_id": c1})
    c2 = r2.json()
    # 对二级回复再回复 → 应归位到一级
    r3 = api("POST", f"/api/conversations/{CH}/posts/{POST1}/comments", token=D,
             json_body={"content": "对二级的回复", "parent_id": c2["id"]})
    c3 = r3.json()
    ok = (r1.status_code == 201 and r2.status_code == 201 and r3.status_code == 201
          and c2["parent_id"] == c1 and c3["parent_id"] == c1)
    return ok, f"一级={c1} 二级parent={c2['parent_id']} 三级归位parent={c3['parent_id']}"


case("TC-F8-11", "二级评论与三级回复归位", "D、A 均为频道成员",
     "1、D 发一级评论\n2、A 回复（二级）\n3、D 再回复二级评论",
     "最多两级：第三层的 parent_id 自动归位到一级评论", "中", f8_comment_two_levels)


def f8_comment_sensitive():
    r = api("POST", f"/api/conversations/{CH}/posts/{POST1}/comments", token=A,
            json_body={"content": "这条评论在刷单"})
    return r.status_code == 400 and "敏感词" in (det(r) or ""), f"{r.status_code} {det(r)}"


case("TC-F8-12", "评论敏感词过滤", "词库含「刷单」",
     "1、A 发含敏感词评论", "400 评论包含敏感词：刷单", "高", f8_comment_sensitive)


def f8_like_idempotent():
    api("POST", f"/api/conversations/{CH}/posts/{POST1}/like", token=D)
    r1 = api("GET", f"/api/conversations/{CH}/posts/{POST1}", token=D).json()
    api("POST", f"/api/conversations/{CH}/posts/{POST1}/like", token=D)
    r2 = api("GET", f"/api/conversations/{CH}/posts/{POST1}", token=D).json()
    api("DELETE", f"/api/conversations/{CH}/posts/{POST1}/like", token=D)
    r3 = api("GET", f"/api/conversations/{CH}/posts/{POST1}", token=D).json()
    return r1["like_count"] == 1 and r2["like_count"] == 1 and r3["like_count"] == 0, \
        f"点赞后={r1['like_count']} 重复点赞={r2['like_count']} 取消后={r3['like_count']}"


case("TC-F8-13", "点赞幂等（重复点赞不叠加）", "D 是频道成员",
     "1、D 点赞\n2、再点赞一次\n3、取消点赞\n4、查 like_count",
     "like_count：1 → 1 → 0", "中", f8_like_idempotent)


def f8_sort_hot():
    # B 先免审加入频道，再发一条高互动帖；按 hot 排序应排在更新的无互动帖之前
    api("POST", f"/api/conversations/{CH}/join", token=B)
    r = api("POST", f"/api/conversations/{CH}/posts", token=D,
            json_body={"content": "热度帖"})
    hot_post = r.json()["id"]
    for _ in range(3):
        api("POST", f"/api/conversations/{CH}/posts/{hot_post}/like", token=A)
        api("POST", f"/api/conversations/{CH}/posts/{hot_post}/like", token=B)
        api("POST", f"/api/conversations/{CH}/posts/{hot_post}/like", token=D)
        api("DELETE", f"/api/conversations/{CH}/posts/{hot_post}/like", token=D)
    api("POST", f"/api/conversations/{CH}/posts/{hot_post}/like", token=D)
    # B 发一条无互动的新帖（时间更新）
    r_new = api("POST", f"/api/conversations/{CH}/posts", token=B,
                json_body={"content": "无互动新帖"})
    new_post = r_new.json()["id"]
    r = api("GET", f"/api/conversations/{CH}/posts", token=A,
            params={"sort": "hot", "limit": 10})
    ids = [p["id"] for p in r.json()]
    hot_idx = ids.index(hot_post) if hot_post in ids else 999
    new_idx = ids.index(new_post) if new_post in ids else 999
    return r.status_code == 200 and hot_idx < new_idx, \
        f"hot 排序：热度帖位次={hot_idx}，无互动新帖位次={new_idx}"


case("TC-F8-14", "帖子热度排序", "热度帖有点赞/评论，另有更新的无互动帖",
     "1、GET posts?sort=hot", "热度帖排在更新的无互动帖之前", "中", f8_sort_hot)


def f8_pin_by_non_admin():
    r = api("POST", f"/api/conversations/{CH}/posts/{POST1}/pin", token=D)
    return r.status_code == 403 and "群主或创建者" in (det(r) or ""), f"{r.status_code} {det(r)}"


case("TC-F8-15", "非频道管理置顶帖子被拦截", "D 是普通成员",
     "1、D POST posts/{id}/pin", "403 仅群主或创建者可执行此操作", "中", f8_pin_by_non_admin)


def f8_pin_by_owner():
    r = api("POST", f"/api/conversations/{CH}/posts/{POST1}/pin", token=A)
    posts = api("GET", f"/api/conversations/{CH}/posts", token=A,
                params={"sort": "time", "limit": 20}).json()
    pinned = [p for p in posts if p["is_pinned"]]
    return r.status_code == 200 and len(pinned) >= 1 and pinned[0]["id"] == POST1, \
        f"{r.status_code} 置顶帖数={len(pinned)}"


case("TC-F8-16", "频道创建者置顶帖子", "A 是频道创建者",
     "1、A POST posts/{id}/pin\n2、按时间序查帖子列表",
     "200；置顶帖排在最前且 is_pinned=true", "中", f8_pin_by_owner)


def f8_delete_post_forbidden():
    # D 删除 A 的帖子（非作者、非频道管理、非系统管理员）应 403
    r = api("DELETE", f"/api/conversations/{CH}/posts/{POST1}", token=D)
    return r.status_code == 403 and "仅作者或管理员" in (det(r) or ""), f"{r.status_code} {det(r)}"


case("TC-F8-17", "非作者非管理删帖被拦截", "D 非作者、非频道管理",
     "1、D DELETE posts/{A的帖子}", "403 仅作者或管理员可删除帖子", "高", f8_delete_post_forbidden)


def f8_delete_post_admin():
    # 系统管理员 alice 免审加入频道后可删任何人的帖（成员校验先于角色校验）
    api("POST", f"/api/conversations/{CH}/join", token=alice_tok)
    r = api("DELETE", f"/api/conversations/{CH}/posts/{POST1}", token=alice_tok)
    det_r = api("GET", f"/api/conversations/{CH}/posts/{POST1}", token=A)
    return r.status_code == 200 and det_r.status_code == 404, \
        f"删除 {r.status_code}；再查详情 {det_r.status_code}"


case("TC-F8-18", "系统管理员可删帖（软删占位）", "alice 是系统管理员",
     "1、alice DELETE posts/{id}\n2、再查帖子详情",
     "200；详情 404 帖子不存在或已删除（软删）", "中", f8_delete_post_admin)


def f8_comment_delete_placeholder():
    r1 = api("POST", f"/api/conversations/{CH}/posts", token=A,
             json_body={"content": "用于删评的帖子"})
    pid = r1.json()["id"]
    r2 = api("POST", f"/api/conversations/{CH}/posts/{pid}/comments", token=A,
             json_body={"content": "将被删除的一级评论"})
    c1 = r2.json()["id"]
    api("POST", f"/api/conversations/{CH}/posts/{pid}/comments", token=B,
        json_body={"content": "其下的二级回复", "parent_id": c1})
    api("DELETE", f"/api/conversations/{CH}/comments/{c1}", token=A)
    clist = api("GET", f"/api/conversations/{CH}/posts/{pid}/comments", token=A).json()
    placeholder = next((c for c in clist if c["id"] == c1), None)
    reply_kept = any(c["parent_id"] == c1 and c["content"] == "其下的二级回复"
                     for c in clist)
    ok = (placeholder is not None and placeholder["content"] == "[该评论已删除]"
          and placeholder["author"] is None and reply_kept)
    return ok, f"占位={placeholder and placeholder['content']} 二级保留={reply_kept}"


case("TC-F8-19", "删除评论软删占位、其下回复保留", "A 发帖子与评论，B 回复",
     "1、A 删除一级评论\n2、查评论列表",
     "一级评论占位「[该评论已删除]」作者置空；其下二级回复保留", "中", f8_comment_delete_placeholder)


def f8_not_member_read():
    # E 未加入频道，读帖子应 403
    r = api("GET", f"/api/conversations/{CH}/posts", token=E)
    return r.status_code == 403 and det(r) == "你不是该会话成员", f"{r.status_code} {det(r)}"


case("TC-F8-20", "非频道成员读帖子被拦截", "E 未加入频道",
     "1、E GET posts", "403 你不是该会话成员", "高", f8_not_member_read)


def f8_comment_like():
    pid = api("POST", f"/api/conversations/{CH}/posts", token=A,
              json_body={"content": "评论点赞测试帖"}).json()["id"]
    cid = api("POST", f"/api/conversations/{CH}/posts/{pid}/comments", token=D,
              json_body={"content": "评论点赞测试评论"}).json()["id"]
    api("POST", f"/api/conversations/{CH}/comments/{cid}/like", token=A)
    n1 = next(c for c in api("GET", f"/api/conversations/{CH}/posts/{pid}/comments",
                             token=A).json() if c["id"] == cid)["like_count"]
    api("POST", f"/api/conversations/{CH}/comments/{cid}/like", token=A)
    n2 = next(c for c in api("GET", f"/api/conversations/{CH}/posts/{pid}/comments",
                             token=A).json() if c["id"] == cid)["like_count"]
    api("DELETE", f"/api/conversations/{CH}/comments/{cid}/like", token=A)
    n3 = next(c for c in api("GET", f"/api/conversations/{CH}/posts/{pid}/comments",
                             token=A).json() if c["id"] == cid)["like_count"]
    return n1 == 1 and n2 == 1 and n3 == 0, \
        f"点赞={n1} 重复点赞={n2} 取消点赞后={n3}"


case("TC-F8-21", "评论点赞与取消（幂等）", "A、D 均为频道成员",
     "1、A 点赞评论\n2、再次点赞\n3、取消点赞\n4、每步查 like_count",
     "like_count：1 → 1 → 0", "中", f8_comment_like)


def f8_edit_post():
    pid = api("POST", f"/api/conversations/{CH}/posts", token=A,
              json_body={"content": "待编辑的帖子"}).json()["id"]
    r = api("PUT", f"/api/conversations/{CH}/posts/{pid}", token=A,
            json_body={"content": "编辑后的正文"})
    return r.status_code == 200 and r.json()["content"] == "编辑后的正文", \
        f"{r.status_code} content={r.json().get('content')}"


case("TC-F8-22", "编辑本人帖子", "A 是帖子作者",
     "1、A POST 发帖\n2、A PUT /posts/{id} 修改正文",
     "200 返回更新后的帖子", "中", f8_edit_post)


def f8_edit_post_forbidden():
    pid = api("POST", f"/api/conversations/{CH}/posts", token=A,
              json_body={"content": "别人的帖子"}).json()["id"]
    r = api("PUT", f"/api/conversations/{CH}/posts/{pid}", token=D,
            json_body={"content": "篡改他人正文"})
    return r.status_code == 403 and "仅作者本人" in (det(r) or ""), f"{r.status_code} {det(r)}"


case("TC-F8-23", "编辑他人帖子被拦截", "D 非该帖作者",
     "1、D PUT /posts/{A的帖子}", "403 仅作者本人可编辑帖子", "高", f8_edit_post_forbidden)


def f8_unpin_post():
    pid = api("POST", f"/api/conversations/{CH}/posts", token=A,
              json_body={"content": "待取消置顶帖"}).json()["id"]
    api("POST", f"/api/conversations/{CH}/posts/{pid}/pin", token=A)
    r = api("DELETE", f"/api/conversations/{CH}/posts/{pid}/pin", token=A)
    posts = api("GET", f"/api/conversations/{CH}/posts", token=A,
                params={"sort": "time", "limit": 20}).json()
    still = any(p["id"] == pid and p["is_pinned"] for p in posts)
    return r.status_code == 200 and not still, f"取消置顶 {r.status_code}；仍为置顶={still}"


case("TC-F8-24", "取消帖子置顶", "A 是频道创建者",
     "1、A 置顶帖子\n2、A DELETE /posts/{id}/pin\n3、查列表确认",
     "200；该帖不再是置顶", "中", f8_unpin_post)

# ---------------------------------------------------------------------------
# F9 富媒体消息
# ---------------------------------------------------------------------------
print("== F9 富媒体消息 ==")


def f9_upload_image():
    data = bytes.fromhex("89504e470d0a1a0a") + b"\x00" * 1024  # PNG 头
    r = api("POST", "/api/upload", token=A,
            files={"file": ("photo.png", data, "image/png")})
    j = r.json()
    case.__dict__["img_url"] = j.get("url")
    return r.status_code == 200 and j.get("kind") == "image" \
        and j.get("url", "").startswith("/uploads/"), f"{r.status_code} {j}"


case("TC-F9-01", "上传图片成功", "A 已登录",
     "1、POST /api/upload 上传 png 图片", "200 返回 /uploads/ URL 与 kind=image", "高", f9_upload_image)
IMG_URL = case.__dict__.get("img_url")


def f9_upload_oversize_image():
    data = b"\xff\xd8\xff\xe0" + b"\x00" * (11 * 1024 * 1024)  # 11MB jpeg
    r = api("POST", "/api/upload", token=A,
            files={"file": ("big.jpg", data, "image/jpeg")})
    return r.status_code == 400 and "10MB" in (det(r) or ""), f"{r.status_code} {det(r)}"


case("TC-F9-02", "图片超过 10MB 被拦截", "—",
     "1、上传 11MB 的 jpeg", "400 文件超过 10MB 上限", "高", f9_upload_oversize_image)


def f9_upload_exe():
    r = api("POST", "/api/upload", token=A,
            files={"file": ("malware.exe", b"MZ fake", "application/octet-stream")})
    return r.status_code == 400 and "不支持的文件类型" in (det(r) or ""), f"{r.status_code} {det(r)}"


case("TC-F9-03", "可执行文件类型被白名单拦截", "—",
     "1、上传 application/octet-stream 伪装 exe", "400 不支持的文件类型", "高", f9_upload_exe)


def f9_upload_pdf():
    data = b"%PDF-1.4 fake" + b"\x00" * 2048
    r = api("POST", "/api/upload", token=A,
            files={"file": ("doc.pdf", data, "application/pdf")})
    j = r.json()
    return r.status_code == 200 and j.get("kind") == "file", f"{r.status_code} {j.get('kind')}"


case("TC-F9-04", "上传白名单文件（pdf）", "—",
     "1、上传 application/pdf", "200 kind=file", "中", f9_upload_pdf)


def f9_upload_oversize_file():
    data = b"%PDF-1.4" + b"\x00" * (51 * 1024 * 1024)
    r = api("POST", "/api/upload", token=A,
            files={"file": ("big.pdf", data, "application/pdf")})
    return r.status_code == 400 and "50MB" in (det(r) or ""), f"{r.status_code} {det(r)}"


case("TC-F9-05", "文件超过 50MB 被拦截", "—",
     "1、上传 51MB 的 pdf", "400 文件超过 50MB 上限", "高", f9_upload_oversize_file)


def f9_fake_mime():
    """伪装扩展名：客户端传 .html 但声明 image/png，落盘扩展名应由服务端按 MIME 推导为 .png。"""
    r = api("POST", "/api/upload", token=A,
            files={"file": ("evil.html", b"\x89PNG fake", "image/png")})
    j = r.json()
    url = j.get("url", "")
    safe = url.endswith(".png")
    # 物理校验：文件落在 uploads 内，且 uploads 外没有 evil.html
    be_uploads = os.path.join(ROOT, "backend", "uploads")
    leaked = os.path.exists(os.path.join(ROOT, "backend", "evil.html"))
    disk_ok = os.path.exists(os.path.join(be_uploads, os.path.basename(url))) if url else False
    return r.status_code == 200 and safe and disk_ok and not leaked, \
        f"url={url} 落盘存在={disk_ok} 无路径泄漏={not leaked}"


case("TC-F9-06", "伪装扩展名由服务端按 MIME 重命名", "—",
     "1、客户端 filename=evil.html 但 Content-Type=image/png",
     "落盘扩展名为 .png；文件在 uploads 内；uploads 外无泄漏文件", "高", f9_fake_mime)


def f9_image_msg():
    ws_a = connect(f"{WS}?token={A}", open_timeout=8)
    try:
        ws_send(ws_a, {"type": "send_message", "conversation_id": CONV_AB,
                       "msg_type": "image", "content": IMG_URL})
        m = ws_recv(ws_a)
        return m["data"]["msg_type"] == "image" and m["data"]["content"] == IMG_URL, \
            f"{m['data'].get('msg_type')} content={m['data'].get('content')}"
    finally:
        ws_a.close()


case("TC-F9-07", "发送图片消息", "已拿到上传接口返回的 URL",
     "1、WS 发送 msg_type=image，content 为 /uploads/ URL",
     "收到 image 消息且 content 为图片 URL", "高", f9_image_msg)


def f9_image_msg_no_upload():
    ws_a = connect(f"{WS}?token={A}", open_timeout=8)
    try:
        ws_send(ws_a, {"type": "send_message", "conversation_id": CONV_AB,
                       "msg_type": "image", "content": "http://evil.com/x.png"})
        m = ws_recv(ws_a)
        return m.get("type") == "error" and "上传接口" in m.get("detail", ""), \
            f"{m.get('type')} {m.get('detail')}"
    finally:
        ws_a.close()


case("TC-F9-08", "图片消息 URL 非上传接口来源被拦截", "—",
     "1、WS 发送 image，content 为站外 URL",
     "error 帧：请先调用上传接口获取文件 URL", "高", f9_image_msg_no_upload)

# ---------------------------------------------------------------------------
# F10 消息管理
# ---------------------------------------------------------------------------
print("== F10 消息管理 ==")


def f10_unread():
    # B 未读 CONV_AB 中的新消息
    ws_a = connect(f"{WS}?token={A}", open_timeout=8)
    try:
        for i in range(3):
            ws_send(ws_a, {"type": "send_message", "conversation_id": CONV_AB,
                           "msg_type": "text", "content": f"未读测试{i}"})
            ws_recv(ws_a)
    finally:
        ws_a.close()
    convs = api("GET", "/api/conversations", token=B).json()
    conv = next((c for c in convs if c["conversation_id"] == CONV_AB), None)
    return conv is not None and conv["unread"] >= 3, f"未读数={conv and conv['unread']}"


case("TC-F10-01", "未读红点统计", "B 离线时 A 发 3 条消息",
     "1、A 向私聊发 3 条消息\n2、B 查会话列表",
     "该会话 unread>=3", "高", f10_unread)


def f10_read():
    r = api("POST", f"/api/conversations/{CONV_AB}/read", token=B)
    convs = api("GET", "/api/conversations", token=B).json()
    conv = next((c for c in convs if c["conversation_id"] == CONV_AB), None)
    return r.status_code == 200 and conv["unread"] == 0, \
        f"已读 {r.status_code}；未读归 0 = {conv['unread'] == 0}"


case("TC-F10-02", "标记已读后未读归零", "B 有未读",
     "1、B POST /{会话}/read\n2、再查会话列表",
     "unread=0", "高", f10_read)


def f10_recall_ok():
    ws_a = connect(f"{WS}?token={A}", open_timeout=8)
    try:
        ws_send(ws_a, {"type": "send_message", "conversation_id": CONV_AB,
                       "msg_type": "text", "content": "这条马上撤回"})
        m = ws_recv(ws_a)
        mid = m["data"]["id"]
    finally:
        ws_a.close()
    r = api("POST", f"/api/conversations/messages/{mid}/recall", token=A)
    hist = api("GET", f"/api/conversations/{CONV_AB}/messages", token=A,
               params={"limit": 5}).json()
    target = next((x for x in hist if x["id"] == mid), None)
    return r.status_code == 200 and target is not None \
        and target["content"] == "" and target["recalled_at"] is not None, \
        f"撤回 {r.status_code}；历史中 content 空 = {target and target['content'] == ''}"


case("TC-F10-03", "3 分钟内撤回自己的消息", "A 刚发出一条消息",
     "1、A POST /messages/{id}/recall\n2、再拉历史",
     "200；历史中该消息 content 置空、带 recalled_at（软撤回非删除）", "高", f10_recall_ok)


def f10_recall_others():
    # 先让 B 发一条消息，再由 A（非发送者）尝试撤回
    ws_b = connect(f"{WS}?token={B}", open_timeout=8)
    try:
        ws_send(ws_b, {"type": "send_message", "conversation_id": CONV_AB,
                       "msg_type": "text", "content": "B的消息，A不许撤回"})
        m = ws_recv(ws_b)
        mid = m["data"]["id"]
    finally:
        ws_b.close()
    r = api("POST", f"/api/conversations/messages/{mid}/recall", token=A)
    return r.status_code == 403 and det(r) == "只能撤回自己的消息", f"{r.status_code} {det(r)}"


case("TC-F10-04", "撤回他人消息被拦截", "A 不是该消息发送者",
     "1、A 撤回 B 的消息", "403 只能撤回自己的消息", "高", f10_recall_others)


def f10_pin_channel_msg():
    # 在频道置顶一条消息（话题帖）
    ws_a = connect(f"{WS}?token={A}", open_timeout=8)
    try:
        ws_send(ws_a, {"type": "send_message", "conversation_id": CH,
                       "msg_type": "text", "content": "频道话题帖内容"})
        m = ws_recv(ws_a)
        mid = m["data"]["id"]
    finally:
        ws_a.close()
    r = api("POST", f"/api/conversations/{CH}/messages/{mid}/pin", token=A)
    convs = api("GET", "/api/conversations", token=A).json()
    conv = next(c for c in convs if c["conversation_id"] == CH)
    # 再置顶另一条验证唯一化
    ws_a = connect(f"{WS}?token={A}", open_timeout=8)
    try:
        ws_send(ws_a, {"type": "send_message", "conversation_id": CH,
                       "msg_type": "text", "content": "第二篇话题帖"})
        m2 = ws_recv(ws_a)
        mid2 = m2["data"]["id"]
    finally:
        ws_a.close()
    r2 = api("POST", f"/api/conversations/{CH}/messages/{mid2}/pin", token=A)
    hist = api("GET", f"/api/conversations/{CH}/messages", token=A,
               params={"limit": 50}).json()
    pinned = [x for x in hist if x["is_pinned"]]
    return r.status_code == 200 and r2.status_code == 200 and len(pinned) == 1 \
        and pinned[0]["id"] == mid2, f"置顶数={len(pinned)} 当前置顶={pinned and pinned[0]['id']}"


case("TC-F10-05", "频道置顶消息且唯一化", "A 是频道创建者",
     "1、置顶消息A\n2、再置顶消息B\n3、查历史中的 is_pinned",
     "始终只有 1 条置顶（新置顶顶掉旧置顶）", "中", f10_pin_channel_msg)


def f10_pin_group_forbidden():
    hist = api("GET", f"/api/conversations/{GROUP}/messages", token=A,
               params={"limit": 5}).json()
    mid = hist[-1]["id"]
    r = api("POST", f"/api/conversations/{GROUP}/messages/{mid}/pin", token=A)
    return r.status_code == 404 and det(r) == "仅频道支持置顶话题帖", f"{r.status_code} {det(r)}"


case("TC-F10-06", "群聊禁止置顶消息", "GROUP 为群聊",
     "1、A POST 群消息 pin", "404 仅频道支持置顶话题帖", "中", f10_pin_group_forbidden)


def f10_unpin_message():
    ws_a = connect(f"{WS}?token={A}", open_timeout=8)
    try:
        ws_send(ws_a, {"type": "send_message", "conversation_id": CH,
                       "msg_type": "text", "content": "待取消置顶的话题帖"})
        m = ws_recv(ws_a)
        mid = m["data"]["id"]
    finally:
        ws_a.close()
    api("POST", f"/api/conversations/{CH}/messages/{mid}/pin", token=A)
    r = api("DELETE", f"/api/conversations/{CH}/messages/{mid}/pin", token=A)
    hist = api("GET", f"/api/conversations/{CH}/messages", token=A,
               params={"limit": 50}).json()
    still = any(x["id"] == mid and x["is_pinned"] for x in hist)
    return r.status_code == 200 and not still, \
        f"取消置顶 {r.status_code}；仍为置顶={still}"


case("TC-F10-07", "取消频道消息置顶", "A 是频道创建者",
     "1、A 置顶消息\n2、A DELETE /messages/{id}/pin\n3、查历史确认 is_pinned",
     "200；该消息不再是置顶", "中", f10_unpin_message)


def f10_recall_notice():
    """撤回后向会话内全部成员广播 system_notice 帧（含操作者本人）。"""
    ws_a = connect(f"{WS}?token={A}", open_timeout=8)
    ws_b = connect(f"{WS}?token={B}", open_timeout=8)
    try:
        ws_send(ws_a, {"type": "send_message", "conversation_id": CONV_AB,
                       "msg_type": "text", "content": "待撤回并广播"})
        mid = ws_recv(ws_a)["data"]["id"]
        ws_recv(ws_b)  # B 先收到 receive_message
        api("POST", f"/api/conversations/messages/{mid}/recall", token=A)
        na = ws_recv(ws_a)
        nb = ws_recv(ws_b)
        ok = (na.get("type") == "system_notice"
              and na["data"].get("event") == "message_recalled"
              and na["data"].get("message_id") == mid
              and nb.get("type") == "system_notice"
              and nb["data"].get("event") == "message_recalled")
        return ok, (f"A收到 {na.get('type')}/{na.get('data', {}).get('event')}；"
                    f"B收到 {nb.get('type')}/{nb.get('data', {}).get('event')}")
    finally:
        ws_a.close()
        ws_b.close()


case("TC-F10-08", "撤回广播 system_notice 帧", "A、B 同时在线且在同一会话",
     "1、A 发消息\n2、A 撤回该消息\n3、观察双方 WS 收到的帧",
     "双方均收到 system_notice 且 event=message_recalled，message_id 一致", "高", f10_recall_notice)

# ---------------------------------------------------------------------------
# F11 规则机器人
# ---------------------------------------------------------------------------
print("== F11 规则机器人 ==")


def f11_help():
    ws_a = connect(f"{WS}?token={A}", open_timeout=8)
    try:
        ws_send(ws_a, {"type": "send_message", "conversation_id": CONV_AB,
                       "msg_type": "text", "content": "/help"})
        user_msg = ws_recv(ws_a)
        bot_msg = ws_recv(ws_a)  # 机器人回复
        ok = (user_msg["data"]["content"] == "/help"
              and bot_msg["data"]["sender_type"] == "bot"
              and "指令" in bot_msg["data"]["content"])
        return ok, f"bot回复={bot_msg['data']['sender_type']}:{bot_msg['data']['content'][:30]}"
    finally:
        ws_a.close()


case("TC-F11-01", "/help 触发机器人回复", "A 已连 WS",
     "1、发送文本 /help", "机器人以 sender_type=bot 回复指令帮助", "中", f11_help)


def f11_signin():
    ws_a = connect(f"{WS}?token={A}", open_timeout=8)
    try:
        ws_send(ws_a, {"type": "send_message", "conversation_id": CONV_AB,
                       "msg_type": "text", "content": "/签到"})
        ws_recv(ws_a)
        bot_msg = ws_recv(ws_a)
        return bot_msg["data"]["sender_type"] == "bot" and "签到" in bot_msg["data"]["content"], \
            bot_msg["data"]["content"][:30]
    finally:
        ws_a.close()


case("TC-F11-02", "/签到 触发机器人回复", "—",
     "1、发送文本 /签到", "机器人回复签到文案", "中", f11_signin)


def f11_keyword():
    ws_a = connect(f"{WS}?token={A}", open_timeout=8)
    try:
        ws_send(ws_a, {"type": "send_message", "conversation_id": CONV_AB,
                       "msg_type": "text", "content": "谁能帮帮我？"})
        user_msg = ws_recv(ws_a)
        got = False
        # 关键词「帮助」不在此句中，机器人不应回复；再发含关键词的
        if user_msg["data"]["sender_type"] == "user":
            ws_send(ws_a, {"type": "send_message", "conversation_id": CONV_AB,
                           "msg_type": "text", "content": "帮助 在哪里"})
            ws_recv(ws_a)
            bot_msg = ws_recv(ws_a)
            got = bot_msg["data"]["sender_type"] == "bot" and "指令" in bot_msg["data"]["content"]
        return got, f"关键词命中回复={got}"
    finally:
        ws_a.close()


case("TC-F11-03", "关键词「帮助」唤醒机器人", "—",
     "1、发不含关键词的文本（不触发）\n2、发含「帮助」的文本（触发）",
     "仅含关键词时机器人回复", "中", f11_keyword)

# ---------------------------------------------------------------------------
# F12 内容治理（举报 + 学号审核）
# ---------------------------------------------------------------------------
print("== F12 内容治理 ==")


def f12_report():
    ws_a = connect(f"{WS}?token={A}", open_timeout=8)
    try:
        ws_send(ws_a, {"type": "send_message", "conversation_id": CONV_AB,
                       "msg_type": "text", "content": "违规内容样本"})
        m = ws_recv(ws_a)
        mid = m["data"]["id"]
    finally:
        ws_a.close()
    case.__dict__["report_mid"] = mid
    r = api("POST", "/api/reports", token=B,
            json_body={"message_id": mid, "reason": "测试举报"})
    return r.status_code == 201 and "report_id" in r.json(), f"{r.status_code} {r.json()}"


case("TC-F12-01", "提交举报", "B 看到 A 的违规消息",
     "1、B POST /api/reports 填消息 id 与理由", "201 返回 report_id", "高", f12_report)
REPORT_MID = case.__dict__.get("report_mid")


def f12_report_dup():
    r = api("POST", "/api/reports", token=B,
            json_body={"message_id": REPORT_MID, "reason": "重复举报"})
    return r.status_code == 400 and det(r) == "你已举报过该消息，请等待处理", f"{r.status_code} {det(r)}"


case("TC-F12-02", "重复举报同一消息被拦截", "B 已举报过该消息",
     "1、再次举报同一消息", "400 你已举报过该消息，请等待处理", "中", f12_report_dup)


def f12_report_list_forbidden():
    r = api("GET", "/api/reports", token=B)
    return r.status_code == 403 and det(r) == "仅管理员可执行此操作", f"{r.status_code} {det(r)}"


case("TC-F12-03", "非管理员查看举报列表被拦截", "B 是普通用户",
     "1、B GET /api/reports", "403 仅管理员可执行此操作", "高", f12_report_list_forbidden)


def f12_report_list_admin():
    r = api("GET", "/api/reports", token=alice_tok, params={"status": "pending"})
    j = r.json()
    has = any(x["message_id"] == REPORT_MID for x in j)
    return r.status_code == 200 and has, f"{r.status_code} 待处理含被举报消息={has}"


case("TC-F12-04", "管理员查看待处理举报", "存在待处理举报",
     "1、alice GET /api/reports?status=pending", "200 列表含该举报", "高", f12_report_list_admin)


def f12_verify_submit():
    proof = b"\xff\xd8\xff\xe0" + b"\x00" * 2048  # jpeg
    r = api("POST", "/api/verifications/student-id", token=F, data={
        "new_student_id": f"{TS}99", "user_note": "学号录错了，申请更正"},
        files={"proof": ("proof.jpg", proof, "image/jpeg")})
    return r.status_code == 201 and r.json().get("status") == "pending", \
        f"{r.status_code} {r.json()}"


case("TC-F12-05", "提交学号变更申请（含证明材料）", f"{USER['f']['username']} 已登录",
     "1、POST /api/verifications/student-id 上传证明材料", "201 进入待审核", "高", f12_verify_submit)


def f12_verify_dup():
    proof = b"\xff\xd8\xff\xe0" + b"\x00" * 2048
    r = api("POST", "/api/verifications/student-id", token=F, data={
        "new_student_id": f"{TS}98"}, files={"proof": ("p.jpg", proof, "image/jpeg")})
    return r.status_code == 400 and det(r) == "你已有一个待审核的申请，请等待管理员处理", \
        f"{r.status_code} {det(r)}"


case("TC-F12-06", "重复提交学号变更被拦截", f"{USER['f']['username']} 有待审申请",
     "1、再次提交申请", "400 你已有一个待审核的申请，请等待管理员处理", "中", f12_verify_dup)


def f12_verify_my():
    r = api("GET", "/api/verifications/my", token=F)
    j = r.json()
    return r.status_code == 200 and any(x["status"] == "pending" for x in j), \
        f"{r.status_code} 我的申请数={len(j)}"


case("TC-F12-07", "查询我的学号申请进展", f"{USER['f']['username']} 已提交",
     "1、GET /api/verifications/my", "200 含 pending 申请", "中", f12_verify_my)


def f12_verify_list_admin():
    r = api("GET", "/api/verifications", token=alice_tok, params={"req_status": "pending"})
    j = r.json()
    req = next((x for x in j if x["user_id"] == USER["f"]["id"]), None)
    case.__dict__["verify_id"] = req["request_id"] if req else None
    return r.status_code == 200 and req is not None and req["has_proof"], \
        f"{r.status_code} 找到F的申请={req is not None} has_proof={req and req['has_proof']}"


case("TC-F12-08", "管理员查看待审学号列表", "存在待审申请",
     "1、alice GET /api/verifications?req_status=pending",
     "200 含 F 的申请且 has_proof=true", "高", f12_verify_list_admin)
VERIFY_ID = case.__dict__.get("verify_id")


def f12_proof_forbidden():
    r = api("GET", f"/api/verifications/{VERIFY_ID}/proof", token=B)
    return r.status_code == 403, f"{r.status_code} {det(r)}"


case("TC-F12-09", "非管理员调阅证明材料被拦截", "B 是普通用户",
     "1、B GET /api/verifications/{id}/proof", "403", "高", f12_proof_forbidden)


def f12_proof_admin():
    r = api("GET", f"/api/verifications/{VERIFY_ID}/proof", token=alice_tok)
    return r.status_code == 200 and r.headers.get("content-type", "").startswith("image/"), \
        f"{r.status_code} content-type={r.headers.get('content-type')}"


case("TC-F12-10", "管理员调阅证明材料", f"存在 request_id={VERIFY_ID} 的申请",
     "1、alice GET /api/verifications/{id}/proof", "200 返回图片", "中", f12_proof_admin)


def f12_verify_reject_no_reason():
    r = api("POST", f"/api/verifications/{VERIFY_ID}/review", token=alice_tok,
            json_body={"action": "reject"})
    return r.status_code == 400 and det(r) == "驳回必须填写理由", f"{r.status_code} {det(r)}"


case("TC-F12-11", "驳回学号申请必须填写理由", f"存在 request_id={VERIFY_ID} 的申请",
     "1、alice 提交 reject 且 note 为空", "400 驳回必须填写理由", "中", f12_verify_reject_no_reason)


def f12_verify_approve_and_proof_deleted():
    r = api("POST", f"/api/verifications/{VERIFY_ID}/review", token=alice_tok,
            json_body={"action": "approve", "note": "材料属实"})
    me = api("GET", "/api/auth/me", token=F).json()
    proof = api("GET", f"/api/verifications/{VERIFY_ID}/proof", token=alice_tok)
    return r.status_code == 200 and me["student_id"] == f"{TS}99" \
        and proof.status_code == 404, \
        f"审核 {r.status_code}；F学号={me['student_id']}；审核后材料 {proof.status_code}"


case("TC-F12-12", "审核通过后学号生效且证明材料被清除", f"存在 request_id={VERIFY_ID} 的申请",
     "1、alice 提交 approve\n2、F 查个人资料\n3、再调阅证明材料",
     "200；F 学号更新；证明材料 404（数据最小化）", "高", f12_verify_approve_and_proof_deleted)

# ---------------------------------------------------------------------------
# ADM 管理后台
# ---------------------------------------------------------------------------
print("== ADM 管理后台 ==")


def adm_overview():
    r = api("GET", "/api/admin/overview", token=alice_tok)
    j = r.json()
    keys = {"pending_reports", "pending_verifications", "users_total", "users_active"}
    return r.status_code == 200 and keys.issubset(j.keys()), \
        f"{r.status_code} users_total={j.get('users_total')}"


case("TC-ADM-01", "管理端总览计数", "alice 已登录管理端",
     "1、GET /api/admin/overview", "200 返回各类计数（不含用户内容）", "高", adm_overview)


def adm_forbidden():
    r = api("GET", "/api/admin/overview", token=B)
    return r.status_code == 403 and det(r) == "仅管理员可执行该操作", f"{r.status_code} {det(r)}"


case("TC-ADM-02", "普通用户访问管理接口被拒（垂直越权）", "B 无管理员权限",
     "1、B GET /api/admin/overview", "403 仅管理员可执行该操作", "高", adm_forbidden)


def adm_users_list():
    r = api("GET", "/api/admin/users", token=alice_tok,
            params={"q": USER["a"]["username"], "status": "all", "page": 1, "page_size": 10})
    j = r.json()
    hit = any(x["username"] == USER["a"]["username"] for x in j["items"])
    return r.status_code == 200 and j["total"] >= 1 and hit, f"{r.status_code} total={j.get('total')}"


case("TC-ADM-03", "账号列表搜索与分页", "—",
     f"1、GET /api/admin/users?q={USER['a']['username']}", "200 命中目标账号", "中", adm_users_list)


def adm_disable_self():
    alice_id = api("GET", "/api/auth/me", token=alice_tok).json()["id"]
    r = api("PUT", f"/api/admin/users/{alice_id}/status", token=alice_tok,
            json_body={"active": False})
    return r.status_code == 400 and det(r) == "不能禁用当前登录的管理员账号", f"{r.status_code} {det(r)}"


case("TC-ADM-04", "管理员禁用自己被拦截", "alice 是管理员",
     "1、alice 对自己 PUT status active=false", "400 不能禁用当前登录的管理员账号", "中", adm_disable_self)


def adm_disable_bot():
    # 注意：管理端账号列表按设计排除机器人（is_bot=False 过滤），
    # 这里直接拿库里的 bot id 验证服务端拦截分支。
    r = api("PUT", f"/api/admin/users/{BOT_ID}/status", token=alice_tok,
            json_body={"active": False})
    return r.status_code == 400 and det(r) == "系统机器人账号不可禁用", f"{r.status_code} {det(r)}"


case("TC-ADM-05", "禁用机器人账号被拦截", "helper_bot 存在（管理端列表不显示，取库内 id）",
     "1、alice 禁用 helper_bot", "400 系统机器人账号不可禁用", "中", adm_disable_bot)


def adm_disable_user_three_points():
    # 三处生效：登录、旧令牌、WS 握手
    r1 = api("PUT", f"/api/admin/users/{USER['e']['id']}/status", token=alice_tok,
             json_body={"active": False})
    login_r = login(USER["e"]["username"])
    token_r = api("GET", "/api/auth/me", token=E)
    ws_note = ""
    try:
        connect(f"{WS}?token={E}", open_timeout=5)
        ws_ok = False
        ws_note = "握手竟然成功"
    except Exception as ex:  # noqa
        ws_ok = ("403" in str(ex)) or ("1008" in str(ex)) or ("Invalid Status" in str(ex))
        ws_note = f"握手被拒: {type(ex).__name__}"
    ok = (r1.status_code == 200 and login_r.status_code == 403
          and token_r.status_code == 401 and ws_ok)
    return ok, (f"禁用 {r1.status_code}；登录 {login_r.status_code}；"
                f"旧令牌 {token_r.status_code} {det(token_r)}；WS {ws_note}")


case("TC-ADM-06", "禁用账号三处同时生效", f"{USER['e']['username']} 持有有效令牌与 WS 能力",
     "1、alice 禁用 E\n2、E 重新登录\n3、E 用旧令牌调 /me\n4、E 尝试建立 WS",
     "登录 403；旧令牌 401「账号已被禁用」；WS 握手被拒（close 1008）", "高", adm_disable_user_three_points)


def adm_enable_user():
    api("PUT", f"/api/admin/users/{USER['e']['id']}/status", token=alice_tok,
        json_body={"active": False})
    r = api("PUT", f"/api/admin/users/{USER['e']['id']}/status", token=alice_tok,
            json_body={"active": True})
    rl = login(USER["e"]["username"])
    return r.status_code == 200 and rl.status_code == 200, \
        f"启用 {r.status_code}；登录 {rl.status_code}"


case("TC-ADM-07", "解禁后账号恢复可用", f"{USER['e']['username']} 曾被禁用",
     "1、alice 启用 E\n2、E 重新登录", "200；登录 200", "中", adm_enable_user)


def adm_reset_pwd():
    r = api("POST", f"/api/admin/users/{USER['d']['id']}/reset-password", token=alice_tok,
            json_body={"new_password": "Reset12345"})
    rl = login(USER["d"]["username"], "Reset12345")
    return r.status_code == 200 and rl.status_code == 200, \
        f"重置 {r.status_code}；新口令登录 {rl.status_code}"


case("TC-ADM-08", "管理员重置用户口令", "—",
     "1、alice POST reset-password new_password=Reset12345\n2、D 用新口令登录",
     "200；新口令可登录", "中", adm_reset_pwd)


def adm_grant_admin():
    r = api("PUT", f"/api/admin/users/{USER['d']['id']}/admin", token=alice_tok,
            json_body={"is_admin": True})
    me = api("GET", "/api/auth/me", token=D).json()
    return r.status_code == 200 and me["is_admin"] is True, f"{r.status_code} D.is_admin={me['is_admin']}"


case("TC-ADM-09", "授予管理员权限", "—",
     "1、alice PUT users/{D}/admin is_admin=true\n2、D 查 /me", "200；D 的 is_admin=true", "中", adm_grant_admin)


def adm_revoke_self():
    r = api("PUT", f"/api/admin/users/{USER['a']['id'] if False else 1}/admin",
            token=alice_tok, json_body={"is_admin": False})
    # 用 alice 自己的 id（1）撤销自己
    return r.status_code == 400 and det(r) == "不能撤销自己的管理员权限", f"{r.status_code} {det(r)}"


case("TC-ADM-10", "撤销自己的管理员权限被拦截", "alice 是管理员",
     "1、alice PUT users/{自己}/admin is_admin=false", "400 不能撤销自己的管理员权限", "中", adm_revoke_self)

# 恢复 D 的普通身份，避免影响后续
api("PUT", f"/api/admin/users/{USER['d']['id']}/admin", token=alice_tok,
    json_body={"is_admin": False})


def adm_change_sid():
    r = api("PUT", f"/api/admin/users/{USER['d']['id']}/student-id", token=alice_tok,
            json_body={"student_id": f"{TS}77"})
    me = api("GET", "/api/auth/me", token=D).json()
    return r.status_code == 200 and me["student_id"] == f"{TS}77", \
        f"{r.status_code} D.student_id={me['student_id']}"


case("TC-ADM-11", "管理员直改学号并留痕", "—",
     f"1、alice PUT users/{{D}}/student_id={TS}77\n2、D 查 /me",
     "200；D 的学号已更新", "中", adm_change_sid)

# ---------------------------------------------------------------------------
# S 安全性测试
# ---------------------------------------------------------------------------
print("== S 安全性测试 ==")


def s_no_token():
    r = api("GET", "/api/conversations")
    return r.status_code == 401, f"{r.status_code} {det(r)}"


case("TC-S-01", "无令牌访问业务接口", "—",
     "1、GET /api/conversations（无 Authorization）", "401", "高", s_no_token)


def s_fake_token():
    r = api("GET", "/api/conversations", token="not.a.validtoken")
    return r.status_code == 401 and det(r) == "令牌无效或已过期", f"{r.status_code} {det(r)}"


case("TC-S-02", "伪造令牌访问", "—",
     "1、携带随机字符串令牌", "401 令牌无效或已过期", "高", s_fake_token)


def s_tampered_token():
    valid = login(USER["a"]["username"]).json()["access_token"]
    tampered = valid[:-2] + ("aa" if not valid.endswith("aa") else "bb")
    r = api("GET", "/api/auth/me", token=tampered)
    return r.status_code == 401, f"{r.status_code} {det(r)}"


case("TC-S-03", "篡改 JWT 签名", "拿到他人有效令牌",
     "1、修改令牌末尾字符后访问", "401（签名校验失败）", "高", s_tampered_token)


def s_expired_token():
    secret = None
    with open(os.path.join(ROOT, "backend", ".env"), encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("SECRET_KEY="):
                secret = line.strip().split("=", 1)[1]
    import jwt as pyjwt
    past = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=10)
    expired = pyjwt.encode(
        {"sub": str(USER["a"]["id"]), "exp": past}, secret, algorithm="HS256")
    r = api("GET", "/api/auth/me", token=expired)
    return r.status_code == 401 and det(r) == "令牌无效或已过期", f"{r.status_code} {det(r)}"


case("TC-S-04", "过期令牌被拒绝", "可用 SECRET_KEY 构造过期令牌",
     "1、签发 exp 已过的令牌并访问", "401 令牌无效或已过期", "高", s_expired_token)


def s_admin_api_normal_user():
    r = api("PUT", f"/api/admin/users/{USER['b']['id']}/status", token=B,
            json_body={"active": False})
    return r.status_code == 403, f"{r.status_code} {det(r)}"


case("TC-S-05", "普通用户调用管理接口（垂直越权）", "B 无管理员权限",
     "1、B 调 PUT /api/admin/users/{id}/status", "403", "高", s_admin_api_normal_user)


def s_report_admin_inline():
    r = api("GET", "/api/reports", token=B)
    return r.status_code == 403, f"{r.status_code} {det(r)}"


case("TC-S-06", "普通用户查看举报列表（内联鉴权）", "B 无管理员权限",
     "1、B GET /api/reports", "403", "高", s_report_admin_inline)


def s_verify_admin_inline():
    r = api("GET", "/api/verifications", token=B)
    return r.status_code == 403, f"{r.status_code} {det(r)}"


case("TC-S-07", "普通用户查看学号审核列表（内联鉴权）", "B 无管理员权限",
     "1、B GET /api/verifications", "403", "高", s_verify_admin_inline)


def s_read_other_conversation():
    # B 不是「B的私密群」成员时已被移除；改用 A 的私聊：C 不是 CONV_AB 成员
    r = api("GET", f"/api/conversations/{CONV_AB}/messages", token=C)
    return r.status_code == 403, f"{r.status_code} {det(r)}"


case("TC-S-08", "非成员读取他人私聊历史（水平越权）", "C 不是 A-B 私聊成员",
     "1、C GET /api/conversations/{私聊}/messages", "403", "高", s_read_other_conversation)


def s_ws_no_token():
    try:
        connect(f"{WS}", open_timeout=5)
        return False, "无令牌握手竟然成功"
    except Exception as ex:  # noqa
        ok = ("403" in str(ex)) or ("Invalid Status" in str(ex)) or ("401" in str(ex))
        return ok, f"握手被拒: {type(ex).__name__}"


case("TC-S-09", "WS 无令牌握手被拒", "—",
     "1、不带 token 连接 /ws", "握手失败（close 1008 / HTTP 403）", "高", s_ws_no_token)


def s_sql_injection_login():
    r = api("POST", "/api/auth/login", json_body={
        "username": "alice' OR '1'='1' --", "password": "x"})
    ok = r.status_code == 400 and det(r) == "用户名或密码错误"
    # 二次确认：真账号仍可正常登录
    ok2 = login(USER["a"]["username"]).status_code == 200
    return ok and ok2, f"注入登录 {r.status_code} {det(r)}；正常账号未受影响={ok2}"


case("TC-S-10", "登录 SQL 注入", "—",
     "1、username=alice' OR '1'='1' -- 登录", "400 用户名或密码错误，不影响正常账号", "高", s_sql_injection_login)


def s_xss_stored():
    payload = "<script>alert('xss')</script>"
    ws_a = connect(f"{WS}?token={A}", open_timeout=8)
    try:
        ws_send(ws_a, {"type": "send_message", "conversation_id": CONV_AB,
                       "msg_type": "text", "content": payload})
        ws_recv(ws_a)
    finally:
        ws_a.close()
    hist = api("GET", f"/api/conversations/{CONV_AB}/messages", token=A,
               params={"limit": 1}).json()
    stored = hist[-1]["content"] == payload
    # 前端检索确认无 v-html（静态检查，报告引用）
    src = os.path.join(ROOT, "frontend", "src")
    uses_vhtml = False
    for dp, _, fns in os.walk(src):
        for fn in fns:
            if fn.endswith((".vue", ".js")):
                with open(os.path.join(dp, fn), encoding="utf-8", errors="ignore") as fh:
                    if "v-html" in fh.read() or "innerHTML" in fh.read():
                        uses_vhtml = True
    return stored and not uses_vhtml, \
        f"原样存储（JSON 转义）={stored}；前端未使用 v-html/innerHTML = {not uses_vhtml}"


case("TC-S-11", "存储型 XSS：消息脚本原样存储、前端无 v-html", "—",
     "1、发送含 <script> 的消息\n2、拉取历史核对\n3、全仓检索前端 v-html",
     "内容原样存储且 JSON 响应转义；前端无 v-html/innerHTML，不会执行", "高", s_xss_stored)


def s_private_dir_not_mounted():
    vdir = os.path.join(ROOT, "backend", "private_uploads")
    leaked_name = None
    if os.path.isdir(vdir):
        for fn in os.listdir(vdir):
            leaked_name = fn
            break
    if not leaked_name:
        # 现场造一个私密文件验证不可经静态访问
        os.makedirs(vdir, exist_ok=True)
        leaked_name = f"probe_{TS}.jpg"
        with open(os.path.join(vdir, leaked_name), "wb") as fh:
            fh.write(b"\xff\xd8\xff\xe0 probe")
    r1 = requests.get(f"{BASE}/private_uploads/{leaked_name}", timeout=10)
    r2 = requests.get(f"{BASE}/uploads/../private_uploads/{leaked_name}",
                      timeout=10, allow_redirects=False)
    ok = r1.status_code == 404 and r2.status_code != 200
    return ok, f"直接访问 {r1.status_code}；路径穿越 {r2.status_code}"


case("TC-S-12", "私密目录不可经静态路由访问", "private_uploads 存在私密文件",
     "1、GET /private_uploads/{文件}\n2、GET /uploads/../private_uploads/{文件}",
     "均不可读取（404/禁止）", "高", s_private_dir_not_mounted)


def s_sensitive_message():
    ws_a = connect(f"{WS}?token={A}", open_timeout=8)
    try:
        ws_send(ws_a, {"type": "send_message", "conversation_id": CONV_AB,
                       "msg_type": "text", "content": "详情加微信详聊"})
        m = ws_recv(ws_a)
        return m.get("type") == "error" and "敏感词" in m.get("detail", ""), \
            f"{m.get('type')} {m.get('detail')}"
    finally:
        ws_a.close()


case("TC-S-13", "消息敏感词事中拦截（不落库）", "词库含「加微信详聊」",
     "1、WS 发送含敏感词的文本", "error 帧提示敏感词，消息不落库", "高", s_sensitive_message)


def s_sensitive_no_store():
    before = len(api("GET", f"/api/conversations/{CONV_AB}/messages", token=A,
                     params={"limit": 50}).json())
    ws_a = connect(f"{WS}?token={A}", open_timeout=8)
    try:
        ws_send(ws_a, {"type": "send_message", "conversation_id": CONV_AB,
                       "msg_type": "text", "content": "开票找我"})
        ws_recv(ws_a)
    finally:
        ws_a.close()
    after = len(api("GET", f"/api/conversations/{CONV_AB}/messages", token=A,
                    params={"limit": 50}).json())
    return after == before, f"拦截前后消息条数 {before} → {after}"


case("TC-S-14", "敏感词消息不落库", "—",
     "1、记录当前历史条数\n2、发敏感词消息被拒\n3、再查历史条数",
     "条数不变（未落库）", "高", s_sensitive_no_store)


def s_search_by_sid():
    r = api("GET", "/api/users/search", token=A, params={"q": USER["b"]["sid"]})
    return r.status_code == 200 and r.json() == [], f"{r.status_code} 结果数={len(r.json())}"


case("TC-S-15", "按学号检索不可命中（隐私）", f"{USER['b']['sid']} 属于 B",
     "1、GET /api/users/search?q=<B的学号>", "200 空列表", "高", s_search_by_sid)


def s_ban_via_report():
    # E 免审加入频道后发一条消息，A（频道成员）举报，alice 处置并封号
    api("POST", f"/api/conversations/{CH}/join", token=E)
    ws_e = connect(f"{WS}?token={E}", open_timeout=8)
    try:
        ws_send(ws_e, {"type": "send_message", "conversation_id": CH,
                       "msg_type": "text", "content": "待举报处置的消息"})
        m = ws_recv(ws_e)
        mid = m["data"]["id"]
    finally:
        ws_e.close()
    api("POST", "/api/reports", token=A,
        json_body={"message_id": mid, "reason": "垃圾信息"})
    rl = api("GET", "/api/reports", token=alice_tok, params={"status": "pending"})
    rid = next(x["report_id"] for x in rl.json() if x["message_id"] == mid)
    r = api("PUT", f"/api/reports/{rid}", token=alice_tok,
            json_body={"action": "resolved", "punish": "ban"})
    login_r = login(USER["e"]["username"])
    token_r = api("GET", "/api/auth/me", token=E)
    ws_note = ""
    try:
        connect(f"{WS}?token={E}", open_timeout=5)
        ws_ok = False
        ws_note = "握手成功"
    except Exception as ex:  # noqa
        ws_ok = True
        ws_note = type(ex).__name__
    ok = (r.status_code == 200 and r.json().get("banned")
          and login_r.status_code == 403 and token_r.status_code == 401 and ws_ok)
    # 解除封禁，避免影响环境
    api("PUT", f"/api/admin/users/{USER['e']['id']}/status", token=alice_tok,
        json_body={"active": True})
    return ok, (f"处置 {r.status_code} banned={r.json().get('banned')}；"
                f"登录 {login_r.status_code}；旧令牌 {token_r.status_code}；WS {ws_note}")


case("TC-S-16", "举报处置+封号闭环（封禁三处生效）", "E 是群成员",
     "1、E 发消息，A 举报\n2、alice 处置 resolved+ban\n3、E 登录/旧令牌/WS 各验一次",
     "处置成功；登录 403、旧令牌 401、WS 握手被拒", "高", s_ban_via_report)


def s_pwd_not_in_response():
    r = login(USER["a"]["username"])
    rl = api("GET", "/api/auth/me", token=r.json()["access_token"])
    return "password" not in rl.text and "password_hash" not in rl.text, \
        f"响应含口令字段 = {'password' in rl.text}"


case("TC-S-17", "接口响应不回显口令/哈希", "—",
     "1、登录并 GET /me\n2、检查响应体", "无任何口令字段", "中", s_pwd_not_in_response)


def s_register_enum():
    # 用户名不存在 vs 密码错误返回相同提示（已在 F3 覆盖，这里测注册面不可枚举）
    r1 = api("POST", "/api/auth/login",
             json_body={"username": "alice", "password": "wrongpass1"})
    r2 = api("POST", "/api/auth/login",
             json_body={"username": "ghost_user_xyz", "password": "wrongpass1"})
    return r1.status_code == r2.status_code == 400 and det(r1) == det(r2), \
        f"错误密码 {det(r1)}；不存在用户 {det(r2)}"


case("TC-S-18", "登录提示不区分「用户不存在」与「密码错误」", "—",
     "1、正确用户名+错误密码\n2、不存在用户名+任意密码",
     "两者均 400 用户名或密码错误（防枚举）", "高", s_register_enum)


def s_cursor_invalid():
    r = api("GET", f"/api/conversations/{CONV_AB}/messages", token=A,
            params={"cursor": "not-a-date", "limit": 10})
    return r.status_code == 400 and det(r) == "cursor 格式非法", f"{r.status_code} {det(r)}"


case("TC-S-19", "非法游标被拦截", "—",
     "1、GET messages?cursor=not-a-date", "400 cursor 格式非法", "中", s_cursor_invalid)


def s_negative_limit():
    r = api("GET", f"/api/conversations/{CONV_AB}/messages", token=A,
            params={"limit": 0})
    # 健壮性观察：不应 500
    return r.status_code != 500, f"{r.status_code}"


case("TC-S-20", "limit=0 边界（健壮性）", "—",
     "1、GET messages?limit=0", "不返回 500（实际行为记录）", "低", s_negative_limit)


def s_msg_type_card_bot():
    ws_a = connect(f"{WS}?token={A}", open_timeout=8)
    try:
        ws_send(ws_a, {"type": "send_message", "conversation_id": CONV_AB,
                       "msg_type": "card", "content": "999999"})
        m = ws_recv(ws_a)
        return m.get("type") == "error" and "被推荐的用户不存在" in m.get("detail", ""), \
            f"{m.get('type')} {m.get('detail')}"
    finally:
        ws_a.close()


case("TC-S-21", "名片消息指向不存在用户被拦截", "—",
     "1、WS 发送 card，content=999999", "error 帧 被推荐的用户不存在", "中", s_msg_type_card_bot)


def s_reply_other_conv():
    # 引用回复指向其它会话的消息应被拒
    hist = api("GET", f"/api/conversations/{GROUP}/messages", token=A,
               params={"limit": 1}).json()
    foreign_mid = hist[-1]["id"] if hist else None
    ws_a = connect(f"{WS}?token={A}", open_timeout=8)
    try:
        ws_send(ws_a, {"type": "send_message", "conversation_id": CONV_AB,
                       "msg_type": "text", "content": "跨会话引用",
                       "reply_to_id": foreign_mid})
        m = ws_recv(ws_a)
        return m.get("type") == "error" and "被引用" in m.get("detail", ""), \
            f"{m.get('type')} {m.get('detail')}"
    finally:
        ws_a.close()


case("TC-S-22", "引用回复跨会话被拦截", "—",
     "1、reply_to_id 指向另一会话的消息", "error 帧 被引用的消息不存在", "中", s_reply_other_conv)

# ---------------------------------------------------------------------------
# 收尾：原生模式直接出报告退出；pytest 模式动态生成逐条 test 函数
# ---------------------------------------------------------------------------
if not RUNNING_PYTEST:
    print("\n== 汇总 ==")
    passed = sum(1 for r in RESULTS if r["result"] == "通过")
    failed = [r for r in RESULTS if r["result"] == "失败"]
    print(f"总计 {len(RESULTS)} 条，通过 {passed}，失败 {len(failed)}")
    for r in failed:
        print(f"  失败: {r['cid']} {r['title']}")
        print(f"        预期: {r['expected']}")
        print(f"        实际: {r['actual']}")

    out = os.path.join(os.path.dirname(__file__), "test_results.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({
            "meta": {
                "ts": TS,
                "base": BASE, "frontend": FE,
                "started_at": dt.datetime.now().isoformat(),
                "total": len(RESULTS), "passed": passed, "failed": len(failed),
            },
            "cases": RESULTS,
        }, fh, ensure_ascii=False, indent=2)
    print(f"结果已写入 {out}")
    sys.exit(1 if failed else 0)
else:
    # pytest 模式：用例已在导入期按序执行完（与原生同一时序），这里为每条
    # 结果生成一个 test 函数，给 pytest 提供逐条报告与退出码。
    def _make_test(entry):
        """把一条已执行的用例包成 pytest test：失败信息带上预期/实际对照。"""
        def _test():
            assert entry["result"] == "通过", \
                f"预期: {entry['expected']} | 实际: {entry['actual']}"
        return _test

    for _i, _e in enumerate(RESULTS, 1):
        _name = f"test_{_i:03d}_{_e['cid'].replace('-', '_').lower()}"
        _fn = _make_test(_e)
        _fn.__name__ = _name
        _fn.__doc__ = f"{_e['cid']} {_e['title']}（{_e['priority']}）"
        globals()[_name] = _fn
    del _i, _e
