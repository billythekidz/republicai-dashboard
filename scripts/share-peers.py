#!/usr/bin/env python3
"""Generate shareable persistent_peers command for other validators."""
import json, os, urllib.request

def http_get(url, timeout=5):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read())
    except:
        return {}

def main():
    rpc_http = os.environ.get("NODE_RPC_HTTP", "http://localhost:26657")

    # Get node's own ID
    status = http_get(f"{rpc_http}/status")
    my_id = status.get("result", {}).get("node_info", {}).get("id", "???")
    my_listen = status.get("result", {}).get("node_info", {}).get("listen_addr", "")

    # Get connected peers
    net = http_get(f"{rpc_http}/net_info")
    peers = net.get("result", {}).get("peers", [])

    if not peers:
        print("No connected peers found!")
        return

    # Build persistent_peers string: node_id@ip:port
    peer_strings = []
    for p in peers:
        ni = p.get("node_info", {})
        node_id = ni.get("id", "")
        remote_ip = p.get("remote_ip", "")
        # Extract port from listen_addr (format: "tcp://0.0.0.0:26656" or similar)
        listen = ni.get("listen_addr", "")
        port = "26656"
        if ":" in listen:
            port = listen.rsplit(":", 1)[-1]
        if node_id and remote_ip:
            peer_strings.append(f"{node_id}@{remote_ip}:{port}")

    peers_csv = ",".join(peer_strings)

    print(f"📡 Your node ID: {my_id}")
    print(f"📊 Connected peers: {len(peer_strings)}")
    print()
    print("=" * 70)
    print("🔗 SHARE THIS — Others can ADD these peers (merge + dedup):")
    print("=" * 70)
    print()
    print("# Copy-paste this into another validator's terminal:")
    print()
    print(f'NEW_PEERS="{peers_csv}"')
    print('CFG="$HOME/.republicd/config/config.toml"')
    print('OLD=$(grep "^persistent_peers " "$CFG" | sed \'s/persistent_peers *= *"\\(.*\\)"/\\1/\')')
    print('MERGED=$(echo "$OLD,$NEW_PEERS" | tr "," "\\n" | awk -F@ \'!seen[$1]++\' | paste -sd,)')
    print('sed -i.bak "s/^persistent_peers *=.*/persistent_peers = \\"$MERGED\\"/" "$CFG"')
    print('systemctl restart republicd')
    print(f'echo "Done! Merged peers into config."')
    print()
    print("=" * 70)
    print()
    print("# Raw peer list (for manual use):")
    print()
    print(peers_csv)

if __name__ == "__main__":
    main()
