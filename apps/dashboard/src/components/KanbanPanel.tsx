"use client";

import { Panel } from "@/components/Panel";
import { TicketCard } from "@/components/TicketCard";
import { api } from "@/lib/api";
import { useTopicListener } from "@/lib/ws";
import type { KanbanSnapshot, Ticket, TicketStatus } from "@/types/api";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

// Display order: most-urgent first.
const STATUS_ORDER: TicketStatus[] = ["Needs Human Review", "In Progress", "Todo", "Done"];

function groupByStatus(tickets: Ticket[]): Map<string, Ticket[]> {
  const out = new Map<string, Ticket[]>();
  for (const status of STATUS_ORDER) out.set(status, []);
  for (const t of tickets) {
    const list = out.get(t.status);
    if (list) {
      list.push(t);
    } else {
      // unknown status — fold into "Todo" group as the safest default.
      out.get("Todo")?.push(t);
    }
  }
  return out;
}

export function KanbanPanel({ className }: { className?: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["tickets"],
    queryFn: () => api.listTickets(),
  });

  const [tickets, setTickets] = useState<Ticket[]>([]);

  useEffect(() => {
    if (data?.tickets) setTickets(data.tickets);
  }, [data]);

  // Live: every poll, the backend broadcasts a full snapshot. Just replace.
  useTopicListener<KanbanSnapshot>("kanban", (msg) => {
    setTickets(msg.data.tickets);
  });

  let body: React.ReactNode;
  if (error) {
    body = (
      <p className="py-8 text-center text-xs text-red-300">Backend unreachable: {String(error)}</p>
    );
  } else if (isLoading && tickets.length === 0) {
    body = <p className="py-8 text-center text-xs text-[--color-muted-foreground]">Loading…</p>;
  } else if (tickets.length === 0) {
    body = (
      <p className="py-8 text-center text-xs text-[--color-muted-foreground]">
        No tickets yet. Configure GitHub via <code>~/.krakenops/config.toml</code>.
      </p>
    );
  } else {
    const grouped = groupByStatus(tickets);
    body = (
      <div className="flex flex-col gap-3 overflow-y-auto">
        {STATUS_ORDER.map((status) => {
          const list = grouped.get(status) ?? [];
          if (list.length === 0) return null;
          return (
            <section key={status}>
              <h3 className="mb-1 text-[10px] font-medium uppercase tracking-wider text-[--color-muted-foreground]">
                {status} <span className="opacity-60">· {list.length}</span>
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

  return (
    <Panel
      title="Kanban Queue"
      className={className}
      trailing={
        <span className="text-[10px] uppercase tracking-wider text-[--color-muted-foreground]">
          {tickets.length} {tickets.length === 1 ? "ticket" : "tickets"}
        </span>
      }
    >
      {body}
    </Panel>
  );
}
