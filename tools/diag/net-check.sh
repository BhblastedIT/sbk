#!/bin/bash

host="${1:-api.anthropic.com}"
echo "== $host =="
for i in 1 2 3; do
 curl -s -o /dev/null -w "  dns=%{time_namelookup}s connect=%{time_connect}s tls=%{time_appconnect}s ttfb=%{time_starttransfer}s total=%{time_total}s http=%{http_code}\n" "https://$host/v1/messages" -X POST -H "content-type: application/json" -d '{}' --max-time 15
done
ping -c 5 "$host" 2>/dev/null | tail -2
