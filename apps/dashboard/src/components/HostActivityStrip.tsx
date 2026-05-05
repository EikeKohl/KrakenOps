"use client";

import { DiscoveredProcessesSection } from "@/components/DiscoveredProcessesSection";
import { Panel } from "@/components/Panel";
import { SpanRow } from "@/components/SpanRow";
import { api } from "@/lib/api";
import { useTopicListener } from "@/lib/ws";
import type { SpanFull, SpanSummary } from "@/types/api";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

const MAX_SPANS = 30;

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

/**
 * Secondary "host activity" row beneath the main 3-panel grid (ADR 0006).
 *
 * SDK-tracked spans live in a Panel; discovered processes use their own
 * collapsible card (which already manages its own header + state). Both
 * are intentionally compact — primary attention belongs on the
 * Workstreams + Kanban relationship above.
 */
export function HostActivityStrip({ className }: { className?: string }) {
  return (
    <div
      className={`grid grid-cols-1 gap-4 lg:grid-cols-2 ${className ?? ""}`}
    >
      <SdkSpansPanel />
      <div>
        <DiscoveredProcessesSection />
      </div>
    </div>
  );
}

function SdkSpansPanel() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["spans", "recent"],
    queryFn: () => api.listSpans({ limit: MAX_SPANS }),
  });
  const [live, setLive] = useState<SpanSummary[]>([]);

  useEffect(() => {
    if (data?.spans) setLive(data.spans.map(fullToSummary));
  }, [data]);

  useTopicListener<SpanSummary>("traces", (msg) => {
    setLive((prev) => {
      if (prev.some((s) => s.span_id === msg.data.span_id)) return prev;
      return [msg.data, ...prev].slice(0, MAX_SPANS);
    });
  });

  const spans = useMemo(() => live.slice(0, MAX_SPANS), [live]);

  let body: React.ReactNode;
  if (error) {
    body = (
      <p className="py-3 text-center text-xs text-red-300">
        Backend unreachable: {String(error)}
      </p>
    );
  } else if (isLoading && spans.length === 0) {
    body = (
      <p className="py-3 text-center text-xs text-[--color-muted-foreground]">
        Loading…
      </p>
    );
  } else if (spans.length === 0) {
    body = (
      <p className="py-3 text-center text-xs text-[--color-muted-foreground]">
        No SDK spans yet. Decorate a function with{" "}
        <code className="rounded bg-[--color-surface] px-1 py-px text-[--color-foreground]">
          @tentacle.track_agent
        </code>{" "}
        to see it here.
      </p>
    );
  } else {
    body = (
      <div className="max-h-72 overflow-y-auto pr-1">
        {spans.map((span) => (
          <SpanRow key={span.span_id} span={span} />
        ))}
      </div>
    );
  }

  return (
    <Panel
      title="SDK Spans"
      subtitle="tentacle-instrumented agents"
      accent="teal"
      trailing={
        <span className="text-[10px] uppercase tracking-wider text-[--color-muted-foreground]">
          {spans.length} {spans.length === 1 ? "span" : "spans"}
        </span>
      }
    >
      {body}
    </Panel>
  );
}
