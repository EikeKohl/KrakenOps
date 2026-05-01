-- 002_orchestration — tickets mirror + agent mappings + agent run history.
-- See docs/adr/0002-orchestration-and-kanban.md.

CREATE TABLE tickets (
    id              TEXT    PRIMARY KEY,             -- GitHub ProjectV2Item node ID
    title           TEXT    NOT NULL,
    status          TEXT    NOT NULL,                -- "Todo" | "In Progress" | "Needs Human Review" | "Done" | <other>
    url             TEXT,
    agent           TEXT,                            -- agent name currently assigned (NULL if unassigned)
    updated_at_s    INTEGER NOT NULL,
    last_seen_at_s  INTEGER NOT NULL                 -- last poll observation; staleness detected via gap
) STRICT;

CREATE INDEX idx_tickets_status     ON tickets(status);
CREATE INDEX idx_tickets_last_seen  ON tickets(last_seen_at_s DESC);

CREATE TABLE agent_mappings (
    name          TEXT    PRIMARY KEY,
    script_path   TEXT    NOT NULL,
    match_label   TEXT,                              -- NULL = catch-all
    args_json     TEXT    NOT NULL DEFAULT '[]',
    env_json      TEXT    NOT NULL DEFAULT '{}'
) STRICT;

CREATE TABLE agent_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id       TEXT    NOT NULL,
    agent_name      TEXT    NOT NULL,
    pid             INTEGER,
    started_at_s    INTEGER NOT NULL,
    ended_at_s      INTEGER,
    status          TEXT    NOT NULL,                -- "running" | "succeeded" | "needs_human_review" | "failed"
    exit_code       INTEGER,
    stderr_tail     TEXT
) STRICT;

CREATE INDEX idx_agent_runs_status   ON agent_runs(status);
CREATE INDEX idx_agent_runs_ticket   ON agent_runs(ticket_id);
CREATE INDEX idx_agent_runs_started  ON agent_runs(started_at_s DESC);
