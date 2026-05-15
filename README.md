# claude-usage-monitor

Local monitoring for [Claude Code](https://code.claude.com/) usage.

A tiny OTLP/HTTP receiver listens on `localhost:4318`, decodes the OpenTelemetry
payloads Claude Code emits, and stores them in a SQLite file (`usage.db`).
A `stats.py` CLI runs the common queries (today / week / models / tools / sessions).

```
claude CLI ──OTLP/HTTP protobuf──▶ monitor.py (:4318) ──▶ usage.db ──▶ stats.py
```

Everything stays on your laptop. The receiver only binds `127.0.0.1` — no outbound network.

## Requirements

- macOS (the auto-start step uses `launchd`; the receiver itself is portable)
- [`uv`](https://docs.astral.sh/uv/) — `brew install uv`

Dependencies (`opentelemetry-proto`, `protobuf`) are declared inline in the
scripts via PEP 723, so `uv run` handles the env automatically.

## Install

### 1. Clone

```bash
git clone https://github.com/<you>/claude-usage-monitor.git
cd claude-usage-monitor
```

### 2. Make Claude Code export to the receiver

Append to `~/.zshrc` (or `~/.bashrc`):

```bash
export CLAUDE_CODE_ENABLE_TELEMETRY=1
export OTEL_METRICS_EXPORTER=otlp
export OTEL_LOGS_EXPORTER=otlp
export OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
export OTEL_METRIC_EXPORT_INTERVAL=10000
export OTEL_LOGS_EXPORT_INTERVAL=5000
export OTEL_LOG_USER_PROMPTS=1   # include prompt text in events; drop if undesired
```

Open a new shell so the variables take effect.

### 3. Run the receiver at every login (macOS LaunchAgent)

`claude-usage-monitor.plist` ships with `__INSTALL_DIR__` placeholders.
Substitute the absolute path of your checkout and install it:

```bash
INSTALL_DIR="$(pwd)"
sed "s|__INSTALL_DIR__|$INSTALL_DIR|g" claude-usage-monitor.plist \
  > ~/Library/LaunchAgents/claude-usage-monitor.plist
launchctl bootstrap "gui/$UID" ~/Library/LaunchAgents/claude-usage-monitor.plist
```

That's it — `monitor.py` is now running, will restart on crash, and boots at login.

Verify:

```bash
launchctl print "gui/$UID/claude-usage-monitor" | head
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:4318/v1/metrics   # → 200
tail -f monitor.log
```

## Daily use

Run `claude` as usual. Usage flows into `usage.db` in this directory.

```bash
uv run stats.py today       # cost, tokens by model/type, sessions, LOC, active min
uv run stats.py week
uv run stats.py month
uv run stats.py models      # per-model requests + cost (from api_request events)
uv run stats.py tools       # tool call counts + success
uv run stats.py sessions    # last 20 sessions
uv run stats.py prompts     # last 30 user prompts (needs OTEL_LOG_USER_PROMPTS=1)
uv run stats.py raw "select name, count(*) from events group by name"
```

`usage.db` is plain SQLite — point Datasette, DBeaver, or `sqlite3` at it for
ad-hoc exploration.

## Manual mode (no LaunchAgent)

Skip step 3 above. In any shell:

```bash
uv run monitor.py     # leave running
```

## Uninstall

```bash
# 1. stop and remove the LaunchAgent
launchctl bootout "gui/$UID/claude-usage-monitor"
rm ~/Library/LaunchAgents/claude-usage-monitor.plist

# 2. remove the export block from ~/.zshrc

# 3. (optional) delete data and the checkout
rm usage.db
```

## What's captured

- **metrics**: `claude_code.cost.usage`, `claude_code.token.usage`,
  `claude_code.session.count`, `claude_code.lines_of_code.count`,
  `claude_code.active_time.total`, `claude_code.commit.count`,
  `claude_code.pull_request.count`, `claude_code.code_edit_tool.decision`
- **events** (OTel logs): `user_prompt`, `api_request`, `api_error`,
  `tool_result`, `tool_decision`, `mcp_server_connection`, `skill_activated`,
  `plugin_loaded`, `at_mention`, `permission_mode_changed`, …
- **spans**: only if you also set `OTEL_TRACES_EXPORTER=otlp` —
  `claude_code.interaction`, `claude_code.llm_request`, `claude_code.tool`, …

Reference: <https://code.claude.com/docs/en/monitoring-usage>

## License

MIT
