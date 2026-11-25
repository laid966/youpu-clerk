@echo off
chcp 65001 >nul
title 有谱掌柜 · 后端（正式站）
cd /d E:\myfirstagent
echo [后端] 启动 uvicorn @ 127.0.0.1:8100
echo        公网入口 https://zcc.tail408b90.ts.net （funnel 已开时）
echo        本站运行期间请勿关闭此窗口（可最小化）
echo.
.\.venv\Scripts\python.exe -m uvicorn clerk.server:app --host 127.0.0.1 --port 8100
pause
