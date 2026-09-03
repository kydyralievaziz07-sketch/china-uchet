#!/bin/bash
cd "$(dirname "$0")"
( sleep 1.2; open "http://localhost:8902" ) &
python3 server.py
