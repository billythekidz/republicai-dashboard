#!/bin/bash
# validators.sh — List all validators sorted by stake
RPC="${NODE_RPC:-tcp://localhost:26657}"
republicd query staking validators --node "$RPC" -o json --limit 200 > /tmp/validators.json 2>/dev/null
python3 << 'PYEOF'
import json, os
d = json.load(open("/tmp/validators.json"))
vals = d.get("validators", [])
vals.sort(key=lambda v: int(v.get("tokens","0")), reverse=True)
bonded = [v for v in vals if v.get("status")=="BOND_STATUS_BONDED"]
unbonded = [v for v in vals if v.get("status")!="BOND_STATUS_BONDED"]
print(f"Total validators: {len(vals)}")
print(f"Bonded: {len(bonded)}, Unbonded: {len(unbonded)}")
print()
my_valoper = os.environ.get("WALLET_VALOPER", "")
for i, v in enumerate(vals[:115]):
    tokens = int(v.get("tokens","0"))/1e18
    moniker = v.get("description",{}).get("moniker","?")
    status = "B" if v.get("status")=="BOND_STATUS_BONDED" else "U"
    marker = " <-- YOU" if my_valoper and my_valoper == v.get("operator_address","") else ""
    print(f"  #{i+1:3d} [{status}] {tokens:12.2f} RAI  {moniker}{marker}")
if len(vals) >= 100:
    cutoff = int(vals[99].get("tokens","0"))/1e18
    print(f"\nTop 100 cutoff: {cutoff:.2f} RAI")
PYEOF
