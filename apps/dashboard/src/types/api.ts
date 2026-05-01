/**
 * Backend API types — mirror what apps/backend returns at /v1/*.
 *
 * Hand-written for v0.1; eventually generated from the FastAPI OpenAPI spec
 * via `pnpm run gen:types`. Source of truth is the backend's response shapes
 * (see apps/backend/app/routes/*.py and ADR 0001 for the span attribute set).
 */

export type TentacleKind = "agent" | "tool" | "human_review";
export type StatusCode = "UNSET" | "OK" | "ERROR";

export interface HealthResponse {
  ok: boolean;
  version: string;
}

// --- /v1/traces -----------------------------------------------------------

export interface TraceSummary {
  trace_id: string;
  service_name: string;
  started_at_ns: number;
  ended_at_ns: number | null;
  span_count: number;
  has_human_review: boolean;
}

export interface TracesListResponse {
  traces: TraceSummary[];
}

// --- shared span shapes ---------------------------------------------------

export interface TokenUsage {
  model: string;
  gen_ai_system: string | null;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number | null;
}

export interface SpanFull {
  span_id: string;
  trace_id: string;
  parent_span_id: string | null;
  name: string;
  otel_kind: string;
  tentacle_kind: TentacleKind | null;
  start_time_ns: number;
  end_time_ns: number;
  status_code: StatusCode;
  status_message: string | null;
  attributes: Record<string, unknown>;
  events: Array<{ name: string; time_unix_nano: number; attributes: Record<string, unknown> }>;
  needs_human_review: boolean;
  service_name?: string;
  token_usage?: TokenUsage;
}

// --- WS-summary span (compact, no attrs/events) ---------------------------

export interface SpanSummary {
  span_id: string;
  trace_id: string;
  parent_span_id: string | null;
  name: string;
  tentacle_kind: TentacleKind | null;
  service_name: string;
  start_time_ns: number;
  end_time_ns: number;
  status_code: StatusCode;
  needs_human_review: boolean;
  token_usage?: TokenUsage;
}

// --- /v1/spans ------------------------------------------------------------

export interface SpansListResponse {
  spans: SpanFull[];
}

// --- /v1/costs ------------------------------------------------------------

export interface CostByModel {
  model: string;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
}

export interface CostsResponse {
  window: "1h" | "24h" | "7d";
  since_ns: number;
  total_cost_usd: number;
  by_model: CostByModel[];
}

// --- /v1/ws metrics topic data ------------------------------------------

export interface MetricsSnapshot {
  cpu_pct: number;
  ram_pct: number;
  disk_pct: number;
  ts_ns: number;
}

// --- /v1/tickets + /v1/ws kanban topic ---------------------------------

export type TicketStatus =
  | "Todo"
  | "In Progress"
  | "Needs Human Review"
  | "Done"
  | (string & { _other?: never }); // accept arbitrary statuses too

export interface Ticket {
  id: string;
  title: string;
  status: TicketStatus;
  url: string | null;
  agent: string | null;
  updated_at_s: number;
  last_seen_at_s?: number;
}

export interface TicketsListResponse {
  tickets: Ticket[];
}

/** Shape of `data` field on a `kanban` WS message. */
export interface KanbanSnapshot {
  tickets: Ticket[];
}

// --- /v1/agents -----------------------------------------------------------

export type AgentRunStatus = "running" | "succeeded" | "needs_human_review" | "failed" | "stopped";

export interface AgentRun {
  id: number;
  ticket_id: string;
  agent_name: string;
  pid: number | null;
  started_at_s: number;
  ended_at_s: number | null;
  status: AgentRunStatus;
  exit_code: number | null;
  stderr_tail: string | null;
}

export interface AgentRunsResponse {
  runs: AgentRun[];
}

// --- command endpoint responses (ADR 0003) ------------------------------

export interface SpawnTicketResponse {
  run_id: number | null;
  agent: string;
}

export interface StopAgentResponse {
  stopped: boolean;
}

export interface ResumeTicketResponse {
  status: "Todo";
}
