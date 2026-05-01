"use client";

import { api } from "@/lib/api";
import { formatCost } from "@/lib/format";
import { useQuery } from "@tanstack/react-query";

/**
 * Compact rollup of LLM spend in the last 24h.
 * Polls /v1/costs every 60s; the granular per-span cost lives in the
 * Processes panel.
 */
export function CostsStrip({ className }: { className?: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["costs", "24h"],
    queryFn: () => api.costs("24h"),
    refetchInterval: 60_000,
  });

  if (error) {
    return (
      <div className={className}>
        <span className="text-xs text-red-300">costs unavailable</span>
      </div>
    );
  }
  if (isLoading || !data) {
    return (
      <div className={className}>
        <span className="text-xs text-[--color-muted-foreground]">…</span>
      </div>
    );
  }

  const top = data.by_model.slice(0, 3);
  return (
    <div className={`flex items-center gap-3 text-xs ${className ?? ""}`}>
      <span className="text-[--color-muted-foreground]">24h spend:</span>
      <span className="font-mono font-medium tabular-nums text-[--color-foreground]">
        {formatCost(data.total_cost_usd)}
      </span>
      {top.length > 0 && (
        <span className="hidden text-[--color-muted-foreground] md:inline">
          ·{" "}
          {top
            .map((m) => `${m.model.split("-").slice(0, 3).join("-")} ${formatCost(m.cost_usd)}`)
            .join(" · ")}
        </span>
      )}
    </div>
  );
}
