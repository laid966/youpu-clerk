@echo off
chcp 65001 >nul
title 有谱掌柜 · 开站
echo [开站] 把本机 8100 端口暴露为公网 HTTPS（ts.net 域名固定不变）
echo.
"C:\Program Files\Tailscale\tailscale.exe" funnel --bg 8100
echo.
echo 当前组网状态：
"C:\Program Files\Tailscale\tailscale.exe" status
echo.
pause
