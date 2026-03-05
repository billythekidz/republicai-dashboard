#!/bin/bash
# list-jobs.sh — List compute jobs for this validator
HOME_DIR="${NODE_HOME:-/root/.republicd}"
RPC="${NODE_RPC:-tcp://localhost:26657}"
WNAME="${WALLET_NAME:-my-wallet}"
KB="${KEYRING_BACKEND:-test}"

VALOPER=$(republicd keys show "$WNAME" --bech val -a --home "$HOME_DIR" --keyring-backend "$KB" 2>/dev/null)
WALLET=$(republicd keys show "$WNAME" -a --home "$HOME_DIR" --keyring-backend "$KB" 2>/dev/null)

echo "Wallet:  $WALLET"
echo "Valoper: $VALOPER"
echo ""

# Query jobs — handle errors gracefully
JOBS_JSON=$(republicd query computevalidation list-job --node "$RPC" -o json 2>/dev/null)
if [ -z "$JOBS_JSON" ]; then
    echo "ERROR: Could not query jobs (empty response)"
    echo "Try: republicd query computevalidation list-job --node $RPC -o json"
    exit 1
fi

# Validate JSON before passing to Python
echo "$JOBS_JSON" | python3 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "ERROR: Invalid JSON response from republicd"
    echo "$JOBS_JSON" | head -3
    exit 1
fi

echo "$JOBS_JSON" | python3 << 'PYEOF'
import json, sys, os

valoper = os.environ.get("WALLET_VALOPER", "")
wallet = os.environ.get("WALLET_ADDRESS", "")

try:
    d = json.load(sys.stdin)
except Exception as e:
    print(f"JSON parse error: {e}")
    sys.exit(1)

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
    for j in my:
        jid = j.get("id", "?")
        status = j.get("status", "?")
        rhash = j.get("result_hash", "")[:30]
        creator = j.get("creator", "")[:20]
        print(f"  Job #{jid:>4s} | {status:25s} | hash={rhash}")
PYEOF
