#!/bin/bash
# peers.sh — Connected peers
RPC_HTTP="${NODE_RPC_HTTP:-http://localhost:26657}"
curl -s "$RPC_HTTP/net_info" > /tmp/netinfo.json
python3 << 'PYEOF'
import json
try:
    d = json.load(open("/tmp/netinfo.json"))
    peers = d.get("result", {}).get("peers", [])
    print(f"Connected peers: {len(peers)}")
    print()
    for p in peers:
        remote = p.get("remote_ip", "?")
        node_info = p.get("node_info", {})
        moniker = node_info.get("moniker", "?")
        network = node_info.get("network", "?")
        print(f"  {moniker:20s} | {remote:15s} | {network}")
except Exception as e:
    print(f"Error: {e}")
PYEOF
