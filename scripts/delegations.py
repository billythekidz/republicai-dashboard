#!/usr/bin/env python3
"""Show staking delegations for this validator."""
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
    home = os.environ.get("NODE_HOME", "/root/.republicd")
    wname = os.environ.get("WALLET_NAME", "my-wallet")
    kb = os.environ.get("KEYRING_BACKEND", "test")

    if not valoper:
        valoper = run(f"republicd keys show {wname} --bech val -a --home {home} --keyring-backend {kb}")

    print(f"Valoper: {valoper}")
    print()

    # Validator info
    val_raw = run(f"republicd query staking validator {valoper} --node {rpc} -o json")
    if val_raw:
        try:
            v = json.loads(val_raw)
            val = v.get("validator", v)
            print(f"Moniker: {val['description']['moniker']}")
            print(f"Status: {val['status']}")
            tokens = int(val['tokens']) / 1e18
            print(f"Total tokens: {tokens:.2f} RAI")
            rate = float(val['commission']['commission_rates']['rate']) * 100
            print(f"Commission: {rate:.1f}%")
        except Exception as e:
            print(f"Error parsing validator: {e}")

    # Delegations
    del_raw = run(f"republicd query staking delegations-to {valoper} --node {rpc} -o json", timeout=30)
    if del_raw:
        try:
            d = json.loads(del_raw)
            delegations = d.get('delegation_responses', [])
            print(f"Delegators: {len(delegations)}")
            print("--- Delegators ---")
            for r in delegations:
                addr = r["delegation"]["delegator_address"]
                shares = float(r["delegation"]["shares"]) / 1e18
                print(f"  {addr} -> {shares:.2f} RAI")
        except Exception as e:
            print(f"Error parsing delegations: {e}")
    else:
        print("Could not query delegations")

if __name__ == "__main__":
    main()
