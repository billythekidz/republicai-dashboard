#!/usr/bin/env python3
"""Show compute job history from saved logs."""
import os, glob

LOGS_DIR = "/var/lib/republic/logs"

def main():
    if not os.path.isdir(LOGS_DIR):
        print("No job logs found yet.")
        print(f"  Logs will appear in {LOGS_DIR}/ after running Submit+Compute or Compute Job.")
        return

    log_files = sorted(glob.glob(os.path.join(LOGS_DIR, "job-*.log")), reverse=True)

    if not log_files:
        print("No job logs found yet.")
        print(f"  Logs will appear in {LOGS_DIR}/ after running Submit+Compute or Compute Job.")
        return

    print(f"=== Job History ({len(log_files)} jobs) ===")
    print()

    for lf in log_files:
        try:
            with open(lf, "r") as f:
                content = f.read().strip()
            print(content)
            print("-" * 60)
        except Exception as e:
            print(f"  Error reading {lf}: {e}")

if __name__ == "__main__":
    main()
