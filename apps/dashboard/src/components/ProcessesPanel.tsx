"use client";

import { Panel } from "@/components/Panel";
import { SpanRow } from "@/components/SpanRow";
import { api } from "@/lib/api";
import { useTopicListener } from "@/lib/ws";
import type { SpanFull, SpanSummary } from "@/types/api";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

const MAX_VISIBLE = 50;

function fullToSummary(s: SpanFull): SpanSummary {
  return {
    span_id: s.span_id,
    trace_id: s.trace_id,
    parent_span_id: s.parent_span_id,
    name: s.name,
    tentacle_kind: s.tentacle_kind,
    service_name: s.service_name ?? "unknown",
    start_time_ns: s.start_time_ns,
    end_time_ns: s.end_time_ns,
    status_code: s.status_code,
    needs_human_review: s.needs_human_review,
    token_usage: s.token_usage,
  };
}

export function ProcessesPanel({ className }: { className?: string }) {
  // Initial load — recent spans across all agents.
  const { data, isLoading, error } = useQuery({
    queryKey: ["spans", "recent"],
    queryFn: () => api.listSpans({ limit: MAX_VISIBLE }),
  });

  const [live, setLive] = useState<SpanSummary[]>([]);

  // Seed live state once when REST data arrives.
  useEffect(() => {
    if (data?.spans) {
      setLive(data.spans.map(fullToSummary));
    }
  }, [data]);

  // Prepend new spans as they arrive over WS, dedup by span_id.
  useTopicListener<SpanSummary>("traces", (msg) => {
    setLive((prev) => {
      if (prev.some((s) => s.span_id === msg.data.span_id)) return prev;
      return [msg.data, ...prev].slice(0, MAX_VISIBLE);
    });
  });

  let body: React.ReactNode;
  if (error) {
    body = (
      <p className="py-8 text-center text-sm text-red-300">Backend unreachable: {String(error)}</p>
    );
  } else if (isLoading && live.length === 0) {
    body = <p className="py-8 text-center text-sm text-[--color-muted-foreground]">Loading…</p>;
  } else if (live.length === 0) {
    body = (
      <p className="py-8 text-center text-sm text-[--color-muted-foreground]">
        No spans yet. Run an agent with the <code>tentacle</code> SDK pointed at this backend.
      </p>
    );
  } else {
    body = (
      <div className="overflow-y-auto">
        {live.map((span) => (
          <SpanRow key={span.span_id} span={span} />
        ))}
      </div>
    );
  }

  return (
    <Panel
      title="Active Processes & Agents"
      className={className}
      trailing={
        <span className="text-[10px] uppercase tracking-wider text-[--color-muted-foreground]">
          {live.length} {live.length === 1 ? "span" : "spans"}
        </span>
      }
    >
      {body}
    </Panel>
  );
}
