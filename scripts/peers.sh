#!/bin/bash
# peers.sh
curl -s http://localhost:26657/net_info > /tmp/netinfo.json
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
        listen = node_info.get("listen_addr", "?")
        network = node_info.get("network", "?")
        print(f"  {moniker:20s} | {remote:15s} | {network}")
except Exception as e:
    print(f"Error: {e}")
PYEOF
