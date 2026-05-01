import { formatCost, formatDurationNs, formatRelativeTime } from "@/lib/format";
import type { SpanSummary, TentacleKind } from "@/types/api";

const KIND_STYLES: Record<TentacleKind, string> = {
  agent: "bg-teal-500/15 text-teal-300 border-teal-500/30",
  tool: "bg-sky-500/15 text-sky-300 border-sky-500/30",
  human_review: "bg-amber-500/15 text-amber-300 border-amber-500/30",
};

const KIND_LABEL: Record<TentacleKind, string> = {
  agent: "agent",
  tool: "tool",
  human_review: "human",
};

export function SpanRow({ span }: { span: SpanSummary }) {
  const kind = span.tentacle_kind;
  const kindStyle = kind ? KIND_STYLES[kind] : "bg-zinc-500/10 text-zinc-400 border-zinc-500/30";
  const kindLabel = kind ? KIND_LABEL[kind] : "—";
  const errored = span.status_code === "ERROR";

  return (
    <div className="flex items-center gap-3 border-b border-[--color-border]/50 py-2 text-sm last:border-0">
      <span
        className={`min-w-[58px] rounded border px-1.5 py-0.5 text-center text-[10px] font-medium uppercase tracking-wider ${kindStyle}`}
      >
        {kindLabel}
      </span>

      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className="truncate font-mono text-[--color-foreground]">{span.name}</span>
          {span.needs_human_review && (
            <span className="text-[10px] uppercase tracking-wider text-amber-300">
              ↑ needs review
            </span>
          )}
          {errored && (
            <span className="text-[10px] uppercase tracking-wider text-red-300">error</span>
          )}
        </div>
        <div className="truncate text-xs text-[--color-muted-foreground]">
          {span.service_name} · {formatRelativeTime(span.start_time_ns)}
        </div>
      </div>

      <div className="text-right text-xs tabular-nums text-[--color-muted-foreground]">
        <div>{formatDurationNs(span.start_time_ns, span.end_time_ns)}</div>
        {span.token_usage && (
          <div className="text-[--color-foreground]">{formatCost(span.token_usage.cost_usd)}</div>
        )}
      </div>
    </div>
  );
}
