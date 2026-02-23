# run.ps1 - Windows / WSL2 用ラッパースクリプト
# M5StickC Claude Code notification クライアントを実行
# 使用法: .\run.ps1 [options] または pwsh -NoProfile -Command ". .\run.ps1 --test"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
python "$ScriptDir/client.py" @args
