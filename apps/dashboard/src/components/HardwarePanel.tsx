"use client";

import { Gauge } from "@/components/Gauge";
import { Panel } from "@/components/Panel";
import { useLatestMessage } from "@/lib/ws";
import type { MetricsSnapshot } from "@/types/api";

export function HardwarePanel({ className }: { className?: string }) {
  const { data, ts } = useLatestMessage<MetricsSnapshot>("metrics");

  return (
    <Panel
      title="Hardware Health"
      className={className}
      trailing={
        <span className="text-[10px] uppercase tracking-wider text-[--color-muted-foreground]">
          {ts == null ? "waiting" : "live"}
        </span>
      }
    >
      <div className="flex flex-col gap-4 py-2">
        <Gauge label="CPU" pct={data?.cpu_pct ?? null} />
        <Gauge label="RAM" pct={data?.ram_pct ?? null} />
        <Gauge label="Disk" pct={data?.disk_pct ?? null} />
      </div>
    </Panel>
  );
}
