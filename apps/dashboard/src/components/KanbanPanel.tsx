"use client";

import { Panel } from "@/components/Panel";
import { ProjectTabs } from "@/components/ProjectTabs";
import { TicketCard } from "@/components/TicketCard";
import { api } from "@/lib/api";
import { useTopicListener } from "@/lib/ws";
import type {
  KanbanSnapshot,
  Project,
  Ticket,
  TicketStatus,
} from "@/types/api";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

// Display order: most-urgent first.
const STATUS_ORDER: TicketStatus[] = ["Needs Human Review", "In Progress", "Todo", "Done"];
const STORAGE_KEY = "ko.kanban.activeProject";

function groupByStatus(tickets: Ticket[]): Map<string, Ticket[]> {
  const out = new Map<string, Ticket[]>();
  for (const status of STATUS_ORDER) out.set(status, []);
  for (const t of tickets) {
    const list = out.get(t.status);
    if (list) {
      list.push(t);
    } else {
      out.get("Todo")?.push(t);
    }
  }
  return out;
}

export function KanbanPanel({ className }: { className?: string }) {
  const ticketsQuery = useQuery({
    queryKey: ["tickets"],
    queryFn: () => api.listTickets(),
  });
  const projectsQuery = useQuery({
    queryKey: ["projects"],
    queryFn: () => api.listProjects(),
  });

  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [active, setActive] = useState<string | "all">("all");

  // Restore the last-active project tab from localStorage.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const v = window.localStorage.getItem(STORAGE_KEY);
    if (v) setActive(v);
  }, []);

  useEffect(() => {
    if (ticketsQuery.data?.tickets) setTickets(ticketsQuery.data.tickets);
  }, [ticketsQuery.data]);
  useEffect(() => {
    if (projectsQuery.data?.projects) setProjects(projectsQuery.data.projects);
  }, [projectsQuery.data]);

  // Live: every poll, the backend broadcasts a full snapshot. Just replace.
  useTopicListener<KanbanSnapshot>("kanban", (msg) => {
    setTickets(msg.data.tickets);
    if (msg.data.projects) setProjects(msg.data.projects);
  });

  const setActivePersisted = (next: string | "all") => {
    setActive(next);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(STORAGE_KEY, next);
    }
  };

  // If the previously-active project disappeared, reset to "all".
  useEffect(() => {
    if (active === "all") return;
    if (!projects.find((p) => p.id === active)) setActivePersisted("all");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projects.length, active]);

  const visibleTickets = useMemo(() => {
    if (active === "all") return tickets;
    return tickets.filter((t) => t.project_id === active);
  }, [tickets, active]);

  const error = ticketsQuery.error ?? projectsQuery.error;
  const isLoading = ticketsQuery.isLoading && tickets.length === 0;

  let body: React.ReactNode;
  if (error) {
    body = (
      <p className="py-8 text-center text-xs text-red-300">
        Backend unreachable: {String(error)}
      </p>
    );
  } else if (isLoading) {
    body = (
      <p className="py-8 text-center text-xs text-[--color-muted-foreground]">
        Loading…
      </p>
    );
  } else if (visibleTickets.length === 0) {
    body = (
      <div className="rounded-lg border border-dashed border-[--color-border] bg-[--color-surface-2]/40 px-3 py-6 text-center text-xs text-[--color-muted-foreground]">
        <p className="mb-1 font-medium text-[--color-foreground]">
          {active === "all" && tickets.length === 0
            ? "No tickets yet."
            : "No tickets in this project."}
        </p>
        <p>
          Run{" "}
          <code className="rounded bg-[--color-surface] px-1 py-px">
            scripts/setup.sh
          </code>{" "}
          to add more projects.
        </p>
      </div>
    );
  } else {
    const grouped = groupByStatus(visibleTickets);
    body = (
      <div className="flex flex-col gap-3 overflow-y-auto">
        {STATUS_ORDER.map((status) => {
          const list = grouped.get(status) ?? [];
          if (list.length === 0) return null;
          return (
            <section key={status}>
              <h3 className="mb-1.5 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.15em] text-[--color-muted-foreground]">
                <span>{status}</span>
                <span className="rounded bg-[--color-surface-2] px-1.5 py-px font-mono text-[10px] text-[--color-foreground]">
                  {list.length}
                </span>
              </h3>
              <div className="flex flex-col gap-1.5">
                {list.map((t) => (
                  <TicketCard key={t.id} ticket={t} />
                ))}
              </div>
            </section>
          );
        })}
      </div>
    );
  }

  const subtitle =
    projects.length > 1
      ? `${projects.length} projects · GitHub mirror`
      : "GitHub Projects mirror";

  return (
    <Panel
      title="Kanban Queue"
      subtitle={subtitle}
      accent="cyan"
      className={className}
      trailing={
        <span className="text-[10px] uppercase tracking-wider text-[--color-muted-foreground]">
          {visibleTickets.length}
          {active === "all" ? "" : ` / ${tickets.length}`}{" "}
          {visibleTickets.length === 1 ? "ticket" : "tickets"}
        </span>
      }
    >
      <ProjectTabs
        projects={projects}
        active={active}
        onChange={setActivePersisted}
      />
      {body}
    </Panel>
  );
}
