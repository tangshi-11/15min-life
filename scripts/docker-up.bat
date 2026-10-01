@echo off
rem 使用 Docker 启动：docker compose up --build
rem 访问地址：http://127.0.0.1:8000
cd /d "%~dp0\.."
docker compose up --build
pause
