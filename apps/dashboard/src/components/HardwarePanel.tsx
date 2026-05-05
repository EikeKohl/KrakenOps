"use client";

import { Gauge } from "@/components/Gauge";
import { Panel } from "@/components/Panel";
import { useLatestMessage } from "@/lib/ws";
import type { MetricsSnapshot } from "@/types/api";

/**
 * Hardware Health panel — three gauges sitting in a fixed-height card so it
 * doesn't stretch to match the Processes panel beside it.
 */
export function HardwarePanel({ className }: { className?: string }) {
  const { data, ts } = useLatestMessage<MetricsSnapshot>("metrics");
  const live = ts != null && Date.now() - ts / 1_000_000 < 5_000;

  return (
    <Panel
      title="Hardware Health"
      subtitle={live ? "1 Hz · live" : "waiting…"}
      accent="teal"
      className={className}
      trailing={
        <span className="inline-flex items-center gap-1.5 text-[10px] uppercase tracking-[0.15em]">
          <span
            className={`h-1.5 w-1.5 rounded-full ${live ? "bg-[--color-accent] ko-live-dot" : "bg-[--color-muted-foreground]"}`}
            aria-hidden="true"
          />
          <span className={live ? "text-[--color-accent]" : "text-[--color-muted-foreground]"}>
            {live ? "live" : "idle"}
          </span>
        </span>
      }
    >
      <div className="flex flex-col gap-5">
        <Gauge label="CPU" pct={data?.cpu_pct ?? null} />
        <Gauge label="Memory" pct={data?.ram_pct ?? null} />
        <Gauge label="Disk" pct={data?.disk_pct ?? null} />
      </div>
    </Panel>
  );
}
