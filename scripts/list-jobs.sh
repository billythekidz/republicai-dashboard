#!/bin/bash
# list-jobs.sh — List jobs targeting our validator
VALOPER=$(republicd keys show my-wallet --bech val -a --home /root/.republicd --keyring-backend test 2>/dev/null)
WALLET=$(republicd keys show my-wallet -a --home /root/.republicd --keyring-backend test 2>/dev/null)
republicd query computevalidation list-job --node tcp://localhost:26657 -o json 2>/dev/null > /tmp/jobs.json

python3 << 'PYEOF'
import json, os
valoper = os.popen("republicd keys show my-wallet --bech val -a --home /root/.republicd --keyring-backend test 2>/dev/null").read().strip()
wallet = os.popen("republicd keys show my-wallet -a --home /root/.republicd --keyring-backend test 2>/dev/null").read().strip()
d = json.load(open("/tmp/jobs.json"))
jobs = d.get("jobs", d.get("job", []))
my = [j for j in jobs if j.get("target_validator")==valoper or j.get("creator")==wallet]
print(f"Total jobs on chain: {len(jobs)}, My jobs: {len(my)}")
print()
for j in my:
    print(f"  Job #{j['id']:>4s} | {j['status']:20s} | hash={j.get('result_hash','')[:30]}")
PYEOF
