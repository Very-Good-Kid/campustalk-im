@echo off
chcp 65001 >nul
setlocal
title CampusTalk 一键启动

rem ============================================================
rem  CampusTalk 校园即时通讯系统 · 一键启动
rem  双击本文件即可：检查环境 -> 安装依赖 -> 初始化数据库
rem                 -> 启动后端(5109) 与前端(5108) -> 打开浏览器
rem
rem  端口约定（改端口需三处同步：本文件、frontend/vite.config.js、frontend/README.md）
rem    前端 Vite    5108
rem    后端 uvicorn 5109
rem ============================================================

set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"
set "FRONTEND=%ROOT%frontend"
set "BACKEND_PORT=5109"
set "FRONTEND_PORT=5108"

echo ============================================================
echo    CampusTalk 校园即时通讯系统 · 一键启动
echo ============================================================
echo.

if not exist "%BACKEND%\app\main.py" (
  echo [错误] 未找到后端目录：%BACKEND%
  echo        请将本脚本放在项目根目录（与 backend、frontend 同级）运行。
  pause
  exit /b 1
)

rem ---------- 1/5 环境检查 ----------
where python >nul 2>nul
if errorlevel 1 (
  echo [错误] 未检测到 Python，请先安装 Python 3.11+ 并加入 PATH。
  pause
  exit /b 1
)
where node >nul 2>nul
if errorlevel 1 (
  echo [错误] 未检测到 Node.js，请先安装 Node.js 并加入 PATH。
  pause
  exit /b 1
)
echo [1/5] 环境检查通过

rem ---------- 2/5 后端依赖 ----------
python -c "import fastapi, uvicorn, sqlalchemy, aiomysql, dotenv, jwt, bcrypt, multipart, redis" >nul 2>nul
if errorlevel 1 (
  echo [2/5] 正在安装后端依赖...
  pushd "%BACKEND%"
  python -m pip install -r requirements.txt
  popd
) else (
  echo [2/5] 后端依赖已就绪
)

rem ---------- 3/5 前端依赖 ----------
if not exist "%FRONTEND%\node_modules" (
  echo [3/5] 正在安装前端依赖（首次较慢，请耐心等待）...
  pushd "%FRONTEND%"
  call npm install
  popd
) else (
  echo [3/5] 前端依赖已就绪
)

rem ---------- 4/5 初始化数据库（幂等，失败不阻塞） ----------
echo [4/5] 初始化数据库（建表 / 补列 / 预置演示账号）...
pushd "%BACKEND%"
python init_db.py
if errorlevel 1 (
  echo.
  echo [提示] 数据库初始化未成功。请确认：
  echo        1. MySQL 已启动（默认 127.0.0.1:3306）；
  echo        2. 已创建数据库 campustalk（utf8mb4）；
  echo        3. backend/.env 中的 DATABASE_URL 账号密码正确。
  echo        建库语句见 backend/init_db.py 顶部注释。
  echo.
)
popd

rem ---------- 5/5 启动前后端 ----------
echo [5/5] 启动后端与前端...

rem Redis 总线硬依赖检查：后端连不上 6379 会启动即退出（fail fast），
rem 这里提前拦住并说人话，避免用户对着 uvicorn 报错窗口发懵。
netstat -ano | findstr ":6379 " | findstr "LISTENING" >nul
if errorlevel 1 (
  echo       [错误] 未检测到 Redis 总线监听 6379 端口（Redis 服务未运行）。
  echo              后端对 Redis 是硬依赖，跳过启动。请打开 services.msc
  echo              启动 Redis 服务（或手动运行 redis-server）后重试本脚本。
  set "SKIP_BACKEND=1"
) else (
  echo       Redis 总线就绪（127.0.0.1:6379）
)

rem 端口占用检测必须叠加 LISTENING：否则"某个进程正在连接该端口"的
rem SYN_SENT / TIME_WAIT 行也会被 findstr 命中，误判"端口已被占用"而跳过启动，
rem 结果前后端一个都没起来（已踩坑）。
netstat -ano | findstr ":%BACKEND_PORT% " | findstr "LISTENING" >nul
if defined SKIP_BACKEND (
  echo       [提示] 因 Redis 未就绪，本脚本不启动后端
) else if errorlevel 1 (
  start "CampusTalk Backend" /d "%BACKEND%" cmd /k python -m uvicorn app.main:app --host 127.0.0.1 --port %BACKEND_PORT%
) else (
  echo       [提示] %BACKEND_PORT% 端口已被占用，跳过后端启动（若已是本项目的后端可忽略）
)

netstat -ano | findstr ":%FRONTEND_PORT% " | findstr "LISTENING" >nul
if errorlevel 1 (
  start "CampusTalk Frontend" /d "%FRONTEND%" cmd /k npm run dev
) else (
  echo       [提示] %FRONTEND_PORT% 端口已被占用，跳过前端启动（若已是本项目的前端可忽略）
)

echo.
echo 等待前端就绪...
rem 用 ping 代替 timeout 等待：timeout 在标准输入被重定向时会立即报错退出
ping -n 7 127.0.0.1 >nul
start "" "http://127.0.0.1:%FRONTEND_PORT%"

echo.
echo ============================================================
echo    启动完成
echo ------------------------------------------------------------
echo    用户端    http://127.0.0.1:%FRONTEND_PORT%
echo    管理端    http://127.0.0.1:%FRONTEND_PORT%/admin/login   （管理员账号登录）
echo    接口文档  http://127.0.0.1:%BACKEND_PORT%/docs
echo ------------------------------------------------------------
echo    演示账号  alice / 123456（管理员）、bob / 123456
echo    关闭本窗口不会停止服务；请分别关闭两个服务窗口以停止。
echo ============================================================
echo.
pause
