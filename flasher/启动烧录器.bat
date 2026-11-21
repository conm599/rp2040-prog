@echo off
chcp 65001 >nul
cd /d "%~dp0"
title debugprobe 一键烧录器

rem 优先用 py 启动器，其次 PATH 里的 python
set "PY=python"
where py >nul 2>nul && set "PY=py -3"

echo 正在启动烧录器服务…浏览器会自动打开 http://127.0.0.1:8731/
echo 关闭本窗口即停止服务。
echo.

%PY% -u launcher.py

echo.
echo 服务已退出。
pause
