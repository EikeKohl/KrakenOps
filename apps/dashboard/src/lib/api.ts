/**
 * Typed REST client for the KrakenOps backend.
 * Every component reaches the backend through this module — never `fetch` directly.
 */

import type {
  AgentRunsResponse,
  BindWorkstreamResponse,
  CostsByTicketResponse,
  CostsResponse,
  DiscoveredProcessSnapshot,
  ExternalEventsListResponse,
  HealthResponse,
  KillProcessResponse,
  ProjectsListResponse,
  ResumeTicketResponse,
  SpansListResponse,
  SpawnTicketResponse,
  StopAgentResponse,
  TicketsListResponse,
  TracesListResponse,
  UnbindWorkstreamResponse,
  WorkstreamsListResponse,
} from "@/types/api";

// IPv4 literal on purpose: the backend binds to 127.0.0.1 only, but modern
// browsers resolve "localhost" to ::1 first and the connection refuses.
// Override with NEXT_PUBLIC_KRAKENOPS_API when running the backend remotely.
export const API_BASE: string =
  process.env.NEXT_PUBLIC_KRAKENOPS_API ?? "http://127.0.0.1:8787";

async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`GET ${path} → ${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

async function apiPost<T, B = unknown>(path: string, body?: B): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(`POST ${path} → ${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

// --- typed endpoint helpers ----------------------------------------------

export const api = {
  health: () => apiGet<HealthResponse>("/v1/health"),
  listTraces: (limit = 50) => apiGet<TracesListResponse>(`/v1/traces?limit=${limit}`),
  listSpans: (params?: { agent?: string; kind?: string; limit?: number }) => {
    const search = new URLSearchParams();
    if (params?.agent) search.set("agent", params.agent);
    if (params?.kind) search.set("kind", params.kind);
    search.set("limit", String(params?.limit ?? 100));
    return apiGet<SpansListResponse>(`/v1/spans?${search.toString()}`);
  },
  costs: (window: "1h" | "24h" | "7d" = "24h") =>
    apiGet<CostsResponse>(`/v1/costs?window=${window}`),
  /** ADR 0008 — per-ticket rollup. */
  costsByTicket: (window: "1h" | "24h" | "7d" = "24h") =>
    apiGet<CostsByTicketResponse>(`/v1/costs?window=${window}&group_by=ticket`),

  // ADR 0002 — kanban mirror.
  listTickets: () => apiGet<TicketsListResponse>("/v1/tickets"),

  // ADR 0002 — agent run history. (`status` = AgentRunStatus filter)
  listAgentRuns: (status?: string) =>
    apiGet<AgentRunsResponse>(`/v1/agents${status ? `?status=${status}` : ""}`),

  // ADR 0003 — command endpoints.
  spawnTicket: (ticketId: string) =>
    apiPost<SpawnTicketResponse>(`/v1/tickets/${encodeURIComponent(ticketId)}/spawn`),
  resumeTicket: (ticketId: string) =>
    apiPost<ResumeTicketResponse>(`/v1/tickets/${encodeURIComponent(ticketId)}/resume`),
  stopAgentRun: (runId: number) => apiPost<StopAgentResponse>(`/v1/agents/${runId}/stop`),

  // ADR 0005 — process discovery + external OTel ingest.
  listProcesses: () => apiGet<DiscoveredProcessSnapshot>("/v1/processes"),
  killProcess: (pid: number) =>
    apiPost<KillProcessResponse>(`/v1/processes/${encodeURIComponent(pid)}/kill`),

  // ADR 0006 — projects + workstreams.
  listProjects: () => apiGet<ProjectsListResponse>("/v1/projects"),
  listWorkstreams: (params?: { activeOnly?: boolean; limit?: number }) => {
    const search = new URLSearchParams();
    if (params?.activeOnly === false) search.set("active_only", "false");
    if (params?.limit != null) search.set("limit", String(params.limit));
    const qs = search.toString();
    return apiGet<WorkstreamsListResponse>(
      `/v1/workstreams${qs ? `?${qs}` : ""}`,
    );
  },
  bindWorkstream: (id: number, body: { ticket_id: string; project_id?: string }) =>
    apiPost<BindWorkstreamResponse, typeof body>(
      `/v1/workstreams/${encodeURIComponent(id)}/bind`,
      body,
    ),
  unbindWorkstream: (id: number) =>
    apiPost<UnbindWorkstreamResponse>(`/v1/workstreams/${encodeURIComponent(id)}/unbind`),
  listEvents: (params?: { service?: string; limit?: number; since?: number }) => {
    const search = new URLSearchParams();
    if (params?.service) search.set("service", params.service);
    search.set("limit", String(params?.limit ?? 100));
    if (params?.since != null) search.set("since", String(params.since));
    return apiGet<ExternalEventsListResponse>(`/v1/events?${search.toString()}`);
  },
};

export { apiGet, apiPost };
