#!/bin/bash
cd "$(dirname "$0")"
# секреты бота и прочие местные настройки, если есть
for f in .bot.env .local.env; do [ -f "$f" ] && set -a && . "./$f" && set +a; done
( sleep 1.2; open "http://localhost:8902" ) &
python3 server.py
