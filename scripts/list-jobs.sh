#!/bin/bash
# list-jobs.sh — List compute jobs for this validator
VALOPER="${WALLET_VALOPER}"
WALLET="${WALLET_ADDRESS}"
RPC="${NODE_RPC:-tcp://localhost:26657}"

# Fallback: try CLI if env vars empty
if [ -z "$VALOPER" ]; then
    HOME_DIR="${NODE_HOME:-/root/.republicd}"
    WNAME="${WALLET_NAME:-my-wallet}"
    KB="${KEYRING_BACKEND:-test}"
    VALOPER=$(republicd keys show "$WNAME" --bech val -a --home "$HOME_DIR" --keyring-backend "$KB" 2>/dev/null)
    WALLET=$(republicd keys show "$WNAME" -a --home "$HOME_DIR" --keyring-backend "$KB" 2>/dev/null)
fi

echo "Wallet:  $WALLET"
echo "Valoper: $VALOPER"
echo ""

# Query jobs — republicd may output to stderr, capture both
republicd query computevalidation list-job --node "$RPC" -o json > /tmp/dashboard_jobs.json 2>&1
RC=$?

if [ $RC -ne 0 ] || [ ! -s /tmp/dashboard_jobs.json ]; then
    echo "ERROR: Could not query jobs (exit=$RC)"
    echo "Try: republicd query computevalidation list-job --node $RPC -o json"
    exit 1
fi

WALLET_VALOPER="$VALOPER" WALLET_ADDRESS="$WALLET" python3 << 'PYEOF'
import json, os

valoper = os.environ.get("WALLET_VALOPER", "")
wallet = os.environ.get("WALLET_ADDRESS", "")

try:
    d = json.load(open("/tmp/dashboard_jobs.json"))
except Exception as e:
    print(f"JSON parse error: {e}")
    exit(1)

jobs = d.get("jobs", d.get("job", []))
if not isinstance(jobs, list):
    jobs = [jobs] if jobs else []

my = [j for j in jobs if j.get("target_validator") == valoper or j.get("creator") == wallet]

print(f"Total jobs on chain: {len(jobs)}")
print(f"My jobs (target/creator): {len(my)}")
print()

if not my:
    print("  No jobs found for this validator.")
else:
    for j in sorted(my, key=lambda x: int(x.get("id", 0)), reverse=True):
        jid = j.get("id", "?")
        status = j.get("status", "?")
        rhash = j.get("result_hash", "")[:30]
        print(f"  Job #{jid:>4s} | {status:25s} | hash={rhash}")
PYEOF
