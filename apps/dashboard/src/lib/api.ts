/**
 * Typed REST client for the KrakenOps backend.
 * Every component reaches the backend through this module — never `fetch` directly.
 */

import type {
  AgentRunsResponse,
  CostsResponse,
  HealthResponse,
  ResumeTicketResponse,
  SpansListResponse,
  SpawnTicketResponse,
  StopAgentResponse,
  TicketsListResponse,
  TracesListResponse,
} from "@/types/api";

export const API_BASE: string = process.env.NEXT_PUBLIC_KRAKENOPS_API ?? "http://localhost:8787";

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
};

export { apiGet, apiPost };
