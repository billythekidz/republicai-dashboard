#!/usr/bin/env python3
"""Show systemd and docker services status."""
import os, subprocess, json

def run(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() or r.stderr.strip()
    except:
        return ""

def main():
    services_env = os.environ.get("NODE_SERVICES", "")
    if services_env:
        services = [s.strip() for s in services_env.split(",") if s.strip()]
    else:
        services = ["republicd", "republic-sidecar", "republic-autocompute",
                     "republic-http", "republic-dashboard", "cloudflared"]

    print("=== Systemd Services ===")
    for svc in services:
        status = run(f"systemctl is-active {svc}")
        print(f"  {svc:30s} {status}")

    # Docker
    print()
    print("=== Docker Containers ===")
    docker_out = run("docker ps --format '{{.Names}}\\t{{.Status}}\\t{{.Image}}'")
    if docker_out:
        for line in docker_out.split("\n"):
            print(f"  {line}")
    else:
        print("  No running containers (or docker not available)")

if __name__ == "__main__":
    main()
