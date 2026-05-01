-- 001_initial — Foundational schema for ingest + cost computation.
-- See docs/adr/0001-tentacle-span-schema.md for the wire-format contract.

CREATE TABLE traces (
    trace_id          TEXT    PRIMARY KEY,             -- 32-char hex
    service_name      TEXT    NOT NULL,
    started_at_ns     INTEGER NOT NULL,                -- unix nano of earliest span
    ended_at_ns       INTEGER,                         -- unix nano of latest span (NULL while in-flight)
    span_count        INTEGER NOT NULL DEFAULT 0,
    has_human_review  INTEGER NOT NULL DEFAULT 0       -- bool: any span with tentacle.needs_human_review
) STRICT;

CREATE INDEX idx_traces_started_at ON traces(started_at_ns DESC);
CREATE INDEX idx_traces_service    ON traces(service_name);

CREATE TABLE spans (
    span_id              TEXT    PRIMARY KEY,          -- 16-char hex
    trace_id             TEXT    NOT NULL,
    parent_span_id       TEXT,                         -- NULL for trace root
    name                 TEXT    NOT NULL,
    otel_kind            TEXT    NOT NULL,             -- INTERNAL/CLIENT/SERVER/...
    tentacle_kind        TEXT,                         -- agent | tool | human_review | NULL
    start_time_ns        INTEGER NOT NULL,
    end_time_ns          INTEGER NOT NULL,
    status_code          TEXT    NOT NULL,             -- UNSET | OK | ERROR
    status_message       TEXT,
    attributes_json      TEXT    NOT NULL,             -- full attribute map for fidelity
    events_json          TEXT    NOT NULL,             -- list of {name, time_ns, attributes}
    needs_human_review   INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (trace_id) REFERENCES traces(trace_id) ON DELETE CASCADE
) STRICT;

CREATE INDEX idx_spans_trace_id     ON spans(trace_id);
CREATE INDEX idx_spans_parent       ON spans(parent_span_id);
CREATE INDEX idx_spans_tentacle     ON spans(tentacle_kind);
CREATE INDEX idx_spans_start        ON spans(start_time_ns DESC);
CREATE INDEX idx_spans_human_review ON spans(needs_human_review) WHERE needs_human_review = 1;

CREATE TABLE token_usage (
    span_id        TEXT    PRIMARY KEY,                -- one usage row per LLM span
    trace_id       TEXT    NOT NULL,
    gen_ai_system  TEXT,                               -- "openai" | "anthropic" | ...
    model          TEXT    NOT NULL,
    input_tokens   INTEGER NOT NULL,
    output_tokens  INTEGER NOT NULL,
    cost_usd       REAL,                               -- NULL if model not in pricing table
    FOREIGN KEY (span_id)  REFERENCES spans(span_id)  ON DELETE CASCADE,
    FOREIGN KEY (trace_id) REFERENCES traces(trace_id) ON DELETE CASCADE
) STRICT;

CREATE INDEX idx_token_usage_trace ON token_usage(trace_id);
CREATE INDEX idx_token_usage_model ON token_usage(model);

CREATE TABLE model_pricing (
    model              TEXT PRIMARY KEY,
    input_per_1k_usd   REAL NOT NULL,
    output_per_1k_usd  REAL NOT NULL,
    source             TEXT NOT NULL,                  -- e.g. "default-2026-05" | "user-override"
    updated_at_s       INTEGER NOT NULL                -- unix epoch seconds
) STRICT;
