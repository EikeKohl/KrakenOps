"use client";

import { Panel } from "@/components/Panel";
import { WorkstreamBindModal } from "@/components/WorkstreamBindModal";
import { WorkstreamCard } from "@/components/WorkstreamCard";
import { api } from "@/lib/api";
import { useTopicListener } from "@/lib/ws";
import type { Ticket, Workstream, WorkstreamsSnapshot } from "@/types/api";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

/**
 * Active Workstreams panel (ADR 0006).
 *
 * REST seeds on mount, WS replaces on every change. Each card carries the
 * source badge, ticket binding (or a "bind" button), TODO progress, and
 * last-seen indicator. Bind opens a modal that lists all open tickets
 * across configured projects.
 */
export function WorkstreamsPanel({ className }: { className?: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["workstreams"],
    queryFn: () => api.listWorkstreams({ activeOnly: true }),
  });
  const ticketsQuery = useQuery({
    queryKey: ["tickets"],
    queryFn: () => api.listTickets(),
  });

  const [streams, setStreams] = useState<Workstream[]>([]);
  const [bindTarget, setBindTarget] = useState<Workstream | null>(null);

  useEffect(() => {
    if (data?.workstreams) setStreams(data.workstreams);
  }, [data]);

  useTopicListener<WorkstreamsSnapshot>("workstreams", (msg) => {
    setStreams(msg.data.workstreams);
  });

  const ticketsById = useMemo(() => {
    const map = new Map<string, Ticket>();
    for (const t of ticketsQuery.data?.tickets ?? []) map.set(t.id, t);
    return map;
  }, [ticketsQuery.data]);

  const bound = streams.filter((s) => s.ticket_id != null);
  const unbound = streams.filter((s) => s.ticket_id == null);

  let body: React.ReactNode;
  if (error) {
    body = (
      <p className="py-4 text-center text-xs text-red-300">
        Backend unreachable: {String(error)}
      </p>
    );
  } else if (isLoading && streams.length === 0) {
    body = (
      <p className="py-4 text-center text-xs text-[--color-muted-foreground]">
        Loading…
      </p>
    );
  } else if (streams.length === 0) {
    body = (
      <div className="rounded-lg border border-dashed border-[--color-border] bg-[--color-surface-2]/40 px-4 py-6 text-center text-xs text-[--color-muted-foreground]">
        <p className="mb-1 font-medium text-[--color-foreground]">
          No active workstreams.
        </p>
        <p>
          Start a Claude Code session — KrakenOps detects it from OTel
          telemetry within ~2 s.
        </p>
      </div>
    );
  } else {
    body = (
      <div className="flex flex-col gap-4">
        {bound.length > 0 && (
          <Section title="bound" count={bound.length}>
            {bound.map((s) => (
              <WorkstreamCard
                key={s.id}
                workstream={s}
                ticket={s.ticket_id ? ticketsById.get(s.ticket_id) : undefined}
                onRequestBind={() => setBindTarget(s)}
              />
            ))}
          </Section>
        )}
        {unbound.length > 0 && (
          <Section title="unbound" count={unbound.length}>
            {unbound.map((s) => (
              <WorkstreamCard
                key={s.id}
                workstream={s}
                onRequestBind={() => setBindTarget(s)}
              />
            ))}
          </Section>
        )}
      </div>
    );
  }

  return (
    <>
      <Panel
        title="Active Workstreams"
        subtitle="bind a session to a ticket — manually or via MCP"
        accent="violet"
        className={className}
        trailing={
          <span className="text-[10px] uppercase tracking-wider text-[--color-muted-foreground]">
            {streams.length} {streams.length === 1 ? "active" : "active"}
          </span>
        }
      >
        <div className="flex flex-col gap-3 overflow-y-auto pr-1">{body}</div>
      </Panel>
      <WorkstreamBindModal
        workstream={bindTarget}
        open={bindTarget !== null}
        onClose={() => setBindTarget(null)}
      />
    </>
  );
}

function Section({
  title,
  count,
  children,
}: {
  title: string;
  count: number;
  children: React.ReactNode;
}) {
  return (
    <section className="flex flex-col gap-2">
      <header className="flex items-center justify-between border-b border-[--color-border-subtle] pb-1.5">
        <h3 className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[--color-foreground]">
          {title}
        </h3>
        <span className="text-[10px] uppercase tracking-wider text-[--color-muted-foreground]">
          {count}
        </span>
      </header>
      <div className="flex flex-col gap-2">{children}</div>
    </section>
  );
}
