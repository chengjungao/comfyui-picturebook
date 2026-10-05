#!/usr/bin/env bash
# 绘本工坊启动脚本（macOS / Linux）
set -e
cd "$(dirname "$0")"

export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1

if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo
  echo "  [X] 没有找到 Python 3。先装一个：https://www.python.org/downloads/"
  echo
  exit 1
fi

if ! "$PY" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 8) else 1)"; then
  echo
  echo "  [X] Python 版本太低，需要 3.8 或以上。当前：$("$PY" --version 2>&1)"
  echo
  exit 1
fi

exec "$PY" app.py "$@"
