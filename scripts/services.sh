#!/bin/bash
# services.sh — Systemd + Docker status
echo "=== Systemd Services ==="
for svc in republicd republic-sidecar republic-autocompute republic-http republic-dashboard cloudflared; do
  st=$(systemctl is-active "$svc" 2>/dev/null || echo "not-found")
  printf "  %-28s %s\n" "$svc" "$st"
done
echo ""
echo "=== Docker Containers ==="
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || echo "  Docker not available"
