#!/usr/bin/env python3
"""Show connected peers."""
import json, os, subprocess, urllib.request

def http_get(url, timeout=5):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read())
    except:
        return {}

def main():
    rpc_http = os.environ.get("NODE_RPC_HTTP", "http://localhost:26657")

    net = http_get(f"{rpc_http}/net_info")
    peers = net.get("result", {}).get("peers", [])

    print(f"Connected peers: {len(peers)}")
    print()

    for p in peers:
        ni = p.get("node_info", {})
        ri = p.get("remote_ip", "?")
        moniker = ni.get("moniker", "?")
        node_id = ni.get("id", "?")[:16]
        listen = ni.get("listen_addr", "?")
        print(f"  {moniker:25s} | {ri:15s} | {node_id}... | {listen}")

if __name__ == "__main__":
    main()
