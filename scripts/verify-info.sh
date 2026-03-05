#!/bin/bash
# verify-info.sh — Gather verification form data
VALOPER=$(republicd keys show my-wallet --bech val -a --home /root/.republicd --keyring-backend test 2>/dev/null)
WALLET=$(republicd keys show my-wallet -a --home /root/.republicd --keyring-backend test 2>/dev/null)

echo "=== Verification Information ==="
echo ""
echo "Validator Address:  $VALOPER"
echo "Wallet Address:     $WALLET"
echo ""
echo "=== GPU Info ==="
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader 2>/dev/null
echo ""
echo "=== System Info ==="
echo "OS: $(cat /etc/os-release | grep PRETTY_NAME | cut -d= -f2 | tr -d '"')"
echo "Kernel: $(uname -r)"
echo "CPU: $(grep 'model name' /proc/cpuinfo | head -1 | cut -d: -f2 | xargs)"
echo "RAM: $(free -h | awk '/Mem:/{print $2}')"
echo "Docker: $(docker --version 2>/dev/null || echo 'N/A')"
echo ""
echo "=== Node Status ==="
curl -s http://localhost:26657/status | jq -r '.result | "  Block: \(.sync_info.latest_block_height)\n  Syncing: \(.sync_info.catching_up)\n  Node: \(.node_info.moniker)"'
echo ""
echo "=== Recent Jobs ==="
republicd query computevalidation list-job --node tcp://localhost:26657 -o json 2>/dev/null | jq -r ".jobs[] | select(.target_validator==\"$VALOPER\") | \"  Job #\(.id) | \(.status)\""
