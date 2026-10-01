#!/usr/bin/env bash
# 15分钟生活圈 · 智能体检助手 — Linux/macOS 一键启动
# 访问地址：http://127.0.0.1:8000
set -e
cd "$(dirname "$0")/.."

if [ ! -x "backend/.venv/bin/python" ]; then
  echo "[1/2] 首次运行：创建虚拟环境并安装依赖..."
  python3 -m venv backend/.venv
  backend/.venv/bin/python -m pip install --disable-pip-version-check -q -r backend/requirements.txt
fi

echo "[2/2] 启动服务：http://127.0.0.1:8000 （Ctrl+C 停止）"
backend/.venv/bin/python backend/run.py
