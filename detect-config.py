#!/usr/bin/env python3
"""
Auto-detect RepublicAI node configuration.
Discovers home directory automatically by scanning:
  1. Running republicd process (--home flag)
  2. Systemd service file (ExecStart --home)
  3. Common locations: /root/.republicd, /home/*/.republicd, etc.
  4. User-specified --home override

Then reads config.toml, app.toml, client.toml to build config.json.

Usage:
  python3 detect-config.py                         # full auto-detect
  python3 detect-config.py --home /root/.republicd  # explicit home
  python3 detect-config.py --output /path/config.json
"""
import json, re, os, sys, subprocess, argparse, glob, socket

DASHBOARD_PORT = 3847

# ─── Helpers ────────────────────────────────────────────────

def run(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except:
        return ""

def parse_toml_simple(filepath):
    """Parse a TOML file into a nested-key dict (section.key = value)."""
    result = {}
    section = ""
    if not os.path.isfile(filepath):
        return result
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            m = re.match(r'^\[(.+)\]$', line)
            if m:
                section = m.group(1) + "."
                continue
            m = re.match(r'^(\S+)\s*=\s*(.+)$', line)
            if m:
                key = section + m.group(1)
                val = m.group(2).strip().strip('"').strip("'")
                result[key] = val
    return result

def extract_port(addr, default=None):
    m = re.search(r':(\d+)$', str(addr))
    return int(m.group(1)) if m else default

def port_is_available(port):
    """Check if a port is free (not in use by any process)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            s.bind(('', port))
            return True
    except OSError:
        return False

def extract_host(addr, default="localhost"):
    m = re.match(r'(?:tcp://|http://|https://)?([^:]+)', str(addr))
    return m.group(1) if m else default


# ─── Home Directory Discovery ──────────────────────────────

def discover_home_dirs():
    """
    Find all possible republicd home directories, ordered by confidence.
    Returns list of (path, source) tuples.
    """
    candidates = []
    seen = set()

    def add(path, source):
        path = os.path.realpath(path)
        if path not in seen and os.path.isdir(path):
            seen.add(path)
            candidates.append((path, source))

    # 1) Running process: check --home flag from cmdline
    ps_output = run("ps aux | grep '[r]epublicd.*start'")
    for line in ps_output.split('\n'):
        if not line:
            continue
        m = re.search(r'--home\s+(\S+)', line)
        if m:
            add(m.group(1), "running process (--home)")
        else:
            # No --home flag means default home for the user running it
            parts = line.split()
            if parts:
                proc_user = parts[0]
                if proc_user == "root":
                    add("/root/.republicd", f"running process (user={proc_user})")
                else:
                    add(f"/home/{proc_user}/.republicd", f"running process (user={proc_user})")

    # 2) Systemd service file
    svc_files = glob.glob("/etc/systemd/system/republicd*.service") + \
                glob.glob("/lib/systemd/system/republicd*.service")
    for svc_file in svc_files:
        try:
            content = open(svc_file).read()
            m = re.search(r'--home\s+(\S+)', content)
            if m:
                add(m.group(1), f"systemd ({os.path.basename(svc_file)})")
            # Also check User= directive
            m_user = re.search(r'^User=(.+)$', content, re.MULTILINE)
            exec_user = m_user.group(1) if m_user else "root"
            if not m:  # no --home flag, infer from user
                if exec_user == "root":
                    add("/root/.republicd", f"systemd user={exec_user}")
                else:
                    add(f"/home/{exec_user}/.republicd", f"systemd user={exec_user}")
        except:
            pass

    # 3) Environment variable
    env_home = os.environ.get("REPUBLICD_HOME") or os.environ.get("DAEMON_HOME")
    if env_home:
        add(env_home, "environment variable")

    # 4) Common default locations
    add("/root/.republicd", "default (root)")
    
    # Scan /home/*/.republicd
    for homedir in glob.glob("/home/*/.republicd"):
        user = homedir.split('/')[2]
        add(homedir, f"default (/home/{user})")

    # 5) Non-standard locations people might use
    for alt in ["/opt/republicd", "/var/lib/republicd", "/data/.republicd"]:
        if os.path.isdir(alt):
            add(alt, "alternative location")

    return candidates


def validate_home(home_dir):
    """Check if a directory looks like a valid republicd home."""
    config_dir = os.path.join(home_dir, "config")
    if not os.path.isdir(config_dir):
        return False, "no config/ directory"
    
    required = ["config.toml"]
    optional = ["app.toml", "client.toml", "genesis.json"]
    
    has_required = all(os.path.isfile(os.path.join(config_dir, f)) for f in required)
    has_optional = sum(1 for f in optional if os.path.isfile(os.path.join(config_dir, f)))
    
    if not has_required:
        return False, "missing config.toml"
    
    return True, f"valid ({has_optional + 1} config files found)"


# ─── Wallet Discovery ──────────────────────────────────────

def discover_wallets(home_dir, keyring_backend):
    """Discover wallets from keyring directory and CLI."""
    wallets = []
    
    # Method 1: Read keyring directory directly
    keyring_dir = os.path.join(home_dir, f"keyring-{keyring_backend}")
    if os.path.isdir(keyring_dir):
        for f in os.listdir(keyring_dir):
            if f.endswith(".info"):
                name = f.replace(".info", "")
                wallets.append(name)
    
    # Method 2: CLI fallback
    if not wallets:
        out = run(f"republicd keys list --home {home_dir} --keyring-backend {keyring_backend} -o json 2>/dev/null")
        if out:
            try:
                for w in json.loads(out):
                    name = w.get("name", "")
                    if name and name not in wallets:
                        wallets.append(name)
            except:
                pass

    # Method 3: Check for common names via CLI
    if not wallets:
        for guess in ["my-wallet", "validator", "default", "wallet"]:
            addr = run(f"republicd keys show {guess} -a --home {home_dir} --keyring-backend {keyring_backend} 2>/dev/null")
            if addr:
                wallets.append(guess)
    
    return wallets


# ─── Main Detection ────────────────────────────────────────

def detect(home_dir):
    config_dir = os.path.join(home_dir, "config")
    
    # Parse configs
    config_toml = parse_toml_simple(os.path.join(config_dir, "config.toml"))
    app_toml = parse_toml_simple(os.path.join(config_dir, "app.toml"))
    client_toml = parse_toml_simple(os.path.join(config_dir, "client.toml"))
    
    # RPC
    rpc_addr = client_toml.get("node", config_toml.get("rpc.laddr", "tcp://localhost:26657"))
    rpc_port = extract_port(rpc_addr, 26657)
    rpc_host = extract_host(rpc_addr, "localhost")
    
    # P2P
    p2p_addr = config_toml.get("p2p.laddr", "tcp://0.0.0.0:26656")
    p2p_port = extract_port(p2p_addr, 26656)
    
    # API
    api_addr = app_toml.get("api.address", "tcp://localhost:1317")
    api_port = extract_port(api_addr, 1317)
    api_enabled = app_toml.get("api.enable", "true").lower() == "true"
    
    # gRPC
    grpc_addr = app_toml.get("grpc.address", "localhost:9090")
    grpc_port = extract_port(grpc_addr, 9090)
    grpc_enabled = app_toml.get("grpc.enable", "true").lower() == "true"
    
    # JSON-RPC
    jsonrpc_addr = app_toml.get("json-rpc.address", "127.0.0.1:8545")
    jsonrpc_port = extract_port(jsonrpc_addr, 8545)
    jsonrpc_enabled = app_toml.get("json-rpc.enable", "false").lower() == "true"
    
    # Moniker & Chain
    moniker = config_toml.get("moniker", "unknown")
    chain_id = client_toml.get("chain-id", "")
    if not chain_id:
        genesis_path = os.path.join(config_dir, "genesis.json")
        if os.path.isfile(genesis_path):
            try:
                with open(genesis_path) as f:
                    chain_id = json.load(f).get("chain_id", "")
            except:
                pass
    
    # Keyring
    keyring_backend = client_toml.get("keyring-backend", "test")
    
    # Wallets
    wallets = discover_wallets(home_dir, keyring_backend)
    default_wallet = wallets[0] if wallets else ""
    
    valoper = ""
    wallet_addr = ""
    if default_wallet:
        wallet_addr = run(f"republicd keys show {default_wallet} -a --home {home_dir} --keyring-backend {keyring_backend} 2>/dev/null")
        valoper = run(f"republicd keys show {default_wallet} --bech val -a --home {home_dir} --keyring-backend {keyring_backend} 2>/dev/null")
    
    # Systemd services
    services_raw = run("systemctl list-unit-files --type=service --no-pager 2>/dev/null")
    services = []
    for line in services_raw.split('\n'):
        if 'republic' in line.lower() or 'cloudflared' in line.lower():
            svc_name = line.split()[0].replace('.service', '')
            if svc_name not in services:
                services.append(svc_name)
    
    # Docker
    docker_available = run("docker --version 2>/dev/null") != ""
    inference_image = "republic-llm-inference:latest"
    if docker_available:
        imgs = run("docker images --format '{{.Repository}}:{{.Tag}}' | grep -i inference")
        if imgs:
            inference_image = imgs.split('\n')[0]
    
    return {
        "node": {
            "home": home_dir,
            "moniker": moniker,
            "chain_id": chain_id,
        },
        "ports": {
            "rpc": rpc_port,
            "rpc_host": rpc_host,
            "p2p": p2p_port,
            "api": api_port,
            "api_enabled": api_enabled,
            "grpc": grpc_port,
            "grpc_enabled": grpc_enabled,
            "jsonrpc": jsonrpc_port,
            "jsonrpc_enabled": jsonrpc_enabled,
        },
        "wallet": {
            "name": default_wallet,
            "address": wallet_addr,
            "valoper": valoper,
            "keyring_backend": keyring_backend,
            "available_wallets": wallets,
        },
        "services": services,
        "docker": {
            "available": docker_available,
            "inference_image": inference_image,
        },
        "endpoints": {
            "rpc": f"tcp://{rpc_host}:{rpc_port}",
            "rpc_http": f"http://{rpc_host}:{rpc_port}",
            "api": f"http://localhost:{api_port}" if api_enabled else None,
            "grpc": f"localhost:{grpc_port}" if grpc_enabled else None,
        }
    }


# ─── Entry Point ────────────────────────────────────────────

if __name__ == "__main__":
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    DEFAULT_OUTPUT = os.path.join(SCRIPT_DIR, "config.json")
    
    parser = argparse.ArgumentParser(description="Auto-detect RepublicAI node config")
    parser.add_argument("--home", default=None, help="Explicit node home dir (skip auto-discovery)")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Output config.json path")
    parser.add_argument("--scan-only", action="store_true", help="Only scan for home dirs, don't generate config")
    args = parser.parse_args()

    # Step 1: Discover home directory
    if args.home:
        home = args.home
        print(f"[override] Using --home: {home}")
    else:
        print("Scanning for republicd home directories...")
        candidates = discover_home_dirs()
        
        if not candidates:
            print("ERROR: No republicd home directory found!")
            print("Try: python3 detect-config.py --home /path/to/.republicd")
            sys.exit(1)
        
        print(f"Found {len(candidates)} candidate(s):")
        valid_home = None
        for path, source in candidates:
            ok, msg = validate_home(path)
            marker = "✅" if ok else "❌"
            print(f"  {marker} {path}  [{source}] — {msg}")
            if ok and not valid_home:
                valid_home = path
        
        if not valid_home:
            print("\nERROR: No valid republicd home found!")
            sys.exit(1)
        
        home = valid_home
        print(f"\n→ Selected: {home}")
    
    if args.scan_only:
        sys.exit(0)

    # Step 2: Validate
    ok, msg = validate_home(home)
    if not ok:
        print(f"ERROR: {home} is not valid — {msg}")
        sys.exit(1)

    # Step 3: Detect
    print(f"\nDetecting configuration from {home}...")
    config = detect(home)

    # Step 3b: Port conflict detection
    print(f"\nChecking port conflicts...")
    port_fields = [
        ('rpc', 'ports.rpc'),
        ('p2p', 'ports.p2p'),
        ('api', 'ports.api'),
        ('grpc', 'ports.grpc'),
        ('jsonrpc', 'ports.jsonrpc'),
    ]
    conflicts_found = False
    for label, key_path in port_fields:
        port = config['ports'][label]
        issues = []
        if port == DASHBOARD_PORT:
            issues.append(f"conflicts with dashboard port {DASHBOARD_PORT}")
        if not port_is_available(port):
            issues.append("port already in use")
        if issues:
            conflicts_found = True
            original = port
            # Find next available port
            candidate = port + 1
            while candidate < port + 100:
                if candidate != DASHBOARD_PORT and port_is_available(candidate):
                    break
                candidate += 1
            print(f"  ⚠️  {label} port {original} — {', '.join(issues)}")
            print(f"       → suggested free port: {candidate}")
            config['ports'][label] = candidate
            # Update endpoints that use this port
            if label == 'rpc':
                h = config['ports']['rpc_host']
                config['endpoints']['rpc'] = f'tcp://{h}:{candidate}'
                config['endpoints']['rpc_http'] = f'http://{h}:{candidate}'
            elif label == 'api' and config['ports']['api_enabled']:
                config['endpoints']['api'] = f'http://localhost:{candidate}'
            elif label == 'grpc' and config['ports']['grpc_enabled']:
                config['endpoints']['grpc'] = f'localhost:{candidate}'
    if not conflicts_found:
        print("  ✅ No port conflicts detected")
    
    print(f"\n{'='*50}")
    print(f"  Node:     {config['node']['moniker']} ({config['node']['chain_id']})")
    print(f"  Home:     {config['node']['home']}")
    print(f"  RPC:      {config['endpoints']['rpc']} (port {config['ports']['rpc']})")
    print(f"  P2P:      port {config['ports']['p2p']}")
    print(f"  API:      {config['endpoints']['api']} (port {config['ports']['api']})")
    print(f"  gRPC:     {config['endpoints']['grpc']} (port {config['ports']['grpc']})")
    print(f"  Wallet:   {config['wallet']['name']} ({config['wallet']['address'][:20]}...)" if config['wallet']['address'] else "  Wallet:   (none detected)")
    print(f"  Wallets:  {config['wallet']['available_wallets']}")
    print(f"  Valoper:  {config['wallet']['valoper'][:20]}..." if config['wallet']['valoper'] else "  Valoper:  (none)")
    print(f"  Services: {', '.join(config['services'])}")
    print(f"  Docker:   {'yes' if config['docker']['available'] else 'no'} ({config['docker']['inference_image']})")
    print(f"{'='*50}")
    
    # Step 4: Write
    os.makedirs(os.path.dirname(args.output) if os.path.dirname(args.output) else ".", exist_ok=True)
    with open(args.output, 'w') as f:
        json.dump(config, f, indent=2)
    print(f"\n✅ Config written to {args.output}")
