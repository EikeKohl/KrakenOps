/** Small formatting helpers shared across panels. */

export function formatCost(cost: number | null | undefined): string {
  if (cost == null) return "—";
  if (cost === 0) return "$0";
  if (cost < 0.0001) return "<$0.0001";
  if (cost < 1) return `$${cost.toFixed(4)}`;
  return `$${cost.toFixed(2)}`;
}

export function formatRelativeTime(nsTimestamp: number, nowMs: number = Date.now()): string {
  const ageMs = nowMs - nsTimestamp / 1_000_000;
  if (ageMs < 1000) return "just now";
  if (ageMs < 60_000) return `${Math.floor(ageMs / 1000)}s ago`;
  if (ageMs < 3_600_000) return `${Math.floor(ageMs / 60_000)}m ago`;
  if (ageMs < 86_400_000) return `${Math.floor(ageMs / 3_600_000)}h ago`;
  return `${Math.floor(ageMs / 86_400_000)}d ago`;
}

export function formatDurationNs(startNs: number, endNs: number): string {
  const ms = (endNs - startNs) / 1_000_000;
  if (ms < 1) return "<1ms";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}
