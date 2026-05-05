-- 004_workstreams — projects table, tickets.project_id, workstreams table.
-- See docs/adr/0006-workstream-model-and-multi-project.md.

CREATE TABLE projects (
    id              TEXT    PRIMARY KEY,
    title           TEXT    NOT NULL,
    owner_login     TEXT    NOT NULL,
    last_seen_at_s  INTEGER NOT NULL
) STRICT;

ALTER TABLE tickets ADD COLUMN project_id TEXT REFERENCES projects(id);

CREATE INDEX idx_tickets_project ON tickets(project_id);

CREATE TABLE workstreams (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    source             TEXT    NOT NULL,
    external_id        TEXT,
    label              TEXT,
    ticket_id          TEXT REFERENCES tickets(id),
    project_id         TEXT REFERENCES projects(id),
    bind_method        TEXT,
    started_at_s       INTEGER NOT NULL,
    last_seen_at_s     INTEGER NOT NULL,
    ended_at_s         INTEGER,
    todos_json         TEXT NOT NULL DEFAULT '[]',
    todos_updated_at_s INTEGER
) STRICT;

CREATE UNIQUE INDEX ux_workstreams_ext   ON workstreams(source, external_id);

CREATE INDEX idx_workstreams_ticket    ON workstreams(ticket_id);

CREATE INDEX idx_workstreams_last_seen ON workstreams(last_seen_at_s DESC);
