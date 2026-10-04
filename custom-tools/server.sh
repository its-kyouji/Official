#!/bin/bash
# Local development and testing runner script
echo "Starting local execution simulation..."
python3 /app/render/render.py 2>/dev/null || true
exec /usr/bin/supervisord -c /app/supervisord.conf
