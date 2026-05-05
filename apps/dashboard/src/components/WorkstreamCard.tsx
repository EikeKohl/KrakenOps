"use client";

import { TodoList, TodoProgressBar } from "@/components/TodoProgress";
import { api } from "@/lib/api";
import { formatRelativeTime } from "@/lib/format";
import type { Ticket, Workstream } from "@/types/api";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

const SOURCE_BADGE: Record<Workstream["source"], string> = {
  claude_code: "border-violet-400/30 bg-violet-500/10 text-violet-200",
  tentacle: "border-teal-400/30 bg-teal-500/10 text-teal-200",
  manual: "border-zinc-400/30 bg-zinc-500/10 text-zinc-200",
};

const SOURCE_LABEL: Record<Workstream["source"], string> = {
  claude_code: "Claude Code",
  tentacle: "tentacle",
  manual: "manual",
};

export function WorkstreamCard({
  workstream,
  ticket,
  onRequestBind,
}: {
  workstream: Workstream;
  ticket?: Ticket;
  onRequestBind: () => void;
}) {
  const [open, setOpen] = useState(false);
  const qc = useQueryClient();
  const live = Date.now() - workstream.last_seen_at_s * 1000 < 5_000;

  const unbind = useMutation({
    mutationFn: () => api.unbindWorkstream(workstream.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["workstreams"] });
    },
  });

  const ticketLabel = ticket?.title ?? workstream.ticket_id;

  return (
    <article className="overflow-hidden rounded-lg border border-[--color-border-subtle] bg-[--color-surface-2]/40">
      <header className="flex items-center gap-2 px-3 py-2">
        <span
          className={`inline-flex items-center rounded border px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider ${SOURCE_BADGE[workstream.source]}`}
        >
          {SOURCE_LABEL[workstream.source]}
        </span>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="flex min-w-0 flex-1 items-baseline gap-2 text-left"
        >
          <span className="text-[10px] text-[--color-muted-foreground]">
            {open ? "▾" : "▸"}
          </span>
          <span className="truncate font-mono text-xs text-[--color-foreground]">
            {workstream.label ?? `workstream #${workstream.id}`}
          </span>
        </button>
        <span className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wider">
          <span
            className={`h-1.5 w-1.5 rounded-full ${live ? "bg-[--color-accent] ko-live-dot" : "bg-[--color-muted-foreground]"}`}
            aria-hidden="true"
          />
          <span className={live ? "text-[--color-accent]" : "text-[--color-muted-foreground]"}>
            {formatRelativeTime(workstream.last_seen_at_s * 1_000_000_000)}
          </span>
        </span>
      </header>

      <div className="flex flex-wrap items-center gap-2 border-t border-[--color-border-subtle] px-3 py-2 text-xs">
        {workstream.ticket_id ? (
          <span className="inline-flex items-baseline gap-1.5 truncate">
            <span className="text-[10px] uppercase tracking-wider text-[--color-muted-foreground]">
              ticket
            </span>
            {ticket?.url ? (
              <a
                href={ticket.url}
                target="_blank"
                rel="noopener noreferrer"
                className="truncate font-medium text-[--color-foreground] hover:text-[--color-accent]"
              >
                {ticketLabel}
              </a>
            ) : (
              <span className="truncate font-medium text-[--color-foreground]">
                {ticketLabel}
              </span>
            )}
            {workstream.bind_method && (
              <span className="ml-1 text-[10px] uppercase tracking-wider text-[--color-muted-foreground]">
                · {workstream.bind_method}
              </span>
            )}
          </span>
        ) : (
          <span className="text-[--color-muted-foreground]">
            <span className="text-[10px] uppercase tracking-wider">no ticket</span>
          </span>
        )}

        <span className="ml-auto flex items-center gap-1.5">
          <button
            type="button"
            onClick={onRequestBind}
            className="rounded-md border border-[--color-border] bg-[--color-surface] px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-[--color-foreground] hover:border-[--color-accent]/50 hover:text-[--color-accent]"
          >
            {workstream.ticket_id ? "rebind" : "bind"}
          </button>
          {workstream.ticket_id && (
            <button
              type="button"
              onClick={() => unbind.mutate()}
              disabled={unbind.isPending}
              className="rounded-md border border-[--color-border] bg-[--color-surface] px-2 py-0.5 text-[10px] uppercase tracking-wider text-[--color-muted-foreground] hover:text-rose-300 disabled:opacity-40"
            >
              {unbind.isPending ? "…" : "unbind"}
            </button>
          )}
        </span>
      </div>

      <div className="border-t border-[--color-border-subtle] px-3 py-2">
        <TodoProgressBar todos={workstream.todos} />
      </div>

      {open && (
        <div className="border-t border-[--color-border-subtle] bg-[--color-surface]/50 px-3 py-3">
          <TodoList todos={workstream.todos} />
        </div>
      )}
    </article>
  );
}
