# claude-usage-monitor

Local OTLP receiver + SQLite + CLI for monitoring [Claude Code](https://code.claude.com/) usage.

```
claude ──OTLP/HTTP──▶ monitor.py (:4318) ──▶ usage.db ──▶ stats.py
```

Binds `127.0.0.1` only. No data leaves your machine.

## Requires

macOS, [`uv`](https://docs.astral.sh/uv/) (`brew install uv`). Python deps are
declared inline via PEP 723 — `uv run` handles the env.

## Install

Clone the repo and `cd` into it, then:

```bash
# 1. Run the receiver at every login (macOS LaunchAgent)
sed "s|__INSTALL_DIR__|$PWD|g" claude-usage-monitor.plist > ~/Library/LaunchAgents/claude-usage-monitor.plist
launchctl bootstrap "gui/$UID" ~/Library/LaunchAgents/claude-usage-monitor.plist

# 2. Tell Claude Code where to send telemetry — append to ~/.zshrc
cat >> ~/.zshrc <<'EOF'
export CLAUDE_CODE_ENABLE_TELEMETRY=1
export OTEL_METRICS_EXPORTER=otlp
export OTEL_LOGS_EXPORTER=otlp
export OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
export OTEL_METRIC_EXPORT_INTERVAL=10000
export OTEL_LOGS_EXPORT_INTERVAL=5000
export OTEL_LOG_USER_PROMPTS=1   # drop to skip storing prompt text
EOF
```

Open a new shell. Run `claude` as usual — usage flows into `usage.db`.

To run the receiver manually instead of via launchd, skip step 1 and `uv run monitor.py`.

## Query

```bash
uv run stats.py today       # cost, tokens, sessions, LOC, active time
uv run stats.py week | month
uv run stats.py models      # per-model requests + cost
uv run stats.py tools       # tool call counts + success
uv run stats.py sessions
uv run stats.py prompts     # needs OTEL_LOG_USER_PROMPTS=1
uv run stats.py raw "select name, count(*) from events group by name"
```

`usage.db` is plain SQLite — Datasette / DBeaver / `sqlite3` work too.

## Uninstall

```bash
launchctl bootout "gui/$UID/claude-usage-monitor"
rm ~/Library/LaunchAgents/claude-usage-monitor.plist
# then remove the export block from ~/.zshrc
```

## What's captured

OTel metrics (`claude_code.cost.usage`, `claude_code.token.usage`, …), events
(`user_prompt`, `api_request`, `tool_result`, …), and optionally spans (set
`OTEL_TRACES_EXPORTER=otlp`). Full list:
<https://code.claude.com/docs/en/monitoring-usage>.

## License

MIT
