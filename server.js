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

// Run a bash command directly (we're inside WSL already!)
function runBash(script) {
    return spawn('bash', ['-c', script], {
        env: {
            ...process.env,
            TERM: 'dumb',
            PATH: '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/root/go/bin',
            ...configEnv()
        }
    });
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

// SSE endpoint — streams command output in real-time
app.get('/api/run', (req, res) => {
    const cmdId = req.query.cmd;
    const args = (req.query.args || '').trim();
    const command = COMMANDS[cmdId];
    if (!command) return res.status(400).json({ error: 'Unknown command: ' + cmdId });

    let script;
    if (command.file) {
        const argStr = args ? ' ' + args : '';
        script = 'bash ' + path.join(SCRIPTS_DIR, command.file) + argStr;
    } else if (typeof command.script === 'function') {
        script = command.script(args);
    } else {
        script = command.script;
    }

    res.writeHead(200, {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        Connection: 'keep-alive',
    });

    const proc = runBash(script);
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

// === Status ===
reg('status', 'Node Status', 'status', '🟢', { file: 'status.sh' });
reg('services', 'Services Status', 'status', '⚙️', { file: 'services.sh' });
reg('delegations', 'Delegations', 'status', '🤝', { file: 'delegations.sh' });
reg('validators', 'All Validators', 'status', '📊', { file: 'validators.sh' });
reg('peers', 'Connected Peers', 'status', '🌐', { file: 'peers.sh' });

// === Jobs (use $NODE_RPC from env) ===
reg('list-jobs', 'List My Jobs', 'jobs', '📋', { file: 'list-jobs.sh' });
reg('query-job', 'Query Job', 'jobs', '🔍', function (id) {
    return 'republicd query computevalidation job ' + id + ' --node $NODE_RPC -o json 2>/dev/null | jq .';
});
reg('submit-self', 'Submit + Compute (Self)', 'jobs', '📤', { file: 'compute-job.sh' });
reg('compute-job', 'Compute Job', 'jobs', '🖥️', function (id) {
    return 'bash ' + path.join(SCRIPTS_DIR, 'compute-job.sh') + ' ' + id;
});
reg('find-tx', 'Find TX', 'jobs', '🔎', function (txOrId) {
    return 'republicd query tx ' + txOrId + ' --node $NODE_RPC -o json 2>/dev/null | jq .';
});

// === Service Control ===
reg('svc-start', 'Start', 'services', '▶️', function (s) { return 'systemctl start ' + s + ' && echo "Started ' + s + '" && systemctl is-active ' + s; });
reg('svc-stop', 'Stop', 'services', '⏹️', function (s) { return 'systemctl stop ' + s + ' && echo "Stopped ' + s + '"'; });
reg('svc-restart', 'Restart', 'services', '🔄', function (s) { return 'systemctl restart ' + s + ' && echo "Restarted ' + s + '" && systemctl is-active ' + s; });
reg('svc-logs', 'Logs', 'services', '📜', function (s) { return 'journalctl -u ' + s + ' --no-pager -n 100'; });

// === Quick ===
reg('ctl-status', 'Full CTL Status', 'quick', '📊', { file: 'republic-ctl.sh' });
reg('verify-info', 'Verification Info', 'quick', '📋', { file: 'verify-info.sh' });
reg('docker-images', 'Docker Images', 'quick', '🐳', 'docker images --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}\t{{.CreatedAt}}"');
reg('detect-config', 'Re-detect Config', 'quick', '🔧', 'python3 /root/dashboard/detect-config.py --output /root/dashboard/config.json');

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

