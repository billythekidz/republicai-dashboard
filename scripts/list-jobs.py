#!/usr/bin/env python3
"""List compute jobs for this validator."""
import json, os, subprocess, sys

def run(cmd, timeout=30):
    """Run command, capture stdout+stderr combined."""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        # republicd outputs JSON to stderr sometimes
        output = r.stdout.strip() or r.stderr.strip()
        return output, r.returncode
    except subprocess.TimeoutExpired:
        return "", -1

def main():
    valoper = os.environ.get("WALLET_VALOPER", "")
    wallet = os.environ.get("WALLET_ADDRESS", "")
    rpc = os.environ.get("NODE_RPC", "tcp://localhost:26657")
    home = os.environ.get("NODE_HOME", "/root/.republicd")
    wname = os.environ.get("WALLET_NAME", "my-wallet")
    kb = os.environ.get("KEYRING_BACKEND", "test")

    # Fallback: get wallet from CLI if env empty
    if not valoper:
        valoper, _ = run(f"republicd keys show {wname} --bech val -a --home {home} --keyring-backend {kb}")
    if not wallet:
        wallet, _ = run(f"republicd keys show {wname} -a --home {home} --keyring-backend {kb}")

    print(f"Wallet:  {wallet}")
    print(f"Valoper: {valoper}")
    print()

    # Query jobs
    raw, rc = run(f"republicd query computevalidation list-job --node {rpc} -o json")
    if not raw:
        print(f"ERROR: Could not query jobs (exit={rc}, empty output)")
        print(f"Try: republicd query computevalidation list-job --node {rpc} -o json")
        sys.exit(1)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON: {e}")
        print(f"First 200 chars: {raw[:200]}")
        sys.exit(1)

    jobs = data.get("jobs", data.get("job", []))
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

if __name__ == "__main__":
    main()
