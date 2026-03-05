#!/usr/bin/env python3
"""Show all validators ranked."""
import json, os, subprocess, sys

def run(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() or r.stderr.strip()
    except:
        return ""

def main():
    valoper = os.environ.get("WALLET_VALOPER", "")
    rpc = os.environ.get("NODE_RPC", "tcp://localhost:26657")

    # Fetch all validators with pagination
    all_validators = []
    page_key = None
    for _ in range(10):  # max 10 pages
        cmd = f"republicd query staking validators --node {rpc} -o json --page-limit 200"
        if page_key:
            cmd += f' --page-key "{page_key}"'
        raw = run(cmd, timeout=30)
        if not raw:
            break
        try:
            data = json.loads(raw)
        except:
            print("ERROR: Invalid JSON response")
            sys.exit(1)
        all_validators.extend(data.get("validators", []))
        # Check for next page
        page_key = data.get("pagination", {}).get("next_key")
        if not page_key:
            break

    validators = all_validators
    bonded = [v for v in validators if v.get("status") == "BOND_STATUS_BONDED"]
    unbonded = len(validators) - len(bonded)
    bonded.sort(key=lambda v: int(v.get("tokens", 0)), reverse=True)

    print(f"Active (bonded) validators: {len(bonded)}  |  Unbonded/Jailed: {unbonded}")
    print(f"{'#':>3} {'Moniker':30s} {'Tokens':>15s} {'Jailed'}")
    print("-" * 60)

    for i, v in enumerate(bonded, 1):
        moniker = v.get("description", {}).get("moniker", "?")[:30]
        tokens = int(v.get("tokens", 0)) / 1e18
        jailed = "⚠️ JAILED" if v.get("jailed") else ""
        marker = " ← YOU" if v.get("operator_address") == valoper else ""
        print(f"{i:>3} {moniker:30s} {tokens:>15.2f} {jailed}{marker}")

if __name__ == "__main__":
    main()
