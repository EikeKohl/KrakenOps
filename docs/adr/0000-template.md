# ADR NNNN: <short title>

- **Status:** Proposed | Accepted | Superseded by ADR XXXX
- **Date:** YYYY-MM-DD
- **Deciders:** @your-handle, ...
- **Affects:** sdk · backend · dashboard · contract  *(check all that apply)*

## Context

What is the problem we're solving? What constraints are at play (performance, compatibility, local-first, dependency hygiene)? Why does this decision need to be made *now*?

## Decision

What did we decide. Be specific — name the attribute, the route, the schema column, the enum value. If this is a wire-format change, paste the old and new shapes side-by-side.

## Consequences

### Positive
- …

### Negative / accepted risks
- …

## Ripple plan

Per [`CLAUDE.md`](../../CLAUDE.md) §6, contract changes ripple in this order. Tick off each as it's done in the PR:

- [ ] **Schema doc / fixtures** updated in `tests/contract/`
- [ ] **Backend** ingestion + serving + migration
- [ ] **SDK** (`tentacle`) emits the new shape; version bumped (major if breaking)
- [ ] **Dashboard** types regenerated + UI consumes the new field
- [ ] `scripts/e2e.sh` passes against the new shape
- [ ] `CLAUDE.md` §5 updated if the data flow changed

## Alternatives considered

Briefly: what else did we look at, and why didn't we pick it?
