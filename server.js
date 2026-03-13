const express = require('express');
const { spawn, execSync } = require('child_process');
const path = require('path');
const fs = require('fs');
const app = express();
const PORT = 3847;

app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

const SCRIPTS_DIR = path.join(__dirname, 'scripts');
const CONFIG_PATH = path.join(__dirname, 'config.json');

// ── Load / generate config ─────────────────────────────
let nodeConfig = {};

function loadConfig() {
    // Auto-generate if missing
    if (!fs.existsSync(CONFIG_PATH)) {
        console.log('config.json not found, running auto-detect...');
        try {
            execSync('python3 ' + path.join(__dirname, 'detect-config.py') + ' --output ' + CONFIG_PATH, {
                stdio: 'inherit', timeout: 30000
            });
        } catch (e) {
            console.error('Auto-detect failed:', e.message);
        }
    }
    if (fs.existsSync(CONFIG_PATH)) {
        nodeConfig = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
        console.log('Config loaded: ' + nodeConfig.node?.moniker + ' (' + nodeConfig.node?.chain_id + ')');
    }
}
loadConfig();

// Build env vars from config for scripts
function configEnv() {
    const c = nodeConfig;
    return {
        NODE_HOME: c.node?.home || '/root/.republicd',
        NODE_MONIKER: c.node?.moniker || '',
        NODE_CHAIN_ID: c.node?.chain_id || '',
        NODE_RPC: c.endpoints?.rpc || 'tcp://localhost:26657',
        NODE_RPC_HTTP: c.endpoints?.rpc_http || 'http://localhost:26657',
        NODE_RPC_PORT: String(c.ports?.rpc || 26657),
        NODE_API: c.endpoints?.api || '',
        NODE_GRPC: c.endpoints?.grpc || '',
        WALLET_NAME: c.wallet?.name || 'my-wallet',
        WALLET_ADDRESS: c.wallet?.address || '',
        WALLET_VALOPER: c.wallet?.valoper || '',
        KEYRING_BACKEND: c.wallet?.keyring_backend || 'test',
        DOCKER_INFERENCE_IMAGE: c.docker?.inference_image || 'republic-llm-inference:latest',
    };
}

// Build env for child processes
function childEnv() {
    return {
        ...process.env,
        TERM: 'dumb',
        HOME: process.env.HOME || '/root',
        PATH: '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/root/go/bin',
        ...configEnv()
    };
}

// Run a shell command (we're inside WSL already!)
function runCmd(script) {
    return spawn('bash', ['-c', script], { env: childEnv() });
}

// Run a Python script
function runPython(scriptPath, args) {
    const pyArgs = [scriptPath];
    if (args) pyArgs.push(...args.split(/\s+/));
    return spawn('python3', pyArgs, { env: childEnv() });
}

// Expose config to frontend
app.get('/api/config', (req, res) => res.json(nodeConfig));

// Re-detect config
app.post('/api/config/refresh', (req, res) => {
    try {
        execSync('python3 ' + path.join(__dirname, 'detect-config.py') + ' --output ' + CONFIG_PATH, {
            stdio: 'pipe', timeout: 30000
        });
        loadConfig();
        res.json({ ok: true, config: nodeConfig });
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// ── HTTP helper for RPC calls ──
const http = require('http');
function rpcGet(url) {
    return new Promise((resolve, reject) => {
        const req = http.get(url, { timeout: 5000 }, (res) => {
            let data = '';
            res.on('data', c => data += c);
            res.on('end', () => { try { resolve(JSON.parse(data)); } catch (e) { reject(e); } });
        });
        req.on('error', reject);
        req.on('timeout', () => { req.destroy(); reject(new Error('timeout')); });
    });
}

let rpcHttpResolved = null;
async function tryRpcGet(path) {
    const candidates = rpcHttpResolved
        ? [rpcHttpResolved]
        : [
            nodeConfig.endpoints?.rpc_http,
            'http://localhost:26657',
            'http://localhost:26658',
        ].filter(Boolean);
    for (const base of candidates) {
        try {
            const data = await rpcGet(`${base}${path}`);
            rpcHttpResolved = base;
            return data;
        } catch (e) {
            if (e.message && (e.message.includes('ECONNREFUSED') || e.message.includes('timeout'))) continue;
            throw e;
        }
    }
    throw new Error('All RPC endpoints unreachable');
}

// ── Latest Blocks endpoint (cached 3s) ──
let blocksCache = { data: null, ts: 0 };
app.get('/api/blocks', async (req, res) => {
    const now = Date.now();
    if (blocksCache.data && now - blocksCache.ts < 3000) {
        return res.json(blocksCache.data);
    }
    try {
        const status = await tryRpcGet('/status');
        const latestHeight = parseInt(status.result.sync_info.latest_block_height);
        const minHeight = Math.max(1, latestHeight - 19);
        const blockchain = await tryRpcGet(`/blockchain?minHeight=${minHeight}&maxHeight=${latestHeight}`);
        const blocks = (blockchain.result.block_metas || []).map(b => ({
            height: b.header.height,
            hash: b.block_id.hash,
            time: b.header.time,
            num_txs: parseInt(b.num_txs || '0'),
        }));
        blocks.sort((a, b) => parseInt(b.height) - parseInt(a.height));
        blocksCache = { data: blocks, ts: now };
        res.json(blocks);
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// SSE endpoint — streams command output in real-time
app.get('/api/run', (req, res) => {
    const cmdId = req.query.cmd;
    const args = (req.query.args || '').trim();
    const command = COMMANDS[cmdId];
    if (!command) return res.status(400).json({ error: 'Unknown command: ' + cmdId });

    let proc;
    if (command.pyfile) {
        // Python script
        proc = runPython(path.join(SCRIPTS_DIR, command.pyfile), args);
    } else {
        let script;
        if (command.file) {
            const argStr = args ? ' ' + args : '';
            script = 'bash ' + path.join(SCRIPTS_DIR, command.file) + argStr;
        } else if (typeof command.script === 'function') {
            script = command.script(args);
        } else {
            script = command.script;
        }
        proc = runCmd(script);
    }

    res.writeHead(200, {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        Connection: 'keep-alive',
    });

    // proc already created above
    let output = '';

    proc.stdout.on('data', (d) => {
        const text = d.toString();
        output += text;
        res.write('data: ' + JSON.stringify({ type: 'stdout', text }) + '\n\n');
    });
    proc.stderr.on('data', (d) => {
        const text = d.toString();
        output += text;
        res.write('data: ' + JSON.stringify({ type: 'stderr', text }) + '\n\n');
    });
    proc.on('close', (code) => {
        res.write('data: ' + JSON.stringify({ type: 'done', code, output }) + '\n\n');
        res.end();
    });
    proc.on('error', (err) => {
        res.write('data: ' + JSON.stringify({ type: 'error', text: err.message }) + '\n\n');
        res.end();
    });
    req.on('close', () => { try { proc.kill(); } catch (e) { } });
});

// ── Command Registry ────────────────────────────────────
const COMMANDS = {};

function reg(id, label, group, icon, opts) {
    if (typeof opts === 'string') {
        COMMANDS[id] = { label, group, icon, script: opts };
    } else if (typeof opts === 'function') {
        COMMANDS[id] = { label, group, icon, script: opts };
    } else {
        COMMANDS[id] = { label, group, icon, ...opts };
    }
}

// === Status (all Python) ===
reg('status', 'Node Status', 'status', '🟢', { pyfile: 'status.py' });
reg('services', 'Services Status', 'status', '⚙️', { pyfile: 'services.py' });
reg('delegations', 'Delegations', 'status', '🤝', { pyfile: 'delegations.py' });
reg('validators', 'All Validators', 'status', '📊', { pyfile: 'validators.py' });
reg('peers', 'Connected Peers', 'status', '🌐', { pyfile: 'peers.py' });
reg('share-peers', '🔗 Share Peers', 'status', '📡', { pyfile: 'share-peers.py' });

// === Jobs (all Python) ===
reg('list-jobs', 'List My Jobs', 'jobs', '📋', { pyfile: 'list-jobs.py' });
reg('all-jobs', 'All Jobs', 'jobs', '📜', { pyfile: 'all-jobs.py' });
reg('job-history', 'Job History', 'jobs', '📂', { pyfile: 'job-history.py' });
reg('query-job', 'Query Job', 'jobs', '🔍', function (input) {
    input = (input || '').trim();
    if (/^[0-9]+$/.test(input)) {
        // Numeric = Job ID → show job details + find TX
        return 'echo "🔍 Job #' + input + ' — Full Details" && echo "" && ' +
            'echo "=== Job Status ===" && ' +
            'republicd query computevalidation job ' + input + ' --node $NODE_RPC -o json 2>&1 | jq -r \'.job | ' +
            '"  ID:         " + .id + "\\n" + ' +
            '"  Status:     " + .status + "\\n" + ' +
            '"  Creator:    " + .creator + "\\n" + ' +
            '"  Target:     " + .target_validator + "\\n" + ' +
            '"  Hash:       " + (.result_hash // "-") + "\\n" + ' +
            '"  Fetch URL:  " + (.result_fetch_endpoint // "-") + "\\n" + ' +
            '"  Inference:  " + (.inference_image // "-") + "\\n" + ' +
            '"  Verify:     " + (.verification_image // "-")\' && echo "" && ' +
            'echo "=== Submit Transaction ===" && ' +
            'TXJSON=$(republicd query txs --query "job_submitted.job_id=\'' + input + '\'" --node $NODE_RPC -o json 2>&1) && ' +
            'TXHASH=$(echo "$TXJSON" | jq -r ".txs[0].txhash // empty") && ' +
            'if [ -z "$TXHASH" ]; then echo "  No submit TX found"; else ' +
            'echo "$TXJSON" | jq -r \'.txs[0] | ' +
            '"  TX Hash:    " + .txhash + "\\n" + ' +
            '"  Height:     " + .height + "\\n" + ' +
            '"  Gas Used:   " + .gas_used + " / " + .gas_wanted + "\\n" + ' +
            '"  Timestamp:  " + .timestamp + "\\n" + ' +
            '"  Code:       " + (.code // 0 | tostring)\' && echo "" && ' +
            'echo "=== Events ===" && echo "$TXJSON" | jq -r \'.txs[0].events[] | ' +
            '"  [" + .type + "]" + "\\n" + ' +
            '(.attributes | map("    " + .key + " = " + .value) | join("\\n"))\'; fi';
    }
    // Otherwise treat as TX hash
    return 'republicd query tx ' + input + ' --node $NODE_RPC -o json 2>&1 | jq .';
});
reg('submit-self', 'Submit + Compute (Self)', 'jobs', '📤', { file: 'compute-job.sh' });
reg('compute-job', 'Compute Job', 'jobs', '🖥️', function (id) {
    return 'bash ' + path.join(SCRIPTS_DIR, 'compute-job.sh') + ' ' + id;
});

// === Service Control ===
reg('svc-start', 'Start', 'services', '▶️', function (s) { return 'systemctl start ' + s + ' && echo "Started ' + s + '" && systemctl is-active ' + s; });
reg('svc-stop', 'Stop', 'services', '⏹️', function (s) { return 'systemctl stop ' + s + ' && echo "Stopped ' + s + '"'; });
reg('svc-restart', 'Restart', 'services', '🔄', function (s) { return 'systemctl restart ' + s + ' && echo "Restarted ' + s + '" && systemctl is-active ' + s; });
reg('svc-logs', 'Logs', 'services', '📜', function (s) { return 'journalctl -u ' + s + ' --no-pager -n 100'; });

// === Quick ===
reg('ctl-status', 'Full CTL Status', 'quick', '📊', 'echo "=== Service Status ===" && for s in republicd republic-sidecar republic-autocompute republic-dashboard; do printf "%-30s %s\\n" "$s" "$(systemctl is-active $s 2>/dev/null || echo inactive)"; done && echo && echo "=== Republic Node ===" && republicd status --node $NODE_RPC 2>&1 | jq -r \'.node_info.moniker + " | height: " + .sync_info.latest_block_height + " | catching_up: " + (.sync_info.catching_up|tostring)\' 2>/dev/null || echo "node unreachable"');
reg('verify-info', 'Verification Info', 'quick', '📋', { pyfile: 'verify-info.py' });
reg('docker-images', 'Docker Images', 'quick', '🐳', 'docker images --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}\t{{.CreatedAt}}"');
reg('detect-config', 'Re-detect Config', 'quick', '🔧', 'python3 ' + path.join(__dirname, 'detect-config.py'));
reg('update-dashboard', '⬆️ Update Dashboard', 'quick', '🔄', 'cd ' + __dirname + ' && echo "=== Pulling latest from git ===" && git fetch origin && git reset --hard origin/main && echo "" && echo "=== Installing dependencies ===" && npm install --omit=dev && echo "" && echo "✅ Updated! Restarting in 2s... (page will reload)" && nohup bash -c "sleep 2 && systemctl restart republic-dashboard" >/dev/null 2>&1 &');

// === Custom ===
reg('custom', 'Custom', 'custom', '⌨️', function (cmd) { return cmd; });

// Command list endpoint (includes services from config for UI)
app.get('/api/commands', (req, res) => {
    const cmds = {};
    for (const [id, cmd] of Object.entries(COMMANDS)) {
        cmds[id] = { label: cmd.label, group: cmd.group, icon: cmd.icon, hasArgs: typeof cmd.script === 'function' };
    }
    res.json({ commands: cmds, services: nodeConfig.services || [] });
});

app.listen(PORT, '0.0.0.0', () => {
    console.log('RepublicAI Dashboard: http://localhost:' + PORT);
    console.log('Node: ' + (nodeConfig.node?.moniker || '?') + ' | RPC port: ' + (nodeConfig.ports?.rpc || '?'));
});

