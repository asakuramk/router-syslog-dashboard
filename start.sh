#!/bin/bash
# Syslog Dashboard 起動スクリプト

cd "$(dirname "$0")"

# 依存パッケージのインストール
echo "📦 依存パッケージを確認中..."
pip3 install fastapi uvicorn --quiet 2>/dev/null || python3 -m pip install fastapi uvicorn --quiet

# IPエイリアス設定 (192.168.50.100 が必要な場合)
# 注意: Routerのsyslog送信先が 192.168.50.100 なら以下を有効化
# sudo ifconfig en0 alias 192.168.50.100 255.255.255.0

echo ""
echo "================================================"
echo "  Syslog Dashboard"
echo "  UDP ポート 514 (sudo必要) でログ受信"
echo "  ダッシュボード: http://localhost:8080"
echo "================================================"
echo ""

# sudo で起動 (port 514 のため)
sudo python3 server.py
