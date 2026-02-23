#!/bin/bash
# run.sh - Linux用ラッパースクリプト
# M5StickC Claude Code notification クライアントを実行
# 使用法: ./run.sh [options]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$SCRIPT_DIR/client.py" "$@"
