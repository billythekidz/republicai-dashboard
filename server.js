const express = require('express');
const { spawn } = require('child_process');
const path = require('path');
const app = express();
const PORT = 3847;

app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

const SCRIPTS_DIR = path.join(__dirname, 'scripts');

// Run a bash command directly (we're inside WSL already!)
function runBash(script) {
    return spawn('bash', ['-c', script], {
        env: { ...process.env, TERM: 'dumb', PATH: '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/root/go/bin' }
    });
}

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

// === Jobs ===
reg('list-jobs', 'List My Jobs', 'jobs', '📋', { file: 'list-jobs.sh' });
reg('query-job', 'Query Job', 'jobs', '🔍', function (id) {
    return 'republicd query computevalidation job ' + id + ' --node tcp://localhost:26657 -o json 2>/dev/null | jq .';
});
reg('submit-self', 'Submit + Compute (Self)', 'jobs', '📤', { file: 'compute-job.sh' });
reg('compute-job', 'Compute Job', 'jobs', '🖥️', function (id) {
    return 'bash ' + path.join(SCRIPTS_DIR, 'compute-job.sh') + ' ' + id;
});
reg('find-tx', 'Find TX', 'jobs', '🔎', function (txOrId) {
    return 'republicd query tx ' + txOrId + ' --node tcp://localhost:26657 -o json 2>/dev/null | jq .';
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

// ctl-status needs to pass 'status' arg
COMMANDS['ctl-status'].file = 'republic-ctl.sh';
COMMANDS['ctl-status'].script = undefined;

// === Custom ===
reg('custom', 'Custom', 'custom', '⌨️', function (cmd) { return cmd; });

// Command list endpoint
app.get('/api/commands', (req, res) => {
    const cmds = {};
    for (const [id, cmd] of Object.entries(COMMANDS)) {
        cmds[id] = { label: cmd.label, group: cmd.group, icon: cmd.icon, hasArgs: typeof cmd.script === 'function' };
    }
    res.json(cmds);
});

app.listen(PORT, '0.0.0.0', () => {
    console.log('RepublicAI Dashboard: http://localhost:' + PORT);
    console.log('Running inside WSL — direct access to republicd, docker, systemctl');
});
