"use client";

import { api } from "@/lib/api";
import { formatCost } from "@/lib/format";
import { useQuery } from "@tanstack/react-query";

/**
 * Compact rollup of LLM spend in the last 24h. Polls /v1/costs every 60s;
 * granular per-span cost lives in the Processes panel.
 */
export function CostsStrip({ className }: { className?: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["costs", "24h"],
    queryFn: () => api.costs("24h"),
    refetchInterval: 60_000,
  });

  if (error) {
    return (
      <div className={`text-xs text-red-300 ${className ?? ""}`}>costs unavailable</div>
    );
  }
  if (isLoading || !data) {
    return (
      <div className={`text-xs text-[--color-muted-foreground] ${className ?? ""}`}>…</div>
    );
  }

  const top = data.by_model.slice(0, 3);
  return (
    <div
      className={`flex items-center gap-3 rounded-full border border-[--color-border] bg-[--color-surface-2]/80 px-3 py-1 backdrop-blur-sm ${className ?? ""}`}
    >
      <span className="text-[10px] uppercase tracking-[0.18em] text-[--color-muted-foreground]">
        24h spend
      </span>
      <span className="font-mono text-sm font-semibold tabular-nums text-[--color-foreground]">
        {formatCost(data.total_cost_usd)}
      </span>
      {top.length > 0 && (
        <span className="hidden items-center gap-2 text-[11px] text-[--color-muted-foreground] md:inline-flex">
          {top.map((m) => (
            <span key={m.model} className="inline-flex items-center gap-1">
              <span className="h-1 w-1 rounded-full bg-[--color-accent]/60" aria-hidden="true" />
              <span className="font-mono">{shortModel(m.model)}</span>
              <span className="font-mono tabular-nums text-[--color-foreground]/80">
                {formatCost(m.cost_usd)}
              </span>
            </span>
          ))}
        </span>
      )}
    </div>
  );
}

function shortModel(model: string): string {
  return model.split("-").slice(0, 3).join("-");
}
