"use client";

import { useLatestMessage } from "@/lib/ws";
import type { MetricsSnapshot } from "@/types/api";

/**
 * Tiny status pill that shows whether the dashboard is receiving live
 * frames from the backend's WS topic. Reads the metrics topic — it ticks
 * once a second so it's a good liveness proxy. "stale" if no frame in
 * the last 5 s.
 */
export function LiveIndicator() {
  const { ts } = useLatestMessage<MetricsSnapshot>("metrics");
  const ageMs = ts == null ? null : Date.now() - ts / 1_000_000;

  let label = "connecting";
  let dotClass = "bg-[--color-muted-foreground]";
  let textClass = "text-[--color-muted-foreground]";
  let pulse = false;

  if (ageMs != null) {
    if (ageMs < 5_000) {
      label = "live";
      dotClass = "bg-[--color-accent]";
      textClass = "text-[--color-accent]";
      pulse = true;
    } else {
      label = "stale";
      dotClass = "bg-amber-400";
      textClass = "text-amber-300";
    }
  }

  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-[--color-border] bg-[--color-surface-2] px-2 py-0.5 text-[10px] uppercase tracking-[0.15em]">
      <span
        className={`h-1.5 w-1.5 rounded-full ${dotClass} ${pulse ? "ko-live-dot" : ""}`}
        aria-hidden="true"
      />
      <span className={textClass}>{label}</span>
    </span>
  );
}
