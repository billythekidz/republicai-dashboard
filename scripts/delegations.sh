#!/bin/bash
# delegations.sh — Uses env vars from server
VALOPER="${WALLET_VALOPER}"
RPC="${NODE_RPC:-tcp://localhost:26657}"

# Fallback
if [ -z "$VALOPER" ]; then
    HOME_DIR="${NODE_HOME:-/root/.republicd}"
    WNAME="${WALLET_NAME:-my-wallet}"
    KB="${KEYRING_BACKEND:-test}"
    VALOPER=$(republicd keys show "$WNAME" --bech val -a --home "$HOME_DIR" --keyring-backend "$KB" 2>/dev/null)
fi

echo "Valoper: $VALOPER"
echo ""

republicd query staking validator "$VALOPER" --node "$RPC" -o json > /tmp/val_info.json 2>/dev/null
republicd query staking delegations-to "$VALOPER" --node "$RPC" -o json > /tmp/delegations.json 2>/dev/null
python3 << 'PYEOF'
import json
try:
    v = json.load(open("/tmp/val_info.json"))
    val = v.get("validator", v)
    d = json.load(open("/tmp/delegations.json"))
    print(f"Moniker: {val['description']['moniker']}")
    print(f"Status: {val['status']}")
    tokens = int(val['tokens']) / 1e18
    print(f"Total tokens: {tokens:.2f} RAI")
    print(f"Commission: {float(val['commission']['commission_rates']['rate'])*100:.1f}%")
    delegations = d.get('delegation_responses', [])
    print(f"Delegators: {len(delegations)}")
    print("--- Delegators ---")
    for r in delegations:
        addr = r["delegation"]["delegator_address"]
        shares = float(r["delegation"]["shares"]) / 1e18
        print(f"  {addr} -> {shares:.2f} RAI")
except Exception as e:
    print(f"Error: {e}")
PYEOF
