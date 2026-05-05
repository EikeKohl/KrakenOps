"use client";

import { DiscoveredProcessesSection } from "@/components/DiscoveredProcessesSection";
import { ExternalEventsFeed } from "@/components/ExternalEventsFeed";
import { Panel } from "@/components/Panel";
import { SpanRow } from "@/components/SpanRow";
import { api } from "@/lib/api";
import { useTopicListener } from "@/lib/ws";
import type { SpanFull, SpanSummary } from "@/types/api";
import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
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

function SectionTitle({ title, count }: { title: string; count?: number }) {
  return (
    <header className="flex items-center justify-between gap-2 border-b border-[--color-border-subtle] pb-2">
      <h3 className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[--color-foreground]">
        {title}
      </h3>
      {count != null && (
        <span className="text-[10px] uppercase tracking-wider text-[--color-muted-foreground]">
          {count} {count === 1 ? "item" : "items"}
        </span>
      )}
    </header>
  );
}

function SdkSpansSection() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["spans", "recent"],
    queryFn: () => api.listSpans({ limit: MAX_VISIBLE }),
  });

  const [live, setLive] = useState<SpanSummary[]>([]);

  useEffect(() => {
    if (data?.spans) {
      setLive(data.spans.map(fullToSummary));
    }
  }, [data]);

  useTopicListener<SpanSummary>("traces", (msg) => {
    setLive((prev) => {
      if (prev.some((s) => s.span_id === msg.data.span_id)) return prev;
      return [msg.data, ...prev].slice(0, MAX_VISIBLE);
    });
  });

  let body: ReactNode;
  if (error) {
    body = (
      <p className="py-3 text-center text-xs text-red-300">
        Backend unreachable: {String(error)}
      </p>
    );
  } else if (isLoading && live.length === 0) {
    body = <p className="py-3 text-center text-xs text-[--color-muted-foreground]">Loading…</p>;
  } else if (live.length === 0) {
    body = (
      <div className="rounded-lg border border-dashed border-[--color-border] bg-[--color-surface-2]/40 px-4 py-4 text-center text-xs text-[--color-muted-foreground]">
        No SDK spans yet. Decorate a function with{" "}
        <code className="rounded bg-[--color-surface] px-1 py-px text-[--color-foreground]">
          @tentacle.track_agent
        </code>{" "}
        and point the exporter at this backend.
      </div>
    );
  } else {
    body = (
      <div>
        {live.map((span) => (
          <SpanRow key={span.span_id} span={span} />
        ))}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <SectionTitle title="SDK-tracked spans" count={live.length} />
      {body}
    </div>
  );
}

export function ProcessesPanel({ className }: { className?: string }) {
  return (
    <Panel
      title="Active Processes & Agents"
      subtitle="SDK spans · external activity · host processes"
      accent="violet"
      className={className}
    >
      <div className="flex flex-col gap-5 overflow-y-auto pr-1">
        <SdkSpansSection />

        <div className="flex flex-col gap-2">
          <SectionTitle title="External activity" />
          <ExternalEventsFeed />
        </div>

        <DiscoveredProcessesSection />
      </div>
    </Panel>
  );
}
