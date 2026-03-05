# RepublicAI Dashboard

Lightweight web dashboard for managing a RepublicAI validator + GPU compute node.  
Runs **inside WSL** for direct access to `republicd`, `docker`, `systemctl`.

![Node.js](https://img.shields.io/badge/Node.js-22-green) ![Express](https://img.shields.io/badge/Express-4-blue) ![License](https://img.shields.io/badge/License-MIT-yellow)

## Features

| Category | Actions |
|----------|---------|
| **Status** | Node health, services, delegations, validators, peers |
| **Jobs** | List jobs, query by ID, submit+compute, find TX hash |
| **Services** | Start / Stop / Restart / Logs for any systemd service |
| **Quick Actions** | Full CTL status, verification info, docker images |
| **Custom** | Run any bash command directly |

- ⚡ **Real-time output** via Server-Sent Events (SSE)
- 🖥️ **Health bar** auto-refreshes on load (block height, sync, peers, balance)
- 🔧 **Zero build step** — vanilla HTML/CSS/JS frontend

## Quick Start

```bash
# Inside WSL (Ubuntu)
cd /root/dashboard
npm install
node server.js
# → http://localhost:3847
```

## Install as systemd service

```bash
cp republic-dashboard.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now republic-dashboard
```

## Architecture

```
/root/dashboard/
├── server.js          # Express server (SSE + command registry)
├── public/
│   ├── index.html     # Dashboard UI
│   ├── style.css      # Dark theme
│   └── app.js         # Client-side SSE + health bar
└── scripts/           # Bash scripts executed by the server
    ├── status.sh      # Node health + JSON for header
    ├── services.sh    # Systemd + Docker status
    ├── delegations.sh # Staking delegations
    ├── validators.sh  # All validators ranked
    ├── peers.sh       # Connected peers
    ├── list-jobs.sh   # My compute jobs
    ├── compute-job.sh # Full pipeline: submit → inference → result
    ├── republic-ctl.sh# Service control (start/stop/restart)
    └── verify-info.sh # GPU verification form data
```

## Configuration

Edit the top of `server.js` to change the port:
```js
const PORT = 3847;
```

Scripts in `scripts/` can be edited independently — the server just calls `bash <script>`.

## License

MIT
