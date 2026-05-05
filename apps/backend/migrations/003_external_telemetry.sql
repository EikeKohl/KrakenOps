-- 003_external_telemetry — external OTel ingest (metrics + logs/events) and
-- discovered-process snapshots from the per-process psutil sampler.
-- See docs/adr/0005-external-otel-and-process-discovery.md.

CREATE TABLE IF NOT EXISTS external_metrics (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    service_name    TEXT NOT NULL,
    metric_name     TEXT NOT NULL,
    value           REAL NOT NULL,
    unit            TEXT,
    attributes_json TEXT NOT NULL DEFAULT '{}',
    ts_ns           INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_external_metrics_service_ts
    ON external_metrics(service_name, ts_ns DESC);

CREATE TABLE IF NOT EXISTS external_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    service_name    TEXT NOT NULL,
    event_name      TEXT NOT NULL,
    prompt_id       TEXT,
    session_id      TEXT,
    attributes_json TEXT NOT NULL DEFAULT '{}',
    observed_at_ns  INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_external_events_service_ts
    ON external_events(service_name, observed_at_ns DESC);

CREATE INDEX IF NOT EXISTS ix_external_events_prompt
    ON external_events(prompt_id) WHERE prompt_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS discovered_processes (
    pid           INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    cmdline       TEXT NOT NULL,
    last_cpu_pct  REAL NOT NULL DEFAULT 0,
    last_rss_mb   REAL NOT NULL DEFAULT 0,
    first_seen_ns INTEGER NOT NULL,
    last_seen_ns  INTEGER NOT NULL
);
