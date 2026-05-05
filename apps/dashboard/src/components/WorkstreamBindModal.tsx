"use client";

import { api } from "@/lib/api";
import type { Project, Ticket, Workstream } from "@/types/api";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

/**
 * Modal that lets the user pick a (project, ticket) pair to bind to a
 * workstream. Uses native ``<dialog>`` — keeps us off any modal library
 * for one screen.
 */

const TERMINAL_STATUSES = new Set(["Done", "Closed", "Canceled"]);

export function WorkstreamBindModal({
  workstream,
  open,
  onClose,
}: {
  workstream: Workstream | null;
  open: boolean;
  onClose: () => void;
}) {
  const qc = useQueryClient();

  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: () => api.listProjects(),
    enabled: open,
  });
  const tickets = useQuery({
    queryKey: ["tickets"],
    queryFn: () => api.listTickets(),
    enabled: open,
  });

  const projectList: Project[] = projects.data?.projects ?? [];
  const allTickets: Ticket[] = tickets.data?.tickets ?? [];

  const [selectedProject, setSelectedProject] = useState<string | "all">("all");
  const [selectedTicket, setSelectedTicket] = useState<string>("");

  // When the modal opens, pre-select whatever project the workstream is
  // already attached to (if any).
  useEffect(() => {
    if (!open || !workstream) return;
    if (workstream.project_id) setSelectedProject(workstream.project_id);
    else setSelectedProject("all");
    setSelectedTicket("");
  }, [open, workstream]);

  const ticketChoices = useMemo(() => {
    return allTickets
      .filter(
        (t) => selectedProject === "all" || t.project_id === selectedProject,
      )
      .filter((t) => !TERMINAL_STATUSES.has(t.status))
      .sort((a, b) => a.title.localeCompare(b.title));
  }, [allTickets, selectedProject]);

  const bind = useMutation({
    mutationFn: () => {
      if (!workstream) throw new Error("no workstream");
      return api.bindWorkstream(workstream.id, {
        ticket_id: selectedTicket,
        project_id:
          selectedProject !== "all" ? selectedProject : undefined,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["workstreams"] });
      onClose();
    },
  });

  if (!open || !workstream) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      role="presentation"
    >
      <div className="w-full max-w-md rounded-xl border border-[--color-border] bg-[--color-surface] p-5 shadow-2xl">
        <header className="mb-4 flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-[0.18em] text-[--color-foreground]">
            Bind workstream
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="text-[10px] uppercase tracking-wider text-[--color-muted-foreground] hover:text-[--color-foreground]"
          >
            esc
          </button>
        </header>

        <p className="mb-4 truncate text-xs text-[--color-muted-foreground]">
          {workstream.label ?? `workstream #${workstream.id}`}
        </p>

        <label className="mb-2 flex flex-col gap-1 text-xs">
          <span className="uppercase tracking-wider text-[--color-muted-foreground]">
            Project
          </span>
          <select
            value={selectedProject}
            onChange={(e) => {
              setSelectedProject(e.target.value);
              setSelectedTicket("");
            }}
            className="rounded-md border border-[--color-border] bg-[--color-surface-2] px-2 py-1.5 text-[--color-foreground]"
          >
            <option value="all">all projects</option>
            {projectList.map((p) => (
              <option key={p.id} value={p.id}>
                {p.title}
              </option>
            ))}
          </select>
        </label>

        <label className="mb-4 flex flex-col gap-1 text-xs">
          <span className="uppercase tracking-wider text-[--color-muted-foreground]">
            Ticket
          </span>
          <select
            value={selectedTicket}
            onChange={(e) => setSelectedTicket(e.target.value)}
            className="rounded-md border border-[--color-border] bg-[--color-surface-2] px-2 py-1.5 text-[--color-foreground]"
          >
            <option value="">— pick a ticket —</option>
            {ticketChoices.map((t) => (
              <option key={t.id} value={t.id}>
                [{t.status}] {t.title}
              </option>
            ))}
          </select>
        </label>

        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-[--color-border] px-3 py-1 text-xs text-[--color-muted-foreground] hover:text-[--color-foreground]"
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={!selectedTicket || bind.isPending}
            onClick={() => bind.mutate()}
            className="rounded-md border border-[--color-accent]/40 bg-[--color-accent]/15 px-3 py-1 text-xs font-medium text-[--color-accent] hover:bg-[--color-accent]/25 disabled:opacity-40"
          >
            {bind.isPending ? "Binding…" : "Bind"}
          </button>
        </div>

        {bind.isError && (
          <p className="mt-2 text-[11px] text-rose-300">
            {String(bind.error)}
          </p>
        )}
      </div>
    </div>
  );
}
