#!/usr/bin/env python3
"""
RepublicAI Full Auto Compute — runs every 5 minutes.
Pipeline: submit job → get job ID → docker inference → submit result → repeat

Usage:
    python3 full-auto-compute.py                  # uses config.json or defaults
    python3 full-auto-compute.py --interval 300   # custom interval (seconds)
    python3 full-auto-compute.py --dry-run        # print what would run, don't execute
"""
import json, os, subprocess, sys, time, hashlib, argparse, signal
from datetime import datetime
from pathlib import Path

# ── Defaults (overridden by config.json or env vars) ──
DEFAULTS = {
    "NODE_HOME": "/root/.republicd",
    "NODE_RPC": "tcp://localhost:26657",
    "CHAIN_ID": "raitestnet_77701-1",
    "WALLET_NAME": "my-wallet",
    "WALLET_ADDRESS": "",
    "WALLET_VALOPER": "",
    "KEYRING_BACKEND": "test",
    "RESULT_BASE_URL": "https://republicai.devn.cloud",
    "JOBS_DIR": "/var/lib/republic/jobs",
    "DOCKER_IMAGE": "republic-llm-inference:latest",
    "VERIFICATION_IMAGE": "example-verification:latest",
    "JOB_FEE": "1000000000000000arai",   # 0.001 RAI
    "GAS_PRICES": "1000000000arai",
    "INTERVAL": 300,  # 5 minutes
    "DOCKER_TIMEOUT": 300,
    "TX_WAIT": 15,
}

# ── Helpers ──
def log(msg, level="INFO"):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [{level}] {msg}", flush=True)

def run(cmd, timeout=30, input_str=None):
    """Run a shell command, return (stdout, stderr, returncode)."""
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, input=input_str
        )
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except subprocess.TimeoutExpired:
        return "", "TIMEOUT", -1
    except Exception as e:
        return "", str(e), -1

def run_json(cmd, timeout=30):
    """Run command and parse JSON output."""
    stdout, stderr, rc = run(cmd, timeout=timeout)
    if rc != 0 or not stdout:
        return None, stderr or f"exit={rc}"
    try:
        return json.loads(stdout), None
    except json.JSONDecodeError as e:
        return None, f"JSON parse error: {e}"

def sha256_file(filepath):
    """Compute SHA256 hash of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

# ── Load config ──
def load_config():
    """Load from config.json (dashboard), then overlay env vars."""
    cfg = dict(DEFAULTS)

    # Try dashboard config.json
    for config_path in [
        Path(__file__).parent.parent / "config.json",
        Path("/root/republicai-dashboard/config.json"),
        Path("/root/republicai-public-dashboard/config.json"),
    ]:
        if config_path.exists():
            try:
                with open(config_path) as f:
                    c = json.load(f)
                cfg["NODE_HOME"] = c.get("node", {}).get("home", cfg["NODE_HOME"])
                cfg["CHAIN_ID"] = c.get("node", {}).get("chain_id", cfg["CHAIN_ID"])
                cfg["NODE_RPC"] = c.get("endpoints", {}).get("rpc", cfg["NODE_RPC"])
                cfg["WALLET_NAME"] = c.get("wallet", {}).get("name", cfg["WALLET_NAME"])
                cfg["WALLET_ADDRESS"] = c.get("wallet", {}).get("address", cfg["WALLET_ADDRESS"])
                cfg["WALLET_VALOPER"] = c.get("wallet", {}).get("valoper", cfg["WALLET_VALOPER"])
                cfg["KEYRING_BACKEND"] = c.get("wallet", {}).get("keyring_backend", cfg["KEYRING_BACKEND"])
                cfg["DOCKER_IMAGE"] = c.get("docker", {}).get("inference_image", cfg["DOCKER_IMAGE"])
                log(f"Config loaded from {config_path}")
                break
            except Exception as e:
                log(f"Warning: failed to read {config_path}: {e}", "WARN")

    # Env var overrides
    for key in cfg:
        env_val = os.environ.get(key)
        if env_val:
            cfg[key] = env_val

    # Auto-detect wallet if missing
    home = cfg["NODE_HOME"]
    wname = cfg["WALLET_NAME"]
    kb = cfg["KEYRING_BACKEND"]

    if not cfg["WALLET_ADDRESS"]:
        out, _, rc = run(f"republicd keys show {wname} -a --home {home} --keyring-backend {kb}")
        if rc == 0 and out:
            cfg["WALLET_ADDRESS"] = out
            log(f"Auto-detected wallet: {out[:10]}...")

    if not cfg["WALLET_VALOPER"]:
        out, _, rc = run(f"republicd keys show {wname} --bech val -a --home {home} --keyring-backend {kb}")
        if rc == 0 and out:
            cfg["WALLET_VALOPER"] = out
            log(f"Auto-detected valoper: {out[:14]}...")

    return cfg

# ── Step 1: Submit Job ──
def submit_job(cfg):
    """Submit a new compute job to the chain. Returns TX hash or None."""
    log("📤 Submitting new job...")

    cmd = (
        f"republicd tx computevalidation submit-job "
        f"{cfg['WALLET_VALOPER']} "
        f"{cfg['DOCKER_IMAGE']} "
        f"{cfg['RESULT_BASE_URL']}/upload "
        f"{cfg['RESULT_BASE_URL']}/result "
        f"{cfg['VERIFICATION_IMAGE']} "
        f"{cfg['JOB_FEE']} "
        f"--from {cfg['WALLET_NAME']} "
        f"--home {cfg['NODE_HOME']} "
        f"--chain-id {cfg['CHAIN_ID']} "
        f"--gas auto "
        f"--gas-adjustment 1.5 "
        f"--gas-prices {cfg['GAS_PRICES']} "
        f"--node {cfg['NODE_RPC']} "
        f"--keyring-backend {cfg['KEYRING_BACKEND']} "
        f"-y"
    )

    stdout, stderr, rc = run(cmd, timeout=30)
    output = stdout + "\n" + stderr

    # Extract txhash
    for line in output.split("\n"):
        if "txhash:" in line.lower() or "txhash:" in line:
            parts = line.strip().split()
            for i, p in enumerate(parts):
                if p.lower().rstrip(":") == "txhash" and i + 1 < len(parts):
                    return parts[i + 1]
            # Also try: txhash: ABCDEF
            if ":" in line:
                return line.split(":", 1)[1].strip()

    log(f"❌ Failed to submit job (rc={rc}): {output[:200]}", "ERROR")
    return None

# ── Step 2: Get Job ID from TX ──
def get_job_id(cfg, txhash):
    """Query TX to extract job_id from events."""
    log(f"🔍 Waiting {cfg['TX_WAIT']}s for TX confirmation...")
    time.sleep(int(cfg["TX_WAIT"]))

    cmd = f"republicd query tx {txhash} --node {cfg['NODE_RPC']} -o json"
    data, err = run_json(cmd, timeout=30)

    if not data:
        log(f"❌ TX query failed: {err}", "ERROR")
        return None

    # Search events for job_submitted.job_id
    events = data.get("events", [])
    # Also try nested in logs
    if not events:
        for lentry in data.get("logs", []):
            events.extend(lentry.get("events", []))

    for event in events:
        if event.get("type") == "job_submitted":
            for attr in event.get("attributes", []):
                if attr.get("key") == "job_id":
                    return attr["value"]

    log(f"❌ job_id not found in TX events", "ERROR")
    return None

# ── Step 3: Run Docker Inference ──
def run_inference(cfg, job_id):
    """Run GPU inference via Docker. Returns result file path or None."""
    jobs_dir = cfg["JOBS_DIR"]
    job_dir = f"{jobs_dir}/{job_id}"
    result_file = f"{job_dir}/result.bin"

    os.makedirs(job_dir, exist_ok=True)

    log(f"⚙️  Running inference for job #{job_id}...")

    # Check for custom inference.py
    inference_mount = ""
    custom_inference = "/root/inference.py"
    if os.path.exists(custom_inference):
        inference_mount = f"-v {custom_inference}:/app/inference.py"

    cmd = (
        f"docker run --rm --gpus all "
        f"-v {job_dir}:/output "
        f"{inference_mount} "
        f"{cfg['DOCKER_IMAGE']}"
    )

    timeout = int(cfg["DOCKER_TIMEOUT"])
    stdout, stderr, rc = run(cmd, timeout=timeout)

    if rc != 0:
        log(f"❌ Docker failed (rc={rc}): {stderr[:200]}", "ERROR")
        # Clean up stuck containers
        run("docker ps -q --filter ancestor=" + cfg["DOCKER_IMAGE"] + " | xargs -r docker kill", timeout=10)
        return None

    if not os.path.exists(result_file):
        log(f"❌ result.bin not found after inference", "ERROR")
        return None

    log(f"✅ Inference done — {result_file}")
    return result_file

# ── Step 4: Submit Result ──
def submit_result(cfg, job_id, result_file):
    """Submit inference result back to chain. Returns TX hash or None."""
    log(f"📤 Submitting result for job #{job_id}...")

    sha256 = sha256_file(result_file)
    result_url = f"{cfg['RESULT_BASE_URL']}/{job_id}/result.bin"

    # Step 4a: generate-only (unsigned TX)
    cmd_gen = (
        f"republicd tx computevalidation submit-job-result "
        f"{job_id} "
        f"{result_url} "
        f"{cfg['VERIFICATION_IMAGE']} "
        f"{sha256} "
        f"--from {cfg['WALLET_NAME']} "
        f"--home {cfg['NODE_HOME']} "
        f"--chain-id {cfg['CHAIN_ID']} "
        f"--gas 300000 "
        f"--gas-prices {cfg['GAS_PRICES']} "
        f"--node {cfg['NODE_RPC']} "
        f"--keyring-backend {cfg['KEYRING_BACKEND']} "
        f"--generate-only"
    )
    stdout, stderr, rc = run(cmd_gen, timeout=30)
    if rc != 0 or not stdout:
        log(f"❌ generate-only failed: {stderr[:200]}", "ERROR")
        return None

    # Write unsigned TX
    unsigned_path = "/tmp/tx_unsigned.json"
    with open(unsigned_path, "w") as f:
        f.write(stdout)

    # Step 4b: Fix bech32 validator address bug
    try:
        import bech32
        tx = json.load(open(unsigned_path))
        _, data = bech32.bech32_decode(cfg["WALLET_ADDRESS"])
        valoper = bech32.bech32_encode("raivaloper", data)
        tx["body"]["messages"][0]["validator"] = valoper
        json.dump(tx, open(unsigned_path, "w"))
    except ImportError:
        log("⚠️  bech32 module not found, skipping address fix", "WARN")
    except Exception as e:
        log(f"⚠️  bech32 fix failed: {e}", "WARN")

    # Step 4c: Sign
    cmd_sign = (
        f"republicd tx sign {unsigned_path} "
        f"--from {cfg['WALLET_NAME']} "
        f"--home {cfg['NODE_HOME']} "
        f"--chain-id {cfg['CHAIN_ID']} "
        f"--node {cfg['NODE_RPC']} "
        f"--keyring-backend {cfg['KEYRING_BACKEND']} "
        f"--output-document /tmp/tx_signed.json"
    )
    _, stderr, rc = run(cmd_sign, timeout=30)
    if rc != 0:
        log(f"❌ Sign failed: {stderr[:200]}", "ERROR")
        return None

    # Step 4d: Broadcast
    cmd_broadcast = (
        f"republicd tx broadcast /tmp/tx_signed.json "
        f"--node {cfg['NODE_RPC']} "
        f"--chain-id {cfg['CHAIN_ID']}"
    )
    stdout, stderr, rc = run(cmd_broadcast, timeout=30)
    output = stdout + "\n" + stderr

    for line in output.split("\n"):
        if "txhash" in line.lower():
            parts = line.strip().split()
            for i, p in enumerate(parts):
                if p.lower().rstrip(":") == "txhash" and i + 1 < len(parts):
                    return parts[i + 1]
            if ":" in line:
                return line.split(":", 1)[1].strip()

    log(f"❌ Broadcast failed: {output[:200]}", "ERROR")
    return None

# ── Step 5: Verify Job Status ──
def verify_job_status(cfg, job_id, target_status="PendingValidation", max_wait=120, poll_interval=10):
    """Poll job status until it reaches target_status or timeout.
    Returns the final status string."""
    log(f"🔎 Verifying job #{job_id} reaches '{target_status}'...")

    deadline = time.time() + max_wait
    last_status = "unknown"

    while time.time() < deadline:
        cmd = f"republicd query computevalidation job {job_id} --node {cfg['NODE_RPC']} -o json"
        data, err = run_json(cmd, timeout=15)

        if data:
            job = data.get("job", data)
            last_status = job.get("status", "unknown")
            log(f"   Job #{job_id} status: {last_status}")

            if target_status.lower() in last_status.lower():
                log(f"✅ Job #{job_id} confirmed: {last_status}")
                return last_status
        else:
            log(f"   Query failed: {err}", "WARN")

        time.sleep(poll_interval)

    log(f"⚠️  Job #{job_id} did not reach '{target_status}' within {max_wait}s (last: {last_status})", "WARN")
    return last_status

# ── Main Loop ──
def main():
    parser = argparse.ArgumentParser(description="RepublicAI Full Auto Compute")
    parser.add_argument("--interval", type=int, default=300, help="Interval between runs in seconds (default: 300 = 5min)")
    parser.add_argument("--dry-run", action="store_true", help="Print config and exit")
    parser.add_argument("--once", action="store_true", help="Run once then exit")
    args = parser.parse_args()

    cfg = load_config()
    cfg["INTERVAL"] = args.interval

    log("=" * 60)
    log("🚀 RepublicAI Full Auto Compute")
    log(f"   Wallet:     {cfg['WALLET_ADDRESS'][:10]}...{cfg['WALLET_ADDRESS'][-4:]}" if cfg['WALLET_ADDRESS'] else "   Wallet:     NOT SET")
    log(f"   Valoper:    {cfg['WALLET_VALOPER'][:14]}...{cfg['WALLET_VALOPER'][-4:]}" if cfg['WALLET_VALOPER'] else "   Valoper:    NOT SET")
    log(f"   RPC:        {cfg['NODE_RPC']}")
    log(f"   Job Fee:    {cfg['JOB_FEE']} ({int(cfg['JOB_FEE'].replace('arai','')) / 1e18:.4f} RAI)")
    log(f"   Gas Prices: {cfg['GAS_PRICES']}")
    log(f"   Result URL: {cfg['RESULT_BASE_URL']}")
    log(f"   Interval:   {cfg['INTERVAL']}s ({cfg['INTERVAL']//60}min)")
    log(f"   Docker:     {cfg['DOCKER_IMAGE']}")
    log("=" * 60)

    if args.dry_run:
        log("DRY RUN — exiting")
        return

    if not cfg["WALLET_ADDRESS"] or not cfg["WALLET_VALOPER"]:
        log("❌ Wallet or Valoper not configured! Cannot proceed.", "ERROR")
        sys.exit(1)

    # Graceful shutdown
    running = [True]
    def handle_signal(sig, frame):
        log("⏹  Shutting down...")
        running[0] = False
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    cycle = 0
    success = 0
    failed = 0

    while running[0]:
        cycle += 1
        log(f"━━━ Cycle #{cycle} (✅{success} ❌{failed}) ━━━")

        try:
            # Step 1: Submit job
            txhash = submit_job(cfg)
            if not txhash:
                failed += 1
                log(f"⏳ Retrying in {cfg['INTERVAL']}s...")
                time.sleep(cfg["INTERVAL"])
                continue

            log(f"✅ Submit TX: {txhash}")

            # Step 2: Get job ID
            job_id = get_job_id(cfg, txhash)
            if not job_id:
                failed += 1
                log(f"⏳ Retrying in {cfg['INTERVAL']}s...")
                time.sleep(cfg["INTERVAL"])
                continue

            log(f"📋 Job ID: {job_id}")

            # Step 3: Run inference
            result_file = run_inference(cfg, job_id)
            if not result_file:
                failed += 1
                log(f"⏳ Retrying in {cfg['INTERVAL']}s...")
                time.sleep(cfg["INTERVAL"])
                continue

            # Step 4: Submit result
            result_tx = submit_result(cfg, job_id, result_file)
            if not result_tx:
                failed += 1
                log(f"❌ Result submission failed for job #{job_id}", "ERROR")
                time.sleep(cfg["INTERVAL"])
                continue

            log(f"📤 Result TX: {result_tx}")

            # Step 5: Verify job reaches PendingValidation
            final_status = verify_job_status(cfg, job_id)
            if "pending" in final_status.lower() and "validation" in final_status.lower():
                success += 1
                log(f"🎉 Job #{job_id} COMPLETE — {final_status}")
            else:
                failed += 1
                log(f"⚠️  Job #{job_id} ended with status: {final_status}", "WARN")

        except Exception as e:
            failed += 1
            log(f"💥 Unexpected error: {e}", "ERROR")

        if args.once:
            log("--once flag set, exiting after 1 cycle")
            break

        log(f"⏳ Next cycle in {cfg['INTERVAL']}s ({cfg['INTERVAL']//60}min)...")
        for _ in range(cfg["INTERVAL"]):
            if not running[0]:
                break
            time.sleep(1)

    log(f"👋 Auto-compute stopped. Total: {cycle} cycles, ✅{success} success, ❌{failed} failed")

if __name__ == "__main__":
    main()
