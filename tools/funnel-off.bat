@echo off
chcp 65001 >nul
title 有谱掌柜 · 关站
echo [关站] 停止公网暴露（本机版 127.0.0.1:8100 与 Pages 预览站不受影响）
echo.
"C:\Program Files\Tailscale\tailscale.exe" funnel off
echo.
echo 已关闭。想再开：双击 funnel-on.bat
pause
