#!/bin/bash
#═══════════════════════════════════════════════════════════
#  RepublicAI Compute Job — Full Pipeline
#  Usage: bash compute-job.sh [JOB_ID]
#     or: bash compute-job.sh            (auto-submit new job to self)
#═══════════════════════════════════════════════════════════
set -euo pipefail

# ── Config from env (injected by dashboard server.js) ─────
WALLET_NAME="${WALLET_NAME:-my-wallet}"
HOME_DIR="${NODE_HOME:-/root/.republicd}"
CHAIN_ID="${CHAIN_ID:-raitestnet_77701-1}"
NODE="${NODE_RPC:-tcp://localhost:26657}"
JOBS_DIR="/var/lib/republic/jobs"
RESULT_BASE_URL="${RESULT_BASE_URL:-https://republicai.devn.cloud}"
INFERENCE_IMAGE="republic-llm-inference:latest"
VERIFY_IMAGE="example-verification:latest"
KB="${KEYRING_BACKEND:-test}"
LOGS_DIR="/var/lib/republic/logs"
mkdir -p "$LOGS_DIR"

VALOPER="${WALLET_VALOPER:-$(republicd keys show "$WALLET_NAME" --bech val -a --home "$HOME_DIR" --keyring-backend "$KB" 2>/dev/null)}"
WALLET="${WALLET_ADDRESS:-$(republicd keys show "$WALLET_NAME" -a --home "$HOME_DIR" --keyring-backend "$KB" 2>/dev/null)}"

ts() { date "+%Y-%m-%d %H:%M:%S"; }

echo ""
echo "╔═══════════════════════════════════════════════════════╗"
echo "║       RepublicAI Compute Job — Full Pipeline          ║"
echo "╠═══════════════════════════════════════════════════════╣"
echo "║  Wallet:   $WALLET"
echo "║  Valoper:  $VALOPER"
echo "║  Node:     $NODE"
echo "║  Time:     $(ts)"
echo "╚═══════════════════════════════════════════════════════╝"
echo ""

# ── Step 0: Determine Job ID ─────────────────────────────
if [ -n "${1:-}" ]; then
    JOB_ID="$1"
    echo "[$(ts)] ℹ️  Using provided Job ID: $JOB_ID"
else
    echo "[$(ts)] 📤 Step 0: Submitting new job to self..."
    SUBMIT_OUTPUT=$(republicd tx computevalidation submit-job \
        "$VALOPER" \
        "$INFERENCE_IMAGE" \
        "http://localhost:8081/upload" \
        "http://localhost:8081" \
        "$VERIFY_IMAGE" \
        1000000000000000000arai \
        --from "$WALLET_NAME" \
        --home "$HOME_DIR" \
        --chain-id "$CHAIN_ID" \
        --gas 300000 \
        --gas-prices 1000000000arai \
        --node "$NODE" \
        --keyring-backend "$KB" -y -o json 2>&1)

    SUBMIT_TX=$(echo "$SUBMIT_OUTPUT" | jq -r '.txhash // empty' 2>/dev/null || true)
    SUBMIT_CODE=$(echo "$SUBMIT_OUTPUT" | jq -r '.code // empty' 2>/dev/null || true)

    if [ -z "$SUBMIT_TX" ]; then
        echo "[$(ts)] ❌ Failed to submit job!"
        echo "$SUBMIT_OUTPUT"
        exit 1
    fi

    echo "[$(ts)]    TX Hash:  $SUBMIT_TX"
    echo "[$(ts)]    TX Code:  ${SUBMIT_CODE:-0}"
    echo "[$(ts)]    ⏳ Waiting 8s for TX to be indexed..."
    sleep 8

    # Extract job_id from TX events
    JOB_ID=$(republicd query tx "$SUBMIT_TX" --node "$NODE" -o json 2>/dev/null | \
        jq -r '[.events[] | select(.type=="job_submitted") | .attributes[] | select(.key=="job_id") | .value] | first // empty')

    if [ -z "$JOB_ID" ]; then
        echo "[$(ts)] ❌ Could not extract Job ID from TX $SUBMIT_TX"
        exit 1
    fi

    echo "[$(ts)]    ✅ Job created: #$JOB_ID"
    echo ""
fi

# ── Step 1: Query job details ────────────────────────────
echo "[$(ts)] 🔍 Step 1: Querying job #$JOB_ID..."
JOB_JSON=$(republicd query computevalidation job "$JOB_ID" --node "$NODE" -o json 2>/dev/null)
JOB_STATUS=$(echo "$JOB_JSON" | jq -r '.job.status')
JOB_CREATOR=$(echo "$JOB_JSON" | jq -r '.job.creator')
JOB_TARGET=$(echo "$JOB_JSON" | jq -r '.job.target_validator')
JOB_RESULT_HASH=$(echo "$JOB_JSON" | jq -r '.job.result_hash')
JOB_FETCH=$(echo "$JOB_JSON" | jq -r '.job.result_fetch_endpoint')

echo "[$(ts)]    Job ID:         $JOB_ID"
echo "[$(ts)]    Status:         $JOB_STATUS"
echo "[$(ts)]    Creator:        $JOB_CREATOR"
echo "[$(ts)]    Target:         $JOB_TARGET"
echo "[$(ts)]    Result Hash:    ${JOB_RESULT_HASH:-(empty)}"
echo ""

if [ "$JOB_STATUS" = "PendingValidation" ]; then
    echo "[$(ts)] ✅ Job already completed (PendingValidation). Nothing to do."
    exit 0
fi

if [ "$JOB_STATUS" != "PendingExecution" ]; then
    echo "[$(ts)] ⚠️  Job status is '$JOB_STATUS', expected 'PendingExecution'."
    exit 1
fi

# ── Step 2: Run GPU inference ────────────────────────────
RESULT_FILE="$JOBS_DIR/$JOB_ID/result.bin"
mkdir -p "$JOBS_DIR/$JOB_ID"

echo "[$(ts)] 🖥️  Step 2: Running GPU inference..."
echo "[$(ts)]    Image: $INFERENCE_IMAGE"
echo "[$(ts)]    Output: $RESULT_FILE"

DOCKER_START=$(date +%s)

if [ -f /root/inference.py ]; then
    echo "[$(ts)]    Using patched /root/inference.py"
    docker run --rm --gpus all \
        -v "$JOBS_DIR/$JOB_ID:/output" \
        -v /root/inference.py:/app/inference.py \
        "$INFERENCE_IMAGE" 2>&1
else
    echo "[$(ts)]    Using built-in inference.py"
    docker run --rm --gpus all \
        -v "$JOBS_DIR/$JOB_ID:/output" \
        "$INFERENCE_IMAGE" 2>&1
fi

DOCKER_END=$(date +%s)
DOCKER_DURATION=$((DOCKER_END - DOCKER_START))

if [ ! -f "$RESULT_FILE" ]; then
    echo "[$(ts)] ❌ Inference failed — no result.bin produced"
    exit 1
fi

RESULT_SIZE=$(stat -c%s "$RESULT_FILE")
RESULT_HASH=$(sha256sum "$RESULT_FILE" | awk '{print $1}')

echo ""
echo "[$(ts)]    ✅ Inference completed in ${DOCKER_DURATION}s"
echo "[$(ts)]    File:   $RESULT_FILE"
echo "[$(ts)]    Size:   $RESULT_SIZE bytes"
echo "[$(ts)]    SHA256: $RESULT_HASH"
echo ""

# ── Step 3: Submit result on-chain ───────────────────────
RESULT_URL="$RESULT_BASE_URL/$JOB_ID/result.bin"

echo "[$(ts)] ⛓️  Step 3: Submitting result on-chain..."
echo "[$(ts)]    Result URL:  $RESULT_URL"
echo "[$(ts)]    Result Hash: $RESULT_HASH"

# Generate unsigned TX
republicd tx computevalidation submit-job-result \
    "$JOB_ID" \
    "$RESULT_URL" \
    "$VERIFY_IMAGE" \
    "$RESULT_HASH" \
    --from "$WALLET_NAME" \
    --home "$HOME_DIR" \
    --chain-id "$CHAIN_ID" \
    --gas 500000 \
    --gas-prices 1000000000arai \
    --node "$NODE" \
    --keyring-backend "$KB" \
    --generate-only 2>/dev/null > /tmp/tx_unsigned.json

# Patch bech32 prefix (known CLI bug: sends rai1 instead of raivaloper)
python3 -c "
import bech32, json
tx = json.load(open('/tmp/tx_unsigned.json'))
msg = tx['body']['messages'][0]
creator = msg.get('creator') or msg.get('validator','')
if creator.startswith('rai1'):
    hrp, data = bech32.bech32_decode(creator)
    msg['validator'] = bech32.bech32_encode('raivaloper', data)
json.dump(tx, open('/tmp/tx_unsigned.json','w'))
"

# Sign
republicd tx sign /tmp/tx_unsigned.json \
    --from "$WALLET_NAME" \
    --home "$HOME_DIR" \
    --chain-id "$CHAIN_ID" \
    --node "$NODE" \
    --keyring-backend "$KB" \
    --output-document /tmp/tx_signed.json 2>/dev/null

# Broadcast
BROADCAST_OUTPUT=$(republicd tx broadcast /tmp/tx_signed.json \
    --node "$NODE" \
    --chain-id "$CHAIN_ID" -o json 2>&1)

RESULT_TX=$(echo "$BROADCAST_OUTPUT" | jq -r '.txhash // empty' 2>/dev/null || true)
RESULT_CODE=$(echo "$BROADCAST_OUTPUT" | jq -r '.code // empty' 2>/dev/null || true)

if [ -z "$RESULT_TX" ]; then
    echo "[$(ts)] ❌ Broadcast failed!"
    echo "$BROADCAST_OUTPUT"
    exit 1
fi

echo "[$(ts)]    TX Hash: $RESULT_TX"
echo "[$(ts)]    TX Code: ${RESULT_CODE:-0}"
echo ""

# ── Step 4: Verify final status ─────────────────────────
echo "[$(ts)] ⏳ Step 4: Waiting 8s for confirmation..."
sleep 8

FINAL_JSON=$(republicd query computevalidation job "$JOB_ID" --node "$NODE" -o json 2>/dev/null)
FINAL_STATUS=$(echo "$FINAL_JSON" | jq -r '.job.status')
FINAL_HASH=$(echo "$FINAL_JSON" | jq -r '.job.result_hash')

echo ""
echo "╔═══════════════════════════════════════════════════════╗"
echo "║                   RESULT SUMMARY                      ║"
echo "╠═══════════════════════════════════════════════════════╣"
echo "║  Job ID:          $JOB_ID"
echo "║  Final Status:    $FINAL_STATUS"
echo "║  Result Hash:     $FINAL_HASH"
echo "║  Submit TX:       ${SUBMIT_TX:-N/A}"
echo "║  Result TX:       $RESULT_TX"
echo "║  Inference Time:  ${DOCKER_DURATION}s"
echo "║  Result Size:     $RESULT_SIZE bytes"
echo "║  Timestamp:       $(ts)"
echo "╚═══════════════════════════════════════════════════════╝"

if [ "$FINAL_STATUS" = "PendingValidation" ]; then
    echo ""
    echo "🎉 SUCCESS — Job #$JOB_ID is now PendingValidation!"
else
    echo ""
    echo "⚠️  Status is '$FINAL_STATUS' — check TX: $RESULT_TX"
fi

# ── Save log ──────────────────────────────────────────────
LOG_FILE="$LOGS_DIR/job-${JOB_ID}.log"
cat <<EOF > "$LOG_FILE"
=== Compute Job #$JOB_ID ===
Timestamp:       $(ts)
Final Status:    $FINAL_STATUS
Result Hash:     $FINAL_HASH
Submit TX:       ${SUBMIT_TX:-N/A}
Result TX:       $RESULT_TX
Inference Time:  ${DOCKER_DURATION}s
Result Size:     $RESULT_SIZE bytes
Creator:         $JOB_CREATOR
Target:          $JOB_TARGET
Wallet:          $WALLET
Valoper:         $VALOPER
EOF
echo ""
echo "📝 Log saved: $LOG_FILE"
