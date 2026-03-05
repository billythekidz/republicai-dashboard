#!/usr/bin/env python3
"""Gather comprehensive verification and node info."""
import json, os, subprocess, sys, urllib.request

def run(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return (r.stdout.strip() or r.stderr.strip()), r.returncode
    except subprocess.TimeoutExpired:
        return "", -1

def http_get(url, timeout=5):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read())
    except:
        return {}

def main():
    valoper = os.environ.get("WALLET_VALOPER", "")
    wallet = os.environ.get("WALLET_ADDRESS", "")
    rpc = os.environ.get("NODE_RPC", "tcp://localhost:26657")
    rpc_http = os.environ.get("NODE_RPC_HTTP", "http://localhost:26657")
    home = os.environ.get("NODE_HOME", "/root/.republicd")
    wname = os.environ.get("WALLET_NAME", "my-wallet")
    kb = os.environ.get("KEYRING_BACKEND", "test")

    # Wallet info
    if not valoper:
        valoper, _ = run(f"republicd keys show {wname} --bech val -a --home {home} --keyring-backend {kb}")
    if not wallet:
        wallet, _ = run(f"republicd keys show {wname} -a --home {home} --keyring-backend {kb}")

    print("=" * 60)
    print("📋 VERIFICATION INFO")
    print("=" * 60)

    # Wallet
    print()
    print("=== Wallet ===")
    print(f"  Name:     {wname}")
    print(f"  Address:  {wallet}")
    print(f"  Valoper:  {valoper}")

    # Node status via RPC
    print()
    print("=== Node Status ===")
    status = http_get(f"{rpc_http}/status")
    ni = status.get("result", {}).get("node_info", {})
    si = status.get("result", {}).get("sync_info", {})
    if ni:
        print(f"  Moniker:       {ni.get('moniker', '?')}")
        print(f"  Node ID:       {ni.get('id', '?')}")
        print(f"  Network:       {ni.get('network', '?')}")
        print(f"  Version:       {ni.get('version', '?')}")
        print(f"  Listen Addr:   {ni.get('listen_addr', '?')}")
    if si:
        print(f"  Latest Block:  {si.get('latest_block_height', '?')}")
        print(f"  Block Time:    {si.get('latest_block_time', '?')}")
        print(f"  Catching Up:   {si.get('catching_up', '?')}")
    if not ni:
        print("  ⚠️ Could not reach RPC")

    # Validator info
    print()
    print("=== Validator ===")
    if valoper:
        val_raw, _ = run(f"republicd query staking validator {valoper} --node {rpc} -o json")
        try:
            val = json.loads(val_raw)
            desc = val.get("description", {})
            print(f"  Moniker:     {desc.get('moniker', '?')}")
            print(f"  Status:      {val.get('status', '?')}")
            tokens = val.get("tokens", "0")
            tokens_f = int(tokens) / 1e18 if tokens.isdigit() else tokens
            print(f"  Tokens:      {tokens_f:,.2f}" if isinstance(tokens_f, float) else f"  Tokens:      {tokens}")
            print(f"  Commission:  {val.get('commission', {}).get('commission_rates', {}).get('rate', '?')}")
            print(f"  Jailed:      {val.get('jailed', '?')}")
            print(f"  Website:     {desc.get('website', '-')}")
            print(f"  Details:     {desc.get('details', '-')}")
        except:
            print(f"  Could not parse validator info")
    else:
        print("  ⚠️ No WALLET_VALOPER set")

    # republicd version
    print()
    print("=== Software ===")
    ver, _ = run("republicd version --long 2>&1")
    if ver:
        for line in ver.split("\n")[:6]:
            print(f"  {line}")

    # GPU
    print()
    print("=== GPU ===")
    gpu, rc = run("nvidia-smi --query-gpu=name,memory.total,memory.used,driver_version,temperature.gpu --format=csv,noheader")
    if rc == 0 and gpu:
        for line in gpu.split("\n"):
            print(f"  {line}")
    else:
        print("  No NVIDIA GPU found (nvidia-smi not available)")

    # Docker
    print()
    print("=== Docker ===")
    dver, _ = run("docker --version")
    print(f"  {dver}" if dver else "  Docker not installed")
    imgs, _ = run('docker images --format "{{.Repository}}:{{.Tag}}  ({{.Size}})" 2>/dev/null')
    if imgs:
        for line in imgs.split("\n")[:10]:
            print(f"  {line}")

    # Services
    print()
    print("=== Services ===")
    for svc in ["republicd", "republic-sidecar", "republic-autocompute", "republic-dashboard"]:
        st, _ = run(f"systemctl is-active {svc}")
        print(f"  {svc:<35s} {st or 'inactive'}")

    # Peers
    print()
    print("=== Network ===")
    net = http_get(f"{rpc_http}/net_info")
    peers = net.get("result", {}).get("peers", [])
    print(f"  Connected peers: {len(peers)}")
    listening = net.get("result", {}).get("listening", "?")
    print(f"  Listening:       {listening}")

    print()
    print("=" * 60)

if __name__ == "__main__":
    main()
