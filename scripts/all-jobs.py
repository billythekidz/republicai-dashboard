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

    # Query all jobs with pagination
    all_jobs = []
    page_key = None
    for page in range(20):  # max 20 pages
        cmd = f"republicd query computevalidation list-job --node {rpc} -o json --limit 500"
        if page_key:
            cmd += f' --page-key "{page_key}"'
        raw, rc = run(cmd, timeout=60)
        if not raw:
            if page == 0:
                print(f"ERROR: Could not query jobs (exit={rc}, empty output)")
                sys.exit(1)
            break

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            if page == 0:
                print(f"ERROR: Invalid JSON: {e}")
                print(f"First 200 chars: {raw[:200]}")
                sys.exit(1)
            break

        jobs_page = data.get("jobs", data.get("job", []))
        if not isinstance(jobs_page, list):
            jobs_page = [jobs_page] if jobs_page else []
        all_jobs.extend(jobs_page)

        # Check for next page
        pagination = data.get("pagination", {})
        page_key = pagination.get("next_key")
        if not page_key:
            break

    jobs = all_jobs

    # Count by status
    status_counts = {}
    for j in jobs:
        s = j.get("status", "unknown")
        status_counts[s] = status_counts.get(s, 0) + 1

    print(f"Total jobs on chain: {len(jobs)}")
    for s, c in sorted(status_counts.items()):
        print(f"  {s}: {c}")
    print()

    if not jobs:
        print("  No jobs found on chain.")
        return

    # Print header
    print(f"{'ID':>5s}  {'Status':<20s}  {'Creator':<45s}  {'Target Validator'}")
    print("-" * 130)

    MAX_LINES = 10000
    sorted_jobs = sorted(jobs, key=lambda x: int(x.get("id", 0)), reverse=True)
    lines_printed = 0
    jobs_shown = 0

    for j in sorted_jobs:
        jid = j.get("id", "?")
        status = j.get("status", "?")
        creator = j.get("creator", "")
        target = j.get("target_validator", "")
        rhash = j.get("result_hash", "")

        is_mine = (target == valoper or creator == wallet) if (valoper or wallet) else False
        marker = " ★" if is_mine else ""

        print(f"{jid:>5s}  {status:<20s}  {creator:<45s}  {target}{marker}")
        lines_printed += 1
        if rhash:
            print(f"       hash: {rhash}")
            lines_printed += 1
        jobs_shown += 1

        if lines_printed >= MAX_LINES:
            remaining = len(jobs) - jobs_shown
            if remaining > 0:
                print()
                print(f"  ... {remaining} older jobs truncated (reached {MAX_LINES} line limit)")
            break

if __name__ == "__main__":
    main()
