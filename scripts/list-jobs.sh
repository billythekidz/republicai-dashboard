#!/bin/bash
# list-jobs.sh — List compute jobs for this validator
HOME_DIR="${NODE_HOME:-/root/.republicd}"
RPC="${NODE_RPC:-tcp://localhost:26657}"
WNAME="${WALLET_NAME:-my-wallet}"
KB="${KEYRING_BACKEND:-test}"

VALOPER=$(republicd keys show "$WNAME" --bech val -a --home "$HOME_DIR" --keyring-backend "$KB" 2>/dev/null)
WALLET=$(republicd keys show "$WNAME" -a --home "$HOME_DIR" --keyring-backend "$KB" 2>/dev/null)
republicd query computevalidation list-job --node "$RPC" -o json 2>/dev/null > /tmp/jobs.json

python3 << PYEOF
import json, os
valoper = "$VALOPER"
wallet = "$WALLET"
d = json.load(open("/tmp/jobs.json"))
jobs = d.get("jobs", d.get("job", []))
my = [j for j in jobs if j.get("target_validator")==valoper or j.get("creator")==wallet]
print(f"Total jobs on chain: {len(jobs)}, My jobs: {len(my)}")
print()
for j in my:
    print(f"  Job #{j['id']:>4s} | {j['status']:20s} | hash={j.get('result_hash','')[:30]}")
PYEOF
