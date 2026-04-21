#!/bin/bash
# Syslog Dashboard 起動（sudo で port 514 をリッスン）

DIR="$(dirname "$0")"

pkill -f "python3 server.py" 2>/dev/null
sleep 1

osascript -e "do shell script \"python3 '$DIR/server.py' > /tmp/syslog-dashboard.log 2>&1 &\" with administrator privileges"

sleep 3

if curl -s http://localhost:8080 > /dev/null 2>&1; then
  osascript -e 'display notification "Syslog Dashboard 起動完了！ http://localhost:8080" with title "Syslog Dashboard"'
  open http://localhost:8080
  echo "起動完了"
else
  cat /tmp/syslog-dashboard.log
fi
