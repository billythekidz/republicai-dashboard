#!/bin/bash
# Detect RepublicAI node config
echo "=== Config files ==="
ls /root/.republicd/config/

echo ""
echo "=== client.toml ==="
cat /root/.republicd/config/client.toml 2>/dev/null

echo ""
echo "=== config.toml (ports) ==="
grep -E "^laddr|^proxy_app|^moniker" /root/.republicd/config/config.toml 2>/dev/null

echo ""
echo "=== app.toml (api/grpc) ==="
grep -E "^address|^enable" /root/.republicd/config/app.toml 2>/dev/null | head -20

echo ""
echo "=== Keyring wallets ==="
republicd keys list --home /root/.republicd --keyring-backend test -o json 2>/dev/null | jq -r '.[].name'

echo ""
echo "=== Systemd services ==="
systemctl list-unit-files --type=service | grep -i republic
