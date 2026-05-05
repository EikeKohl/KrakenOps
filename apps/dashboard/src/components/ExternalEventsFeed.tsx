"use client";

import { api } from "@/lib/api";
import { formatCost, formatRelativeTime } from "@/lib/format";
import { useTopicListener } from "@/lib/ws";
import type {
  ExternalActivity,
  ExternalEventRecord,
  ExternalMetricRecord,
} from "@/types/api";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

/**
 * Live feed of external OTel records (Claude Code et al.) the backend
 * ingested via /v1/metrics + /v1/logs. Top-level grouping is by
 * `session_id` (a CLI session = one card); within a session, events are
 * sub-grouped by `prompt_id` so a single user prompt and its API + tool
 * fan-out land together. Aggregate metrics fold into the matching session.
 *
 * See ADR 0005 and tests/contract/schemas/claude_code_event.schema.json.
 */

const MAX_EVENTS = 400;
const MAX_METRICS = 100;
const ALL_SERVICES = "__all__";
const STANDALONE_SESSION = "__no_session__";

// --- helpers --------------------------------------------------------------

function attrString(attrs: Record<string, unknown>, key: string): string | null {
  const v = attrs?.[key];
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  return null;
}

/**
 * Claude Code's OTLP exporter emits some numeric values as JSON strings
 * ("duration_ms": "195") and others as proper numbers ("input_tokens": 1).
 * Coerce both shapes — return null only when the value is missing or
 * non-numeric.
 */
function attrNumber(attrs: Record<string, unknown>, key: string): number | null {
  const v = attrs?.[key];
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string" && v !== "") {
    const n = Number(v);
    if (Number.isFinite(n)) return n;
  }
  return null;
}

/** Coerce "true"/"false" strings as well as native booleans. */
function attrBool(attrs: Record<string, unknown>, key: string): boolean | null {
  const v = attrs?.[key];
  if (typeof v === "boolean") return v;
  if (v === "true") return true;
  if (v === "false") return false;
  return null;
}

/**
 * Match an event by suffix so we accept both the OTel-style bare name
 * Claude Code actually emits ("api_request") and the prefixed form the
 * contract schema documents ("claude_code.api_request").
 */
function eventNameIs(name: string, base: string): boolean {
  return name === base || name === `claude_code.${base}`;
}

function isEvent(r: ExternalActivity): r is ExternalEventRecord {
  return r.kind === "event";
}
function isMetric(r: ExternalActivity): r is ExternalMetricRecord {
  return r.kind === "metric";
}

function eventKey(e: ExternalEventRecord): string {
  return `${e.service_name}:${e.event_name}:${e.observed_at_ns}:${
    e.prompt_id ?? ""
  }:${e.session_id ?? ""}`;
}
function metricKey(m: ExternalMetricRecord): string {
  return `${m.service_name}:${m.metric_name}:${m.ts_ns}`;
}

function shortId(id: string | null | undefined, n = 6): string {
  if (!id) return "—";
  return id.length <= n ? id : id.slice(0, n);
}

function eventTimestampNs(r: ExternalActivity): number {
  return isEvent(r) ? r.observed_at_ns : r.ts_ns;
}

// --- data shaping ---------------------------------------------------------

interface PromptGroup {
  /** prompt_id, or synthetic "loose:<eventKey>" for events without one. */
  key: string;
  prompt_id: string | null;
  events: ExternalEventRecord[];
  startedAtNs: number;
}

interface SessionGroup {
  key: string; // session_id, or "__no_session__"
  session_id: string | null;
  service_name: string;
  events: ExternalEventRecord[];
  metrics: ExternalMetricRecord[];
  prompts: PromptGroup[];
  startedAtNs: number;
  lastSeenNs: number;
}

function groupBySession(records: ExternalActivity[]): SessionGroup[] {
  const sessions = new Map<string, SessionGroup>();

  for (const r of records) {
    // Events carry `session_id` as a top-level field (the backend pulled it
    // out of attributes). Metrics keep it inside `attributes["session.id"]`.
    const sid = isEvent(r) ? r.session_id : attrString(r.attributes ?? {}, "session.id");
    const key = sid ?? STANDALONE_SESSION;
    let s = sessions.get(key);
    if (!s) {
      s = {
        key,
        session_id: sid,
        service_name: r.service_name,
        events: [],
        metrics: [],
        prompts: [],
        startedAtNs: eventTimestampNs(r),
        lastSeenNs: eventTimestampNs(r),
      };
      sessions.set(key, s);
    }
    if (isEvent(r)) s.events.push(r);
    else s.metrics.push(r);
    const ts = eventTimestampNs(r);
    if (ts < s.startedAtNs) s.startedAtNs = ts;
    if (ts > s.lastSeenNs) s.lastSeenNs = ts;
  }

  for (const s of sessions.values()) {
    const promptMap = new Map<string, PromptGroup>();
    for (const e of s.events) {
      const pkey = e.prompt_id ? `prompt:${e.prompt_id}` : `loose:${eventKey(e)}`;
      let p = promptMap.get(pkey);
      if (!p) {
        p = {
          key: pkey,
          prompt_id: e.prompt_id,
          events: [],
          startedAtNs: e.observed_at_ns,
        };
        promptMap.set(pkey, p);
      }
      p.events.push(e);
      if (e.observed_at_ns < p.startedAtNs) p.startedAtNs = e.observed_at_ns;
    }
    const promptList = Array.from(promptMap.values());
    promptList.sort((a, b) => b.startedAtNs - a.startedAtNs);
    for (const p of promptList) {
      p.events.sort((a, b) => a.observed_at_ns - b.observed_at_ns);
    }
    s.prompts = promptList;
  }

  const out = Array.from(sessions.values());
  out.sort((a, b) => b.lastSeenNs - a.lastSeenNs);
  return out;
}

// --- prompt-cluster summary -----------------------------------------------

interface PromptStats {
  promptText: string | null;
  promptLength: number | null;
  models: string[];
  apiCalls: number;
  toolCalls: number;
  toolNames: string[];
  failedTools: number;
  inputTokens: number;
  outputTokens: number;
  cacheReadTokens: number;
  cacheCreationTokens: number;
  totalCost: number | null;
  totalDurationMs: number | null;
}

function promptStats(events: ExternalEventRecord[]): PromptStats {
  const stats: PromptStats = {
    promptText: null,
    promptLength: null,
    models: [],
    apiCalls: 0,
    toolCalls: 0,
    toolNames: [],
    failedTools: 0,
    inputTokens: 0,
    outputTokens: 0,
    cacheReadTokens: 0,
    cacheCreationTokens: 0,
    totalCost: null,
    totalDurationMs: null,
  };
  const modelSet = new Set<string>();
  const toolSet = new Set<string>();
  let costAcc = 0;
  let costCount = 0;
  let durAcc = 0;
  let durCount = 0;

  for (const e of events) {
    const a = e.attributes ?? {};
    if (eventNameIs(e.event_name, "user_prompt")) {
      const text = attrString(a, "prompt");
      if (text && !isRedactedPrompt(text)) stats.promptText = text;
      stats.promptLength = stats.promptLength ?? attrNumber(a, "prompt_length");
    } else if (eventNameIs(e.event_name, "api_request")) {
      stats.apiCalls += 1;
      const model = attrString(a, "model");
      if (model) modelSet.add(model);
      const i = attrNumber(a, "input_tokens");
      const o = attrNumber(a, "output_tokens");
      const cr = attrNumber(a, "cache_read_tokens");
      const cc = attrNumber(a, "cache_creation_tokens");
      const cost = attrNumber(a, "cost_usd");
      const dur = attrNumber(a, "duration_ms");
      if (i != null) stats.inputTokens += i;
      if (o != null) stats.outputTokens += o;
      if (cr != null) stats.cacheReadTokens += cr;
      if (cc != null) stats.cacheCreationTokens += cc;
      if (cost != null) {
        costAcc += cost;
        costCount += 1;
      }
      if (dur != null) {
        durAcc += dur;
        durCount += 1;
      }
    } else if (eventNameIs(e.event_name, "tool_result")) {
      stats.toolCalls += 1;
      const tool = attrString(a, "tool_name");
      if (tool) toolSet.add(tool);
      if (attrBool(a, "success") === false) stats.failedTools += 1;
    }
  }
  stats.models = Array.from(modelSet);
  stats.toolNames = Array.from(toolSet);
  stats.totalCost = costCount > 0 ? costAcc : null;
  stats.totalDurationMs = durCount > 0 ? durAcc : null;
  return stats;
}

interface SessionStats {
  apiCalls: number;
  toolCalls: number;
  totalInputTokens: number;
  totalOutputTokens: number;
  totalCost: number;
}

function sessionStats(events: ExternalEventRecord[], metrics: ExternalMetricRecord[]): SessionStats {
  let apiCalls = 0;
  let toolCalls = 0;
  let totalInputTokens = 0;
  let totalOutputTokens = 0;
  let totalCost = 0;
  for (const e of events) {
    const a = e.attributes ?? {};
    if (eventNameIs(e.event_name, "api_request")) {
      apiCalls += 1;
      totalInputTokens += attrNumber(a, "input_tokens") ?? 0;
      totalOutputTokens += attrNumber(a, "output_tokens") ?? 0;
      totalCost += attrNumber(a, "cost_usd") ?? 0;
    } else if (eventNameIs(e.event_name, "tool_result")) {
      toolCalls += 1;
    }
  }
  // Cost-of-record from claude_code.cost.usage metric is more authoritative
  // when present (Claude Code emits it post-request). Take the higher value.
  let metricCost = 0;
  for (const m of metrics) {
    if (eventNameIs(m.metric_name, "cost.usage")) metricCost += m.value;
  }
  if (metricCost > totalCost) totalCost = metricCost;
  return { apiCalls, toolCalls, totalInputTokens, totalOutputTokens, totalCost };
}

/**
 * The user_prompt body is redacted by default unless the operator opts in via
 * `OTEL_LOG_USER_PROMPTS=1`. Treat both placeholder forms — the schema's
 * `[redacted]` and Claude Code's actual `<REDACTED>` — as "no content".
 */
function isRedactedPrompt(s: string): boolean {
  const t = s.trim().toLowerCase();
  return t === "[redacted]" || t === "<redacted>";
}

// --- atoms ----------------------------------------------------------------

function ServiceBadge({ name }: { name: string }) {
  return (
    <span className="inline-flex items-center rounded border border-violet-400/30 bg-violet-500/10 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-violet-200">
      {name}
    </span>
  );
}

function StatChip({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <span className="inline-flex items-baseline gap-1.5 rounded-md border border-[--color-border-subtle] bg-[--color-surface] px-1.5 py-0.5 font-mono text-[10px]">
      <span className="uppercase tracking-wider text-[--color-muted-foreground]">{label}</span>
      <span className={`tabular-nums ${accent ?? "text-[--color-foreground]"}`}>{value}</span>
    </span>
  );
}

function EventNameLabel({ name }: { name: string }) {
  const stripped = name.startsWith("claude_code.")
    ? name.slice("claude_code.".length)
    : name;
  return <span className="font-mono text-[--color-foreground]">{stripped}</span>;
}

function EventRow({ event }: { event: ExternalEventRecord }) {
  const attrs = event.attributes ?? {};
  const accents: React.ReactNode[] = [];

  if (eventNameIs(event.event_name, "api_request")) {
    const model = attrString(attrs, "model");
    const duration = attrNumber(attrs, "duration_ms");
    const cost = attrNumber(attrs, "cost_usd");
    const input = attrNumber(attrs, "input_tokens");
    const output = attrNumber(attrs, "output_tokens");
    if (model) accents.push(<span key="m">{model}</span>);
    if (input != null && output != null) {
      accents.push(
        <span key="t" className="text-[--color-foreground]">
          {input.toLocaleString()}↑ / {output.toLocaleString()}↓
        </span>,
      );
    }
    if (duration != null) accents.push(<span key="d">{Math.round(duration)}ms</span>);
    if (cost != null)
      accents.push(
        <span key="c" className="text-[--color-foreground]">
          {formatCost(cost)}
        </span>,
      );
  } else if (eventNameIs(event.event_name, "tool_result")) {
    const tool = attrString(attrs, "tool_name");
    const success = attrBool(attrs, "success");
    const duration = attrNumber(attrs, "duration_ms");
    if (tool) accents.push(<span key="t" className="text-[--color-foreground]">{tool}</span>);
    if (success != null) {
      accents.push(
        <span key="ok" className={success ? "text-teal-300" : "text-amber-300"}>
          {success ? "ok" : "failed"}
        </span>,
      );
    }
    if (duration != null) accents.push(<span key="d">{Math.round(duration)}ms</span>);
  } else if (eventNameIs(event.event_name, "tool_decision")) {
    const tool = attrString(attrs, "tool_name");
    const decision = attrString(attrs, "decision");
    if (tool) accents.push(<span key="t" className="text-[--color-foreground]">{tool}</span>);
    if (decision)
      accents.push(
        <span
          key="d"
          className={decision === "accept" ? "text-teal-300" : "text-amber-300"}
        >
          {decision}
        </span>,
      );
  } else if (eventNameIs(event.event_name, "user_prompt")) {
    const len = attrNumber(attrs, "prompt_length");
    if (len != null) accents.push(<span key="l">{len} chars</span>);
  } else if (eventNameIs(event.event_name, "api_error")) {
    const message = attrString(attrs, "error") ?? attrString(attrs, "message");
    if (message) accents.push(<span key="err" className="text-rose-300">{message}</span>);
  }

  return (
    <div className="flex items-baseline gap-3 py-1 text-xs">
      <EventNameLabel name={event.event_name} />
      {accents.length > 0 && (
        <div className="flex flex-wrap items-baseline gap-2 font-mono text-[--color-muted-foreground]">
          {accents}
        </div>
      )}
      <span className="ml-auto whitespace-nowrap text-[10px] uppercase tracking-wider text-[--color-muted-foreground]">
        {formatRelativeTime(event.observed_at_ns)}
      </span>
    </div>
  );
}

function PromptCluster({ group }: { group: PromptGroup }) {
  const [open, setOpen] = useState(false);
  const stats = useMemo(() => promptStats(group.events), [group.events]);
  const totalTokens = stats.inputTokens + stats.outputTokens;

  const headline = stats.promptText
    ? truncate(stats.promptText, 120)
    : group.prompt_id
      ? `prompt ${shortId(group.prompt_id, 8)}`
      : (group.events[0]?.event_name ?? "event");

  return (
    <article className="rounded-md border border-[--color-border-subtle] bg-[--color-surface-2]/40">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full flex-col items-stretch gap-1.5 px-2.5 py-2 text-left"
      >
        <div className="flex items-baseline gap-2">
          <span className="text-[10px] text-[--color-muted-foreground]">
            {open ? "▾" : "▸"}
          </span>
          <span className="min-w-0 flex-1 text-xs leading-snug text-[--color-foreground]">
            <span className="font-medium">{headline}</span>
          </span>
          <span className="ml-2 whitespace-nowrap text-[10px] uppercase tracking-wider text-[--color-muted-foreground]">
            {formatRelativeTime(group.startedAtNs)}
          </span>
        </div>
        <div className="flex flex-wrap items-baseline gap-1.5 pl-4">
          {stats.models.map((m) => (
            <StatChip key={m} label="model" value={m} accent="text-violet-200" />
          ))}
          {stats.apiCalls > 0 && (
            <StatChip label="api" value={String(stats.apiCalls)} />
          )}
          {totalTokens > 0 && (
            <StatChip
              label="tok"
              value={`${stats.inputTokens.toLocaleString()}↑/${stats.outputTokens.toLocaleString()}↓`}
            />
          )}
          {stats.cacheReadTokens > 0 && (
            <StatChip
              label="cache"
              value={`${stats.cacheReadTokens.toLocaleString()}↺`}
              accent="text-cyan-200"
            />
          )}
          {stats.toolCalls > 0 && (
            <StatChip
              label="tools"
              value={
                stats.failedTools > 0
                  ? `${stats.toolCalls} (${stats.failedTools} failed)`
                  : String(stats.toolCalls)
              }
              accent={stats.failedTools > 0 ? "text-amber-200" : undefined}
            />
          )}
          {stats.totalCost != null && stats.totalCost > 0 && (
            <StatChip
              label="cost"
              value={formatCost(stats.totalCost)}
              accent="text-teal-200"
            />
          )}
          {stats.totalDurationMs != null && (
            <StatChip label="dur" value={`${Math.round(stats.totalDurationMs)}ms`} />
          )}
        </div>
      </button>
      {open && (
        <div className="border-t border-[--color-border-subtle] px-3 py-2">
          {stats.promptText && (
            <div className="mb-2 max-h-40 overflow-y-auto whitespace-pre-wrap rounded bg-[--color-surface] px-2 py-1.5 font-mono text-[11px] leading-snug text-[--color-foreground]">
              {stats.promptText}
            </div>
          )}
          {group.events.map((e) => (
            <EventRow key={eventKey(e)} event={e} />
          ))}
        </div>
      )}
    </article>
  );
}

function SessionCard({ group }: { group: SessionGroup }) {
  const [open, setOpen] = useState(true);
  const stats = useMemo(
    () => sessionStats(group.events, group.metrics),
    [group.events, group.metrics],
  );
  const isStandalone = group.session_id == null;

  return (
    <section className="overflow-hidden rounded-lg border border-[--color-border] bg-[--color-surface]">
      <header className="flex flex-wrap items-center gap-3 border-b border-[--color-border-subtle] bg-gradient-to-r from-[--color-surface-2] to-[--color-surface] px-3 py-2">
        <ServiceBadge name={group.service_name} />
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="flex min-w-0 flex-1 items-baseline gap-2 text-left"
        >
          <span className="text-[10px] text-[--color-muted-foreground]">
            {open ? "▾" : "▸"}
          </span>
          <span className="min-w-0 flex-1 truncate font-mono text-xs text-[--color-foreground]">
            {isStandalone ? "no session id" : `session ${shortId(group.session_id, 8)}`}
          </span>
          <span className="text-[10px] uppercase tracking-wider text-[--color-muted-foreground]">
            {group.prompts.length} {group.prompts.length === 1 ? "prompt" : "prompts"} ·{" "}
            {formatRelativeTime(group.lastSeenNs)}
          </span>
        </button>
      </header>
      <div className="flex flex-wrap gap-1.5 border-b border-[--color-border-subtle] bg-[--color-surface] px-3 py-2">
        <StatChip label="api" value={String(stats.apiCalls)} />
        <StatChip label="tools" value={String(stats.toolCalls)} />
        <StatChip
          label="tok"
          value={`${stats.totalInputTokens.toLocaleString()}↑/${stats.totalOutputTokens.toLocaleString()}↓`}
        />
        <StatChip
          label="cost"
          value={formatCost(stats.totalCost)}
          accent="text-teal-200"
        />
      </div>
      {open && (
        <div className="flex flex-col gap-1.5 px-3 py-2">
          {group.prompts.length === 0 ? (
            <p className="py-2 text-center text-[11px] text-[--color-muted-foreground]">
              No prompts yet — only aggregate counters seen.
            </p>
          ) : (
            group.prompts.map((p) => <PromptCluster key={p.key} group={p} />)
          )}
        </div>
      )}
    </section>
  );
}

// --- main component -------------------------------------------------------

export function ExternalEventsFeed() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["events", "latest"],
    queryFn: () => api.listEvents({ limit: 200 }),
  });

  const [records, setRecords] = useState<ExternalActivity[]>([]);
  const [serviceFilter, setServiceFilter] = useState<string>(ALL_SERVICES);

  useEffect(() => {
    if (data?.events) setRecords(data.events);
  }, [data]);

  useTopicListener<ExternalActivity>("events", (msg) => {
    setRecords((prev) => {
      const next = [msg.data, ...prev];
      let metricBudget = MAX_METRICS;
      let eventBudget = MAX_EVENTS;
      const trimmed: ExternalActivity[] = [];
      for (const r of next) {
        if (isMetric(r)) {
          if (metricBudget > 0) {
            trimmed.push(r);
            metricBudget--;
          }
        } else if (eventBudget > 0) {
          trimmed.push(r);
          eventBudget--;
        }
      }
      return trimmed;
    });
  });

  const services = useMemo(() => {
    const set = new Set<string>();
    for (const r of records) set.add(r.service_name);
    return Array.from(set).sort();
  }, [records]);

  const visible = useMemo(() => {
    if (serviceFilter === ALL_SERVICES) return records;
    return records.filter((r) => r.service_name === serviceFilter);
  }, [records, serviceFilter]);

  const sessions = useMemo(() => groupBySession(visible), [visible]);

  if (error) {
    return (
      <p className="py-4 text-center text-xs text-red-300">
        Backend unreachable: {String(error)}
      </p>
    );
  }
  if (isLoading && records.length === 0) {
    return (
      <p className="py-4 text-center text-xs text-[--color-muted-foreground]">Loading…</p>
    );
  }
  if (records.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-[--color-border] bg-[--color-surface-2]/40 px-4 py-6 text-center text-xs text-[--color-muted-foreground]">
        <p className="mb-2 font-medium text-[--color-foreground]">No external activity yet.</p>
        <p>
          Run the setup wizard:{" "}
          <code className="rounded bg-[--color-surface] px-1 py-px text-[--color-foreground]">
            scripts/setup.sh
          </code>{" "}
          — it installs the Claude Code OTel env vars for you.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {services.length > 1 && (
        <div className="flex items-center gap-2 text-xs">
          <label
            htmlFor="service-filter"
            className="text-[10px] uppercase tracking-[0.15em] text-[--color-muted-foreground]"
          >
            Service
          </label>
          <select
            id="service-filter"
            value={serviceFilter}
            onChange={(e) => setServiceFilter(e.target.value)}
            className="rounded-md border border-[--color-border] bg-[--color-surface-2] px-2 py-0.5 font-mono text-xs text-[--color-foreground]"
          >
            <option value={ALL_SERVICES}>all</option>
            {services.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
      )}

      {sessions.length > 0 ? (
        <div className="flex flex-col gap-3">
          {sessions.map((s) => (
            <SessionCard key={s.key} group={s} />
          ))}
        </div>
      ) : (
        <p className="py-2 text-center text-xs text-[--color-muted-foreground]">
          No events match the current filter.
        </p>
      )}
    </div>
  );
}

function truncate(s: string, n: number): string {
  if (s.length <= n) return s;
  return `${s.slice(0, n - 1)}…`;
}

// Avoid an "unused" warning when the metric badge shape isn't rendered
// directly — the export keeps the helper available for future surfaces.
export const _metricKey = metricKey;
