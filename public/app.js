// RepublicAI Dashboard — Client JS
const outputEl = document.getElementById('output');
const spinnerEl = document.getElementById('output-spinner');
const titleEl = document.getElementById('output-title');
let currentSource = null;

// Strip ANSI codes for clean display
function stripAnsi(text) {
    return text.replace(/\x1b\[[0-9;]*m/g, '');
}

function appendOutput(text, cssClass) {
    const cleaned = stripAnsi(text);
    const span = document.createElement('span');
    if (cssClass) span.className = cssClass;
    span.textContent = cleaned;
    outputEl.appendChild(span);
    outputEl.scrollTop = outputEl.scrollHeight;
}

function clearOutput() {
    outputEl.textContent = '';
}

function copyLog() {
    const text = outputEl.textContent || '';
    navigator.clipboard.writeText(text).then(() => {
        const btn = document.getElementById('copy-log-btn');
        btn.textContent = '✅ Copied!';
        setTimeout(() => { btn.textContent = 'Copy'; }, 1500);
    });
}

let lastQueriedJobId = '';
let appendMode = false;

function computeQueriedJob() {
    if (lastQueriedJobId) {
        appendMode = true;
        runCommand('compute-job', lastQueriedJobId);
    }
}

function setRunning(label) {
    titleEl.textContent = label;
    spinnerEl.classList.remove('hidden');
}

let lastCmdId = '';

function setDone(code) {
    spinnerEl.classList.add('hidden');
    const status = code === 0 ? '✅ Done' : `❌ Exit: ${code}`;
    titleEl.textContent += ` — ${status}`;
    // Show share button only after peers command succeeds
    const shareBtn = document.getElementById('share-peers-btn');
    if (lastCmdId === 'peers' && code === 0) {
        shareBtn.classList.remove('hidden');
    } else {
        shareBtn.classList.add('hidden');
    }
    // Show compute button after query-job with a numeric Job ID
    const computeBtn = document.getElementById('compute-queried-btn');
    const jobInput = document.getElementById('job-id-input');
    if (lastCmdId === 'query-job' && code === 0 && jobInput) {
        const val = jobInput.value.trim();
        if (/^[0-9]+$/.test(val)) {
            lastQueriedJobId = val;
            computeBtn.classList.remove('hidden');
        } else {
            computeBtn.classList.add('hidden');
        }
    } else if (lastCmdId !== 'compute-job') {
        computeBtn.classList.add('hidden');
    }
}

function runCommand(cmdId, args = '') {
    if (currentSource) {
        currentSource.close();
        currentSource = null;
    }

    if (appendMode) {
        appendOutput('\n' + '='.repeat(60) + '\n', 'ansi-dim');
        appendMode = false;
    } else {
        clearOutput();
    }
    lastCmdId = cmdId;
    // Hide compute button when starting new command (except compute-job itself)
    if (cmdId !== 'compute-job') {
        document.getElementById('compute-queried-btn').classList.add('hidden');
    }
    const label = cmdId + (args ? ` (${args})` : '');
    setRunning(label);

    const url = `/api/run?cmd=${encodeURIComponent(cmdId)}&args=${encodeURIComponent(args)}`;
    const es = new EventSource(url);
    currentSource = es;

    es.onmessage = (e) => {
        try {
            const data = JSON.parse(e.data);
            if (data.type === 'stdout') {
                appendOutput(data.text);
            } else if (data.type === 'stderr') {
                appendOutput(data.text, 'ansi-dim');
            } else if (data.type === 'done') {
                setDone(data.code);
                es.close();
                currentSource = null;
                // If it's the status command, parse health bar
                if (cmdId === 'status') parseHealthBar(data.output);
            } else if (data.type === 'error') {
                appendOutput(`ERROR: ${data.text}\n`, 'ansi-red');
                es.close();
                currentSource = null;
            }
        } catch (err) {
            appendOutput(e.data + '\n');
        }
    };

    es.onerror = () => {
        setDone(-1);
        es.close();
        currentSource = null;
    };
}

// Parse health bar from status command JSON output
function parseHealthBar(output) {
    try {
        const jsonStart = output.indexOf('JSON_START');
        if (jsonStart === -1) return;
        const jsonStr = output.substring(jsonStart + 10).trim();
        const d = JSON.parse(jsonStr);

        const blockEl = document.getElementById('block-height');
        const syncEl = document.getElementById('sync-status');
        const peerEl = document.getElementById('peer-count');
        const valEl = document.getElementById('val-status');
        const balEl = document.getElementById('balance-display');

        blockEl.textContent = `Block: ${d.block}`;
        blockEl.className = 'badge ok';

        syncEl.textContent = d.syncing ? 'Syncing ⏳' : 'Synced ✅';
        syncEl.className = d.syncing ? 'badge warn' : 'badge ok';

        peerEl.textContent = `Peers: ${d.peers}`;
        peerEl.className = parseInt(d.peers) > 3 ? 'badge ok' : 'badge warn';

        const isBonded = d.status.includes('BONDED');
        valEl.textContent = isBonded ? '🟢 Bonded' : d.status.replace('BOND_STATUS_', '');
        valEl.className = isBonded ? 'badge ok' : 'badge err';

        const rai = (parseInt(d.balance || '0') / 1e18).toFixed(2);
        const staked = (parseInt(d.tokens || '0') / 1e18).toFixed(2);
        balEl.textContent = `💰 ${rai} / ${staked} RAI`;
        balEl.className = 'badge ok';
    } catch (e) {
        // Silently fail — health bar just won't update
    }
}

// Wire up buttons
document.querySelectorAll('[data-cmd]').forEach(btn => {
    btn.addEventListener('click', () => {
        const cmd = btn.dataset.cmd;
        let args = '';

        if (btn.dataset.argsFrom) {
            const el = document.getElementById(btn.dataset.argsFrom);
            args = el ? el.value.trim() : '';
        }

        // For dangerous commands, confirm
        if (cmd === 'submit-self') {
            if (!confirm('Submit a new job to your own validator?\nThis will run GPU inference and cost gas.')) return;
        }
        if (cmd === 'custom' && args) {
            if (!confirm(`Run custom command?\n\n${args}`)) return;
        }

        runCommand(cmd, args);
    });
});

// Enter key on input fields
document.querySelectorAll('.input-row input').forEach(input => {
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            const btn = input.parentElement.querySelector('button[data-cmd]');
            if (btn) btn.click();
        }
    });
});

// Auto-refresh status on load
setTimeout(() => runCommand('status'), 500);

// ── Share Peers Modal ────────────────────────────
function openSharePeers() {
    const modal = document.getElementById('share-modal');
    const cmdEl = document.getElementById('share-command');
    cmdEl.textContent = '⏳ Loading peers...';
    modal.classList.remove('hidden');

    // Fetch share-peers command
    const es = new EventSource('/api/run?cmd=share-peers');
    let output = '';
    es.onmessage = (e) => {
        try {
            const data = JSON.parse(e.data);
            if (data.type === 'stdout' || data.type === 'stderr') {
                output += data.text;
            } else if (data.type === 'done') {
                es.close();
                // Extract just the command lines
                const lines = output.split('\n');
                const cmdLines = [];
                let capture = false;
                for (const line of lines) {
                    if (line.startsWith('NEW_PEERS=')) capture = true;
                    if (capture) cmdLines.push(line);
                    if (line.startsWith('echo "Done')) { capture = false; }
                }
                cmdEl.textContent = cmdLines.join('\n').trim() || output;
            }
        } catch (err) { /* ignore */ }
    };
    es.onerror = () => { es.close(); cmdEl.textContent = 'Error loading peers'; };
}

function copyShareCommand() {
    const text = document.getElementById('share-command').textContent;
    navigator.clipboard.writeText(text).then(() => {
        const btn = document.querySelector('.copy-btn');
        btn.textContent = '✅ Copied!';
        setTimeout(() => { btn.textContent = '📋 Copy'; }, 2000);
    });
}

function closeShareModal() {
    document.getElementById('share-modal').classList.add('hidden');
}

// ── Latest Blocks Timeline ──
const blocksEl = document.getElementById('blocks-timeline');
let knownHeights = new Set();

function timeAgo(isoStr) {
    const diff = Math.floor((Date.now() - new Date(isoStr).getTime()) / 1000);
    if (diff < 5) return 'just now';
    if (diff < 60) return diff + 's ago';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    return Math.floor(diff / 3600) + 'h ago';
}

function renderBlocks(blocks) {
    if (!blocksEl || !blocks.length) return;
    blocks.forEach(b => {
        const existing = document.getElementById('blk-' + b.height);
        if (existing) {
            existing.querySelector('.blk-time').textContent = timeAgo(b.time);
            return;
        }
        const el = document.createElement('div');
        el.className = 'block-entry' + (knownHeights.size > 0 ? ' block-new' : '');
        el.id = 'blk-' + b.height;
        el.innerHTML =
            '<span class="blk-height">#' + b.height + '</span>' +
            '<span class="blk-hash">' + b.hash.substring(0, 10) + '…</span>' +
            (b.num_txs > 0 ? '<span class="blk-txs">' + b.num_txs + 'tx</span>' : '') +
            '<span class="blk-time">' + timeAgo(b.time) + '</span>';
        const firstChild = blocksEl.firstChild;
        if (firstChild) blocksEl.insertBefore(el, firstChild);
        else blocksEl.appendChild(el);
        knownHeights.add(b.height);
    });
    while (blocksEl.children.length > 20) blocksEl.removeChild(blocksEl.lastChild);
}

async function fetchBlocks() {
    try {
        const resp = await fetch('/api/blocks');
        if (!resp.ok) return;
        const blocks = await resp.json();
        const newBlocks = blocks.filter(b => !document.getElementById('blk-' + b.height)).reverse();
        if (newBlocks.length > 0) renderBlocks(newBlocks);
        blocks.forEach(b => {
            const el = document.getElementById('blk-' + b.height);
            if (el) el.querySelector('.blk-time').textContent = timeAgo(b.time);
        });
    } catch (e) { /* silent */ }
}

setTimeout(fetchBlocks, 1000);
setInterval(fetchBlocks, 5000);
