#!/bin/zsh
cd "${0:A:h}"
if ! command -v uv >/dev/null; then
  echo "请先安装 uv：https://docs.astral.sh/uv/"
  exit 1
fi
echo "启动后请打开 http://127.0.0.1:8769/"
exec uv run python server.py
