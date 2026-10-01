@echo off
rem ============================================
rem 15分钟生活圈 · 智能体检助手 — Windows 一键启动
rem 首次运行自动创建虚拟环境并安装依赖，之后直接启动
rem 访问地址：http://127.0.0.1:8000
rem ============================================
cd /d "%~dp0\.."

if not exist "backend\.venv\Scripts\python.exe" (
  echo [1/2] 首次运行：创建虚拟环境并安装依赖...
  python -m venv backend\.venv
  if errorlevel 1 (
    echo 创建虚拟环境失败，请确认已安装 Python 3.10+ 并加入 PATH
    pause & exit /b 1
  )
  backend\.venv\Scripts\python -m pip install --disable-pip-version-check -q -r backend\requirements.txt
  if errorlevel 1 (
    echo 依赖安装失败，请检查网络后重试
    pause & exit /b 1
  )
)

echo [2/2] 启动服务：http://127.0.0.1:8000 （Ctrl+C 停止）
backend\.venv\Scripts\python backend\run.py
pause
