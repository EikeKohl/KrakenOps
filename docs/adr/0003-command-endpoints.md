# ADR 0003: command endpoints (spawn, stop, resume)

- **Status:** Accepted
- **Date:** 2026-05-01
- **Deciders:** @eikekohlmeyer
- **Affects:** backend · dashboard · contract

## Context

PR #7 turned the GitHub poller + orchestrator into a fully reactive system:
move a card to `Todo`, an agent runs. PR #8 needs the **operator-driven**
counterpart — buttons in the dashboard that don't depend on the next poll
firing. CLAUDE.md §5.5 already names three commands; this ADR pins their
shape and side-effects.

## Decision

Three additive REST endpoints. All are POST, all return JSON.

### `POST /v1/tickets/{ticket_id}/spawn`

Manually run the configured agent for a ticket, regardless of its GitHub
status. Useful for: re-running a `Done` ticket, kicking off something that
was paused, testing a freshly-edited agent script.

- **404** — ticket not found in the local mirror.
- **409** — a `running` agent_run already exists for this ticket.
- **400** — no agent mapping matches the ticket's first label.
- **503** — poller dormant (no GitHub config); no client to dispatch through.
- **202** — `{ "run_id": <int> }` accepted; orchestrator is now running
  in the background. Subscribe to `traces`/`kanban` for progress.

### `POST /v1/agents/{run_id}/stop`

Terminate a running agent_run.

- **404** — run not found.
- **409** — run not in `running` state (already finished, or already stopped).
- **200** — `{ "stopped": true }`. Run row updated to `status="stopped"`,
  `exit_code=-15`. The orchestrator's own exit handler will *not* overwrite
  this because `_finish_run` treats `stopped` as sticky.

Termination protocol: SIGTERM first, wait up to 3s, then SIGKILL. The
GitHub status is **untouched** (operator follow-up), same convention as a
generic `failed` outcome (per ADR 0002).

### `POST /v1/tickets/{ticket_id}/resume`

Move a `Needs Human Review` ticket back to `Todo`. The next poll picks it
up and dispatches an agent again.

- **404** — ticket not found.
- **409** — ticket not in `Needs Human Review`.
- **502** — GitHub call failed.
- **200** — `{ "status": "Todo" }`. Local mirror is optimistically updated
  too so the dashboard reflects the change immediately rather than waiting
  for the next poll.

**Note on resume semantics.** v0.4 does *not* pass a structured human
payload to the agent. The contract is: the operator updates whatever the
agent needs (ticket fields, attached comments, file uploads, etc.) *before*
clicking Resume; the next agent run picks up that state freshly. Richer
resume — passing a payload via SDK — is a future ADR.

## Consequences

### Positive
- Dashboard gets first-class actions per ticket without needing webhook /
  long-poll workarounds.
- Stop is sticky: a deliberately-stopped run won't get reclassified as
  `failed` by a race with the orchestrator's own exit handler.

### Negative / accepted risks
- Spawn allows running a stale or already-completed ticket. We rely on the
  duplicate-run guard (`409` if `running`) to prevent the most painful
  footgun; everything else is operator's choice.
- Resume's "no structured payload" limitation is a real UX gap. Documented;
  superseded by a future ADR once the SDK gains a `tentacle.resume()` API.

## Ripple plan

- [x] **Schema doc** — this ADR; new `agent_runs.status = "stopped"` value
      (text column, no migration needed).
- [x] **Backend** — three routes, process registry in orchestrator,
      sticky-stopped logic in `_finish_run`, `app.state.github_client`.
- [ ] **SDK** — no change.
- [x] **Dashboard** — typed mutations, KanbanPanel surfaces the buttons.
- [x] `scripts/e2e.sh` — still passes; the new endpoints are tested via
      pytest.

## Alternatives considered

- **Per-run resume that re-spawns directly (skip GitHub).** Rejected for
  v0.4 — the GitHub board is the operator's source of truth; bypassing it
  would create drift between dashboard and board states.
- **Single `POST /v1/agents/{run_id}/cancel` instead of `stop`.** Rejected —
  "cancel" is ambiguous (does it mark the ticket somehow?). "stop" is just
  process termination.
- **PID-based stop via `os.kill`.** Rejected — PID reuse race. Process
  registry keyed by `run_id` is safer.
