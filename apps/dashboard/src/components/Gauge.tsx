/**
 * A horizontal capacity gauge with label, percent number, and a colored bar.
 * Color thresholds are color-blind friendly (teal → amber → fuchsia) per
 * CLAUDE.md §2.1.
 */

export interface GaugeProps {
  label: string;
  pct: number | null;
}

function barClasses(pct: number): string {
  if (pct < 60) return "from-teal-400 to-emerald-500";
  if (pct < 85) return "from-amber-400 to-amber-500";
  return "from-fuchsia-400 to-rose-500";
}

function textColor(pct: number): string {
  if (pct < 60) return "text-teal-200";
  if (pct < 85) return "text-amber-200";
  return "text-fuchsia-200";
}

export function Gauge({ label, pct }: GaugeProps) {
  if (pct == null) {
    return (
      <div>
        <div className="mb-1.5 flex items-baseline justify-between">
          <span className="text-[11px] font-medium uppercase tracking-[0.15em] text-[--color-muted-foreground]">
            {label}
          </span>
          <span className="text-sm tabular-nums text-[--color-muted-foreground]">…</span>
        </div>
        <div className="h-1.5 w-full rounded-full bg-[--color-border-subtle]" />
      </div>
    );
  }

  const clamped = Math.max(0, Math.min(100, pct));
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between">
        <span className="text-[11px] font-medium uppercase tracking-[0.15em] text-[--color-muted-foreground]">
          {label}
        </span>
        <span className={`text-sm font-semibold tabular-nums ${textColor(clamped)}`}>
          {clamped.toFixed(1)}%
        </span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-[--color-border-subtle]">
        <div
          className={`h-full rounded-full bg-gradient-to-r transition-all duration-500 ${barClasses(clamped)}`}
          style={{ width: `${clamped}%` }}
        />
      </div>
    </div>
  );
}
