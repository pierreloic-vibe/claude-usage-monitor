# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "opentelemetry-proto>=1.27",
#   "protobuf>=4.25",
# ]
# ///
"""Local OTLP/HTTP receiver for Claude Code telemetry. See README.md."""

import gzip
import json
import sqlite3
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from opentelemetry.proto.collector.logs.v1 import logs_service_pb2
from opentelemetry.proto.collector.metrics.v1 import metrics_service_pb2
from opentelemetry.proto.collector.trace.v1 import trace_service_pb2

DB_PATH = Path(__file__).parent / "usage.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS metrics (
    ts INTEGER NOT NULL,
    name TEXT NOT NULL,
    value REAL NOT NULL,
    attrs TEXT NOT NULL,
    resource TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_metrics_ts ON metrics(ts);
CREATE INDEX IF NOT EXISTS idx_metrics_name ON metrics(name);

CREATE TABLE IF NOT EXISTS events (
    ts INTEGER NOT NULL,
    name TEXT NOT NULL,
    body TEXT NOT NULL,
    attrs TEXT NOT NULL,
    resource TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_name ON events(name);

CREATE TABLE IF NOT EXISTS spans (
    ts INTEGER NOT NULL,
    duration_ms REAL NOT NULL,
    name TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    span_id TEXT NOT NULL,
    parent_span_id TEXT,
    attrs TEXT NOT NULL,
    resource TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_spans_ts ON spans(ts);
CREATE INDEX IF NOT EXISTS idx_spans_trace ON spans(trace_id);
"""


def init_db():
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)
    con.commit()
    return con


def kv_to_dict(kv_list):
    out = {}
    for kv in kv_list:
        v = kv.value
        if v.HasField("string_value"):
            out[kv.key] = v.string_value
        elif v.HasField("bool_value"):
            out[kv.key] = v.bool_value
        elif v.HasField("int_value"):
            out[kv.key] = v.int_value
        elif v.HasField("double_value"):
            out[kv.key] = v.double_value
        elif v.HasField("array_value"):
            out[kv.key] = [
                a.string_value or a.int_value or a.double_value or a.bool_value
                for a in v.array_value.values
            ]
        else:
            out[kv.key] = str(v)
    return out


def any_value(v):
    if v.HasField("string_value"):
        return v.string_value
    if v.HasField("bool_value"):
        return v.bool_value
    if v.HasField("int_value"):
        return v.int_value
    if v.HasField("double_value"):
        return v.double_value
    if v.HasField("kvlist_value"):
        return kv_to_dict(v.kvlist_value.values)
    if v.HasField("array_value"):
        return [any_value(a) for a in v.array_value.values]
    return None


def handle_metrics(con, req):
    rows = []
    for rm in req.resource_metrics:
        resource = json.dumps(kv_to_dict(rm.resource.attributes))
        for sm in rm.scope_metrics:
            for m in sm.metrics:
                name = m.name
                points = []
                if m.HasField("sum"):
                    points = m.sum.data_points
                elif m.HasField("gauge"):
                    points = m.gauge.data_points
                elif m.HasField("histogram"):
                    for dp in m.histogram.data_points:
                        ts = int(dp.time_unix_nano // 1_000_000_000)
                        attrs = json.dumps(kv_to_dict(dp.attributes))
                        rows.append((ts, name, dp.sum, attrs, resource))
                    continue
                for dp in points:
                    ts = int(dp.time_unix_nano // 1_000_000_000)
                    val = dp.as_double if dp.HasField("as_double") else dp.as_int
                    attrs = json.dumps(kv_to_dict(dp.attributes))
                    rows.append((ts, name, float(val), attrs, resource))
    if rows:
        con.executemany("INSERT INTO metrics VALUES (?,?,?,?,?)", rows)
        con.commit()
    return len(rows)


def handle_logs(con, req):
    rows = []
    for rl in req.resource_logs:
        resource = json.dumps(kv_to_dict(rl.resource.attributes))
        for sl in rl.scope_logs:
            for lr in sl.log_records:
                ts = int(lr.time_unix_nano // 1_000_000_000) or int(time.time())
                attrs = kv_to_dict(lr.attributes)
                name = attrs.get("event.name") or lr.event_name or ""
                body = any_value(lr.body)
                rows.append(
                    (
                        ts,
                        name,
                        json.dumps(body) if not isinstance(body, str) else body,
                        json.dumps(attrs),
                        resource,
                    )
                )
    if rows:
        con.executemany("INSERT INTO events VALUES (?,?,?,?,?)", rows)
        con.commit()
    return len(rows)


def handle_traces(con, req):
    rows = []
    for rs in req.resource_spans:
        resource = json.dumps(kv_to_dict(rs.resource.attributes))
        for ss in rs.scope_spans:
            for sp in ss.spans:
                ts = int(sp.start_time_unix_nano // 1_000_000_000)
                dur_ms = (sp.end_time_unix_nano - sp.start_time_unix_nano) / 1_000_000
                rows.append(
                    (
                        ts,
                        dur_ms,
                        sp.name,
                        sp.trace_id.hex(),
                        sp.span_id.hex(),
                        sp.parent_span_id.hex() or None,
                        json.dumps(kv_to_dict(sp.attributes)),
                        resource,
                    )
                )
    if rows:
        con.executemany("INSERT INTO spans VALUES (?,?,?,?,?,?,?,?)", rows)
        con.commit()
    return len(rows)


class Handler(BaseHTTPRequestHandler):
    con = None

    def log_message(self, fmt, *args):
        pass  # silence default access log

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        if self.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        try:
            if self.path == "/v1/metrics":
                req = metrics_service_pb2.ExportMetricsServiceRequest()
                req.ParseFromString(raw)
                n = handle_metrics(self.con, req)
                resp = metrics_service_pb2.ExportMetricsServiceResponse()
            elif self.path == "/v1/logs":
                req = logs_service_pb2.ExportLogsServiceRequest()
                req.ParseFromString(raw)
                n = handle_logs(self.con, req)
                resp = logs_service_pb2.ExportLogsServiceResponse()
            elif self.path == "/v1/traces":
                req = trace_service_pb2.ExportTraceServiceRequest()
                req.ParseFromString(raw)
                n = handle_traces(self.con, req)
                resp = trace_service_pb2.ExportTraceServiceResponse()
            else:
                self.send_error(404)
                return
            print(f"[{time.strftime('%H:%M:%S')}] {self.path} -> {n} rows", flush=True)
            payload = resp.SerializeToString()
            self.send_response(200)
            self.send_header("Content-Type", "application/x-protobuf")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except Exception as e:
            print(f"error {self.path}: {e}", file=sys.stderr, flush=True)
            self.send_error(500, str(e))


def main():
    con = init_db()
    Handler.con = con
    # sqlite3 connections are thread-safe enough for serialized writes in CPython
    # but ThreadingHTTPServer may interleave; allow shared use.
    con.execute("PRAGMA journal_mode=WAL")
    Handler.con = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
    Handler.con.execute("PRAGMA journal_mode=WAL")
    srv = ThreadingHTTPServer(("127.0.0.1", 4318), Handler)
    print(f"OTLP/HTTP receiver listening on http://127.0.0.1:4318  db={DB_PATH}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
