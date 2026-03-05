#!/bin/bash
# status.sh — Node health for dashboard header
# Uses env vars: NODE_HOME, NODE_RPC, NODE_RPC_HTTP, WALLET_NAME, KEYRING_BACKEND
HOME_DIR="${NODE_HOME:-/root/.republicd}"
RPC="${NODE_RPC:-tcp://localhost:26657}"
RPC_HTTP="${NODE_RPC_HTTP:-http://localhost:26657}"
WNAME="${WALLET_NAME:-my-wallet}"
KB="${KEYRING_BACKEND:-test}"
RPC_PORT="${NODE_RPC_PORT:-26657}"

VALOPER=$(republicd keys show "$WNAME" --bech val -a --home "$HOME_DIR" --keyring-backend "$KB" 2>/dev/null)
WALLET=$(republicd keys show "$WNAME" -a --home "$HOME_DIR" --keyring-backend "$KB" 2>/dev/null)
STATUS_JSON=$(curl -s "$RPC_HTTP/status")
BLOCK=$(echo "$STATUS_JSON" | jq -r '.result.sync_info.latest_block_height')
SYNCING=$(echo "$STATUS_JSON" | jq -r '.result.sync_info.catching_up')
PEERS=$(curl -s "$RPC_HTTP/net_info" | jq -r '.result.n_peers')

VAL_RAW=$(republicd query staking validator "$VALOPER" --node "$RPC" -o json 2>/dev/null)
TOKENS=$(echo "$VAL_RAW" | jq -r '(.validator.tokens // .tokens) // "0"')
VAL_STATUS=$(echo "$VAL_RAW" | jq -r '(.validator.status // .status) // "?"')
MONIKER=$(echo "$VAL_RAW" | jq -r '(.validator.description.moniker // .description.moniker) // "?"')
JAILED=$(echo "$VAL_RAW" | jq -r '(.validator.jailed // .jailed) // false')

BAL_JSON=$(republicd query bank balances "$WALLET" --node "$RPC" -o json 2>/dev/null)
BALANCE=$(echo "$BAL_JSON" | jq -r '.balances[] | select(.denom=="arai") | .amount' 2>/dev/null)
BALANCE=${BALANCE:-0}

echo "=== Node Health ==="
echo "  Wallet:    $WALLET"
echo "  Valoper:   $VALOPER"
echo "  Moniker:   $MONIKER"
echo "  Status:    $VAL_STATUS"
echo "  Jailed:    $JAILED"
TOKENS_RAI=$(python3 -c "print(f'{int(\"$TOKENS\")/1e18:.2f}')" 2>/dev/null || echo "?")
BALANCE_RAI=$(python3 -c "print(f'{int(\"$BALANCE\")/1e18:.2f}')" 2>/dev/null || echo "?")
echo "  Staked:    $TOKENS_RAI RAI"
echo "  Liquid:    $BALANCE_RAI RAI"
echo "  Block:     $BLOCK"
echo "  Syncing:   $SYNCING"
echo "  Peers:     $PEERS"
echo ""
echo "JSON_START"
printf '{"wallet":"%s","valoper":"%s","moniker":"%s","status":"%s","jailed":%s,"tokens":"%s","balance":"%s","block":"%s","syncing":%s,"peers":"%s"}\n' \
  "$WALLET" "$VALOPER" "$MONIKER" "$VAL_STATUS" "$JAILED" "$TOKENS" "$BALANCE" "$BLOCK" "$SYNCING" "$PEERS"
