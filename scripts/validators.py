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

    raw = run(f"republicd query staking validators --node {rpc} -o json", timeout=30)
    if not raw:
        print("ERROR: Could not query validators")
        sys.exit(1)

    try:
        data = json.loads(raw)
    except:
        print("ERROR: Invalid JSON response")
        sys.exit(1)

    validators = data.get("validators", [])
    validators.sort(key=lambda v: int(v.get("tokens", 0)), reverse=True)

    print(f"Total validators: {len(validators)}")
    print(f"{'#':>3} {'Moniker':30s} {'Tokens':>15s} {'Status':25s} {'Jailed'}")
    print("-" * 85)

    for i, v in enumerate(validators, 1):
        moniker = v.get("description", {}).get("moniker", "?")[:30]
        tokens = int(v.get("tokens", 0)) / 1e18
        status = v.get("status", "?")
        jailed = "⚠️ JAILED" if v.get("jailed") else ""
        marker = " ← YOU" if v.get("operator_address") == valoper else ""
        print(f"{i:>3} {moniker:30s} {tokens:>15.2f} {status:25s} {jailed}{marker}")

if __name__ == "__main__":
    main()
