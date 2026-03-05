#!/usr/bin/env python3
"""List ALL compute jobs on chain with full details."""
import json, os, subprocess, sys

def run(cmd, timeout=30):
    """Run command, capture stdout+stderr combined."""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        output = r.stdout.strip() or r.stderr.strip()
        return output, r.returncode
    except subprocess.TimeoutExpired:
        return "", -1

def main():
    valoper = os.environ.get("WALLET_VALOPER", "")
    wallet = os.environ.get("WALLET_ADDRESS", "")
    rpc = os.environ.get("NODE_RPC", "tcp://localhost:26657")

    # Fetch ALL jobs in one query (huge limit, server returns what it has)
    cmd = f"republicd query computevalidation list-job --node {rpc} -o json --limit 1000000000 --reverse"
    raw, rc = run(cmd, timeout=60)
    if not raw:
        print(f"ERROR: Could not query jobs (exit={rc}, empty output)")
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

    # Count by status
    status_counts = {}
    for j in jobs:
        s = j.get("status", "unknown")
        status_counts[s] = status_counts.get(s, 0) + 1

    # Total = latest job ID (first in --reverse result)
    total_on_chain = jobs[0].get("id", "?") if jobs else "0"
    print(f"Total jobs on chain: {total_on_chain}  |  Showing latest: {len(jobs)}")
    for s, c in sorted(status_counts.items()):
        print(f"  {s}: {c}")
    print()

    if not jobs:
        print("  No jobs found on chain.")
        return

    # Already sorted newest first by --reverse
    print(f"{'ID':>5s}  {'Status':<20s}  {'Creator':<45s}  {'Target Validator'}")
    print("-" * 130)

    for j in jobs:
        jid = j.get("id", "?")
        status = j.get("status", "?")
        creator = j.get("creator", "")
        target = j.get("target_validator", "")
        rhash = j.get("result_hash", "")

        is_mine = (target == valoper or creator == wallet) if (valoper or wallet) else False
        marker = " ★" if is_mine else ""

        print(f"{jid:>5s}  {status:<20s}  {creator:<45s}  {target}{marker}")
        if rhash:
            print(f"       hash: {rhash}")

if __name__ == "__main__":
    main()
