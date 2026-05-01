"use client";

import { api } from "@/lib/api";
import { formatRelativeTime } from "@/lib/format";
import type { Ticket } from "@/types/api";
import { useMutation, useQueryClient } from "@tanstack/react-query";

const STATUS_BADGE: Record<string, string> = {
  Todo: "bg-zinc-500/15 text-zinc-300 border-zinc-500/30",
  "In Progress": "bg-sky-500/15 text-sky-300 border-sky-500/30",
  "Needs Human Review": "bg-amber-500/15 text-amber-300 border-amber-500/30",
  Done: "bg-teal-500/15 text-teal-300 border-teal-500/30",
};

export function TicketCard({ ticket }: { ticket: Ticket }) {
  const qc = useQueryClient();

  const spawn = useMutation({
    mutationFn: () => api.spawnTicket(ticket.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agents"] });
      qc.invalidateQueries({ queryKey: ["tickets"] });
    },
  });
  const resume = useMutation({
    mutationFn: () => api.resumeTicket(ticket.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tickets"] });
    },
  });

  const badgeStyle =
    STATUS_BADGE[ticket.status] ?? "bg-zinc-500/15 text-zinc-400 border-zinc-500/30";

  const showSpawn = ticket.status !== "Done" && !!ticket.agent;
  const showResume = ticket.status === "Needs Human Review";

  return (
    <div className="rounded-md border border-[--color-border] bg-[--color-background] p-2.5">
      <div className="flex items-start justify-between gap-2">
        <a
          href={ticket.url ?? "#"}
          target="_blank"
          rel="noopener noreferrer"
          className="min-w-0 flex-1 truncate text-sm font-medium text-[--color-foreground] hover:text-[--color-accent]"
          title={ticket.title}
        >
          {ticket.title}
        </a>
        <span
          className={`shrink-0 rounded border px-1.5 py-0.5 text-[10px] uppercase tracking-wider ${badgeStyle}`}
        >
          {ticket.status}
        </span>
      </div>

      <div className="mt-1 flex items-center justify-between text-[11px] text-[--color-muted-foreground]">
        <span className="truncate">{ticket.agent ? `→ ${ticket.agent}` : "no agent assigned"}</span>
        <span className="shrink-0">{formatRelativeTime(ticket.updated_at_s * 1_000_000_000)}</span>
      </div>

      {(showSpawn || showResume) && (
        <div className="mt-2 flex gap-1.5">
          {showSpawn && (
            <button
              type="button"
              onClick={() => spawn.mutate()}
              disabled={spawn.isPending}
              className="rounded border border-sky-500/40 bg-sky-500/10 px-2 py-0.5 text-[11px] text-sky-300 hover:bg-sky-500/20 disabled:opacity-50"
            >
              {spawn.isPending ? "Spawning…" : "Spawn"}
            </button>
          )}
          {showResume && (
            <button
              type="button"
              onClick={() => resume.mutate()}
              disabled={resume.isPending}
              className="rounded border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[11px] text-amber-300 hover:bg-amber-500/20 disabled:opacity-50"
            >
              {resume.isPending ? "Resuming…" : "Resume →"}
            </button>
          )}
        </div>
      )}

      {(spawn.isError || resume.isError) && (
        <p className="mt-1 text-[11px] text-red-300">{String(spawn.error ?? resume.error)}</p>
      )}
    </div>
  );
}
