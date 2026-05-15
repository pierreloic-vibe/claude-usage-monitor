# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Query helper for usage.db. Usage: uv run stats.py [today|week|month|tools|models|sessions|prompts|raw <sql>]"""

import json
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).parent / "usage.db"


def q(sql, *params):
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return list(con.execute(sql, params))


def fmt_table(rows, cols):
    if not rows:
        print("(no data)")
        return
    widths = [max(len(str(c)), max(len(str(r[c])) for r in rows)) for c in cols]
    print("  ".join(c.ljust(w) for c, w in zip(cols, widths)))
    print("  ".join("-" * w for w in widths))
    for r in rows:
        print("  ".join(str(r[c]).ljust(w) for c, w in zip(cols, widths)))


def summary(since_sql):
    print(f"\n=== usage since {since_sql} ===")
    cost = q(
        f"SELECT ROUND(SUM(value),4) AS cost_usd FROM metrics "
        f"WHERE name='claude_code.cost.usage' AND ts >= {since_sql}"
    )
    print(f"cost:  ${cost[0]['cost_usd'] or 0}")

    tok = q(
        f"SELECT json_extract(attrs,'$.type') AS kind, "
        f"json_extract(attrs,'$.model') AS model, "
        f"SUM(value) AS tokens FROM metrics "
        f"WHERE name='claude_code.token.usage' AND ts >= {since_sql} "
        f"GROUP BY kind, model ORDER BY tokens DESC"
    )
    print("\ntokens by type/model:")
    fmt_table(tok, ["kind", "model", "tokens"])

    sess = q(
        f"SELECT COUNT(*) AS n FROM metrics "
        f"WHERE name='claude_code.session.count' AND ts >= {since_sql}"
    )
    loc = q(
        f"SELECT json_extract(attrs,'$.type') AS kind, SUM(value) AS lines FROM metrics "
        f"WHERE name='claude_code.lines_of_code.count' AND ts >= {since_sql} GROUP BY kind"
    )
    active = q(
        f"SELECT ROUND(SUM(value)/60,1) AS minutes FROM metrics "
        f"WHERE name='claude_code.active_time.total' AND ts >= {since_sql}"
    )
    print(f"\nsessions started: {sess[0]['n']}")
    print(f"active time:      {active[0]['minutes'] or 0} min")
    fmt_table(loc, ["kind", "lines"])


def tools():
    rows = q(
        "SELECT json_extract(attrs,'$.name') AS tool, "
        "COUNT(*) AS calls, "
        "SUM(CASE WHEN json_extract(attrs,'$.success')='true' OR json_extract(attrs,'$.success')=1 THEN 1 ELSE 0 END) AS ok "
        "FROM events WHERE name='tool_result' "
        "GROUP BY tool ORDER BY calls DESC"
    )
    fmt_table(rows, ["tool", "calls", "ok"])


def models():
    rows = q(
        "SELECT json_extract(attrs,'$.model') AS model, "
        "COUNT(*) AS requests, "
        "SUM(CAST(json_extract(attrs,'$.input_tokens') AS INTEGER)) AS in_tok, "
        "SUM(CAST(json_extract(attrs,'$.output_tokens') AS INTEGER)) AS out_tok, "
        "SUM(CAST(json_extract(attrs,'$.cache_read_tokens') AS INTEGER)) AS cache_read, "
        "ROUND(SUM(CAST(json_extract(attrs,'$.cost_usd') AS REAL)),4) AS cost "
        "FROM events WHERE name='api_request' GROUP BY model ORDER BY cost DESC"
    )
    fmt_table(rows, ["model", "requests", "in_tok", "out_tok", "cache_read", "cost"])


def sessions():
    rows = q(
        "SELECT json_extract(attrs,'$.session.id') AS session, "
        "MIN(ts) AS started, MAX(ts) AS last, COUNT(*) AS events "
        "FROM events GROUP BY session ORDER BY last DESC LIMIT 20"
    )
    fmt_table(rows, ["session", "started", "last", "events"])


def prompts():
    rows = q(
        "SELECT datetime(ts,'unixepoch','localtime') AS at, "
        "substr(COALESCE(json_extract(attrs,'$.prompt'), body),1,120) AS prompt "
        "FROM events WHERE name='user_prompt' ORDER BY ts DESC LIMIT 30"
    )
    fmt_table(rows, ["at", "prompt"])


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "today"
    if cmd == "today":
        summary("strftime('%s','now','start of day')")
    elif cmd == "week":
        summary("strftime('%s','now','-7 days')")
    elif cmd == "month":
        summary("strftime('%s','now','-30 days')")
    elif cmd == "tools":
        tools()
    elif cmd == "models":
        models()
    elif cmd == "sessions":
        sessions()
    elif cmd == "prompts":
        prompts()
    elif cmd == "raw":
        rows = q(sys.argv[2])
        if rows:
            cols = rows[0].keys()
            fmt_table(rows, cols)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
