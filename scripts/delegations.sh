#!/bin/bash
# delegations.sh
VALOPER=$(republicd keys show my-wallet --bech val -a --home /root/.republicd --keyring-backend test 2>/dev/null)
republicd query staking validator $VALOPER --node tcp://localhost:26657 -o json > /tmp/val_info.json 2>/dev/null
republicd query staking delegations-to $VALOPER --node tcp://localhost:26657 -o json > /tmp/delegations.json 2>/dev/null
python3 << 'PYEOF'
import json
v = json.load(open("/tmp/val_info.json"))
d = json.load(open("/tmp/delegations.json"))
print(f"Moniker: {v['description']['moniker']}")
print(f"Status: {v['status']}")
tokens = int(v['tokens']) / 1e18
print(f"Total tokens: {tokens:.2f} RAI")
print(f"Commission: {float(v['commission']['commission_rates']['rate'])*100:.1f}%")
print(f"Delegators: {len(d['delegation_responses'])}")
print("--- Delegators ---")
for r in d["delegation_responses"]:
    addr = r["delegation"]["delegator_address"]
    shares = float(r["delegation"]["shares"]) / 1e18
    print(f"  {addr} -> {shares:.2f} RAI")
PYEOF
