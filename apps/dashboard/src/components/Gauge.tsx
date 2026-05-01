/**
 * A horizontal capacity gauge with label, percent number, and a colored bar.
 * Color thresholds are color-blind friendly (teal → amber → magenta) per
 * CLAUDE.md §2.1 ("color-blind-safe palette for hardware gauges").
 */

export interface GaugeProps {
  label: string;
  pct: number | null;
}

function barColor(pct: number): string {
  if (pct < 60) return "bg-teal-500";
  if (pct < 85) return "bg-amber-500";
  return "bg-fuchsia-500";
}

function textColor(pct: number): string {
  if (pct < 60) return "text-teal-300";
  if (pct < 85) return "text-amber-300";
  return "text-fuchsia-300";
}

export function Gauge({ label, pct }: GaugeProps) {
  if (pct == null) {
    return (
      <div>
        <div className="mb-1 flex items-baseline justify-between">
          <span className="text-xs uppercase tracking-wider text-[--color-muted-foreground]">
            {label}
          </span>
          <span className="text-sm text-[--color-muted-foreground]">…</span>
        </div>
        <div className="h-2 w-full rounded bg-[--color-border]" />
      </div>
    );
  }

  const clamped = Math.max(0, Math.min(100, pct));
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between">
        <span className="text-xs uppercase tracking-wider text-[--color-muted-foreground]">
          {label}
        </span>
        <span className={`text-sm tabular-nums font-medium ${textColor(clamped)}`}>
          {clamped.toFixed(1)}%
        </span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded bg-[--color-border]">
        <div
          className={`h-full transition-all duration-500 ${barColor(clamped)}`}
          style={{ width: `${clamped}%` }}
        />
      </div>
    </div>
  );
}
