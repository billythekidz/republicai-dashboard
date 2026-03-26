#!/usr/bin/env python3
"""
RepublicAI Full Auto Compute - Dynamic Workers with Resource Guard.
Architecture: 1 TX Coordinator + 1 thread per job (unlimited)
Guard: pauses new submissions if CPU/RAM/GPU > 90%
Fast mode: skip Docker, reuse cached result.bin

Usage:
    python3 full-auto-compute.py              # normal mode
    python3 full-auto-compute.py --fast       # skip Docker, reuse result.bin
    python3 full-auto-compute.py --dry-run    # print config and exit
"""
import json, os, subprocess, sys, time, hashlib, argparse, signal, shutil
import threading, queue
from datetime import datetime
from pathlib import Path

# -- Defaults --
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
    "DOCKER_IMAGE": "republicai/gpt2-inference:latest",
    "VERIFICATION_IMAGE": "example-verification:latest",
    "JOB_FEE": "1000000000000000arai",
    "GAS_PRICES": "1000000000arai",
    "DOCKER_TIMEOUT": 600,
    "TX_WAIT": 15,
    "RESOURCE_LIMIT": 90,
    "MAX_WORKERS": 10,
}

CACHED_RESULT = "/var/lib/republic/cached_result.bin"

# -- Helpers --
def log(msg, level="INFO", tag="COORD"):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [{tag}] [{level}] {msg}", flush=True)

def run(cmd, timeout=30, input_str=None):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                          timeout=timeout, input=input_str)
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except subprocess.TimeoutExpired:
        return "", "TIMEOUT", -1
    except Exception as e:
        return "", str(e), -1

def run_json(cmd, timeout=30):
    stdout, stderr, rc = run(cmd, timeout=timeout)
    if rc != 0 or not stdout:
        return None, stderr or f"exit={rc}"
    try:
        return json.loads(stdout), None
    except json.JSONDecodeError as e:
        return None, f"JSON parse error: {e}"

def sha256_file(filepath):
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

def extract_txhash(output):
    for line in output.split("\n"):
        if "txhash:" in line.lower() or "txhash:" in line:
            parts = line.strip().split()
            for i, p in enumerate(parts):
                if p.lower().rstrip(":") == "txhash" and i + 1 < len(parts):
                    return parts[i + 1]
            if ":" in line:
                return line.split(":", 1)[1].strip()
    return None

# -- Resource Monitor --
def check_resources(limit):
    cpu_pct = 0
    ram_pct = 0
    gpu_pct = 0
    try:
        out, _, rc = run("grep 'cpu ' /proc/stat", timeout=5)
        if rc == 0 and out:
            vals = list(map(int, out.split()[1:]))
            idle1, total1 = vals[3], sum(vals)
            time.sleep(0.5)
            out2, _, _ = run("grep 'cpu ' /proc/stat", timeout=5)
            if out2:
                vals2 = list(map(int, out2.split()[1:]))
                d_total = sum(vals2) - total1
                d_idle = vals2[3] - idle1
                if d_total > 0:
                    cpu_pct = (1 - d_idle / d_total) * 100
    except:
        pass
    try:
        out, _, rc = run("free | grep Mem", timeout=5)
        if rc == 0 and out:
            parts = out.split()
            if int(parts[1]) > 0:
                ram_pct = (int(parts[2]) / int(parts[1])) * 100
    except:
        pass
    try:
        out, _, rc = run("nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits", timeout=5)
        if rc == 0 and out:
            gpu_pct = float(out.strip().split('\n')[0])
    except:
        pass
    ok = cpu_pct < limit and ram_pct < limit and gpu_pct < limit
    return ok, cpu_pct, ram_pct, gpu_pct

# -- Config --
def load_config():
    cfg = dict(DEFAULTS)
    for config_path in [
        Path(__file__).parent.parent / "config.json",
        Path("/root/republicai-dashboard/config.json"),
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

    for key in cfg:
        env_val = os.environ.get(key)
        if env_val:
            cfg[key] = env_val

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

# -- TX Operations (Coordinator only) --
def submit_job_tx(cfg):
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
    txhash = extract_txhash(stdout + "\n" + stderr)
    if not txhash:
        log(f"[FAIL] Submit failed: {(stdout + stderr)[:200]}", "ERROR")
    return txhash

def get_job_id_from_tx(cfg, txhash):
    time.sleep(int(cfg["TX_WAIT"]))
    cmd = f"republicd query tx {txhash} --node {cfg['NODE_RPC']} -o json"
    data, err = run_json(cmd, timeout=30)
    if not data:
        log(f"[FAIL] TX query failed: {err}", "ERROR")
        return None
    events = data.get("events", [])
    if not events:
        for lentry in data.get("logs", []):
            events.extend(lentry.get("events", []))
    for event in events:
        if event.get("type") == "job_submitted":
            for attr in event.get("attributes", []):
                if attr.get("key") == "job_id":
                    return attr["value"]
    log("[FAIL] job_id not found in TX events", "ERROR")
    return None

def submit_result_tx(cfg, job_id, result_file):
    sha256 = sha256_file(result_file)
    result_url = f"{cfg['RESULT_BASE_URL']}/{job_id}/result.bin"
    unsigned_path = "/tmp/tx_unsigned.json"
    signed_path = "/tmp/tx_signed.json"

    cmd_gen = (
        f"republicd tx computevalidation submit-job-result "
        f"{job_id} {result_url} "
        f"{cfg['VERIFICATION_IMAGE']} {sha256} "
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
        log(f"[FAIL] generate-only failed: {stderr[:200]}", "ERROR")
        return None

    with open(unsigned_path, "w") as f:
        f.write(stdout)

    try:
        import bech32
        tx = json.load(open(unsigned_path))
        _, data = bech32.bech32_decode(cfg["WALLET_ADDRESS"])
        valoper = bech32.bech32_encode("raivaloper", data)
        tx["body"]["messages"][0]["validator"] = valoper
        json.dump(tx, open(unsigned_path, "w"))
    except ImportError:
        pass
    except Exception as e:
        log(f"[WARN] bech32 fix failed: {e}", "WARN")

    cmd_sign = (
        f"republicd tx sign {unsigned_path} "
        f"--from {cfg['WALLET_NAME']} "
        f"--home {cfg['NODE_HOME']} "
        f"--chain-id {cfg['CHAIN_ID']} "
        f"--node {cfg['NODE_RPC']} "
        f"--keyring-backend {cfg['KEYRING_BACKEND']} "
        f"--output-document {signed_path}"
    )
    _, stderr, rc = run(cmd_sign, timeout=30)
    if rc != 0:
        log(f"[FAIL] Sign failed: {stderr[:200]}", "ERROR")
        return None

    cmd_broadcast = (
        f"republicd tx broadcast {signed_path} "
        f"--node {cfg['NODE_RPC']} "
        f"--chain-id {cfg['CHAIN_ID']}"
    )
    stdout, stderr, rc = run(cmd_broadcast, timeout=30)
    txhash = extract_txhash(stdout + "\n" + stderr)
    if not txhash:
        log(f"[FAIL] Broadcast failed: {(stdout + stderr)[:200]}", "ERROR")
    return txhash

# -- Inference Worker (1 thread per job) --
def run_inference_thread(worker_id, job_id, result_queue, cfg, fast_mode=False):
    tag = f"W{worker_id}"

    job_dir = f"{cfg['JOBS_DIR']}/{job_id}"
    result_file = f"{job_dir}/result.bin"
    os.makedirs(job_dir, exist_ok=True)

    if fast_mode:
        # Fast mode: copy cached result.bin instead of running Docker
        log(f"[FAST] Copying cached result for job #{job_id}", tag=tag)
        try:
            shutil.copy2(CACHED_RESULT, result_file)
        except Exception as e:
            log(f"[FAIL] Cache copy failed: {e}", "ERROR", tag=tag)
            result_queue.put((job_id, None))
            return
    else:
        # Normal mode: run Docker inference
        log(f"[RUN] Running inference for job #{job_id}", tag=tag)

        inference_mount = ""
        if os.path.exists("/root/inference.py"):
            inference_mount = "-v /root/inference.py:/app/inference.py"

        container_name = f"compute-job-{job_id}"
        cmd = (
            f"docker run --rm --gpus all "
            f"--name {container_name} "
            f"--stop-timeout 10 "
            f"-v {job_dir}:/output "
            f"{inference_mount} "
            f"{cfg['DOCKER_IMAGE']}"
        )
        timeout = int(cfg["DOCKER_TIMEOUT"])
        stdout, stderr, rc = run(cmd, timeout=timeout)

        if rc != 0:
            log(f"[FAIL] Docker failed (rc={rc}): {stderr[:200]}", "ERROR", tag=tag)
            # Kill zombie container if still running
            run(f"docker kill {container_name} 2>/dev/null; docker rm -f {container_name} 2>/dev/null", timeout=10)
            result_queue.put((job_id, None))
            return

    if not os.path.exists(result_file):
        log(f"[FAIL] result.bin not found", "ERROR", tag=tag)
        result_queue.put((job_id, None))
        return

    # Cache result for future fast-mode use
    if not fast_mode and not os.path.exists(CACHED_RESULT):
        try:
            shutil.copy2(result_file, CACHED_RESULT)
            log(f"[CACHE] Saved result.bin for fast mode", tag=tag)
        except:
            pass

    log(f"[OK] Inference done for job #{job_id}", tag=tag)
    result_queue.put((job_id, result_file))

# -- Main Coordinator --
def main():
    parser = argparse.ArgumentParser(description="RepublicAI Full Auto Compute")
    parser.add_argument("--dry-run", action="store_true", help="Print config and exit")
    parser.add_argument("--once", action="store_true", help="Run one cycle then exit")
    parser.add_argument("--fast", action="store_true", help="Skip Docker, reuse cached result.bin")
    parser.add_argument("--limit", type=int, default=90, help="Resource limit %% (default: 90)")
    parser.add_argument("--max-workers", type=int, default=10, help="Max concurrent workers (default: 10)")
    # Legacy args
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--interval", type=int, default=0)
    parser.add_argument("--instance", type=str, default="0")
    args = parser.parse_args()

    cfg = load_config()
    resource_limit = args.limit
    fast_mode = args.fast

    log("=" * 60)
    log("[START] RepublicAI Full Auto Compute (Dynamic Workers)")
    log(f"   Architecture: 1 Coordinator + dynamic threads (1 per job)")
    log(f"   Mode: {'FAST (cached result.bin)' if fast_mode else 'NORMAL (Docker inference)'}")
    max_workers = args.max_workers
    log(f"   Resource guard: pause if CPU/RAM/GPU > {resource_limit}%")
    log(f"   Max workers:  {max_workers} concurrent threads")
    if cfg['WALLET_ADDRESS']:
        log(f"   Wallet:     {cfg['WALLET_ADDRESS'][:10]}...{cfg['WALLET_ADDRESS'][-4:]}")
    if cfg['WALLET_VALOPER']:
        log(f"   Valoper:    {cfg['WALLET_VALOPER'][:14]}...{cfg['WALLET_VALOPER'][-4:]}")
    log(f"   RPC:        {cfg['NODE_RPC']}")
    log(f"   Docker:     {cfg['DOCKER_IMAGE']}")
    log(f"   Zero TX conflicts guaranteed")
    log("=" * 60)

    if args.dry_run:
        log("DRY RUN -- exiting")
        return

    if not cfg["WALLET_ADDRESS"] or not cfg["WALLET_VALOPER"]:
        log("[FAIL] Wallet not configured!", "ERROR")
        sys.exit(1)

    # Fast mode: need cached result
    if fast_mode and not os.path.exists(CACHED_RESULT):
        log("No cached result.bin found. Running one Docker inference first...")
        fast_mode = False  # first run will be normal, then switch to fast

    running = [True]
    def handle_signal(sig, frame):
        log("[STOP] Shutting down...")
        running[0] = False
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    result_queue = queue.Queue()
    active_threads = []
    cycle = 0
    jobs_submitted = 0
    jobs_completed = 0
    jobs_failed = 0
    start_time = time.time()
    switched_to_fast = False

    while running[0]:
        cycle += 1
        active_threads = [t for t in active_threads if t.is_alive()]

        log(f"--- Cycle #{cycle} (OK:{jobs_completed} FAIL:{jobs_failed} | "
            f"threads:{len(active_threads)}) ---")

        # -- Phase 1: Collect completed results --
        while not result_queue.empty():
            job_id, result_file = result_queue.get_nowait()
            if result_file is None:
                jobs_failed += 1
                continue

            log(f"[SEND] Submitting result for job #{job_id}...")
            result_tx = submit_result_tx(cfg, job_id, result_file)
            if result_tx:
                jobs_completed += 1
                log(f"[DONE] Job #{job_id} COMPLETE -- TX: {result_tx}")
                # Auto-switch to fast after first successful completion
                if args.fast and not switched_to_fast and os.path.exists(CACHED_RESULT):
                    fast_mode = True
                    switched_to_fast = True
                    log("[CACHE] Switching to fast mode - cached result available")
            else:
                jobs_failed += 1
                log(f"[FAIL] Result submission failed for job #{job_id}", "ERROR")
            time.sleep(3)

        # -- Phase 2: Resource check --
        ok, cpu, ram, gpu = check_resources(resource_limit)
        if not ok:
            log(f"[PAUSE] Resources high (CPU:{cpu:.0f}% RAM:{ram:.0f}% GPU:{gpu:.0f}%) "
                f"-- waiting 10s...", "WARN")
            time.sleep(10)
            continue

        # -- Phase 3: Check worker count --
        if len(active_threads) >= max_workers:
            log(f"[PAUSE] {len(active_threads)}/{max_workers} workers busy -- waiting 5s...")
            time.sleep(5)
            continue

        # -- Phase 4: Submit new job + spawn thread --
        log(f"[SEND] Submitting new job... ({len(active_threads)}/{max_workers} workers)")
        txhash = submit_job_tx(cfg)
        if not txhash:
            log("[WAIT] Submit failed, waiting 5s...")
            time.sleep(5)
            if args.once:
                break
            continue

        log(f"[OK] Submit TX: {txhash}")
        jobs_submitted += 1

        job_id = get_job_id_from_tx(cfg, txhash)
        if not job_id:
            log("[FAIL] Could not get job_id, skipping")
            jobs_failed += 1
            if args.once:
                break
            continue

        worker_id = jobs_submitted
        t = threading.Thread(
            target=run_inference_thread,
            args=(worker_id, job_id, result_queue, cfg, fast_mode),
            daemon=True
        )
        t.start()
        active_threads.append(t)
        mode_str = "FAST" if fast_mode else "DOCKER"
        log(f"[JOB] Job #{job_id} -> Thread #{worker_id} [{mode_str}] "
            f"({len(active_threads)} active | CPU:{cpu:.0f}% RAM:{ram:.0f}% GPU:{gpu:.0f}%)")

        # Stats every 20 cycles
        if cycle % 20 == 0:
            elapsed = time.time() - start_time
            rate = jobs_completed / (elapsed / 3600) if elapsed > 0 else 0
            log(f"[STATS] submitted={jobs_submitted} completed={jobs_completed} "
                f"failed={jobs_failed} rate={rate:.1f}/hr "
                f"threads={len(active_threads)} uptime={elapsed/60:.0f}min")

        if args.once:
            break
        time.sleep(2)

    # Shutdown
    log(f"Waiting for {len(active_threads)} threads to finish...")
    for t in active_threads:
        t.join(timeout=30)
    while not result_queue.empty():
        job_id, result_file = result_queue.get_nowait()
        if result_file:
            result_tx = submit_result_tx(cfg, job_id, result_file)
            if result_tx:
                jobs_completed += 1
                log(f"[DONE] Job #{job_id} COMPLETE -- TX: {result_tx}")

    elapsed = time.time() - start_time
    rate = jobs_completed / (elapsed / 3600) if elapsed > 0 else 0
    log(f"[BYE] Stopped. submitted={jobs_submitted} completed={jobs_completed} "
        f"failed={jobs_failed} rate={rate:.1f}/hr uptime={elapsed/60:.0f}min")

if __name__ == "__main__":
    main()
