import type { ReactNode } from "react";

/**
 * Dashboard panel shell. Provides a layered surface with subtle border, a
 * title row, and a scrollable body. Add `accent` for a colored top edge.
 */
export function Panel({
  title,
  className,
  children,
  trailing,
  subtitle,
  accent,
}: {
  title: string;
  className?: string;
  children: ReactNode;
  trailing?: ReactNode;
  subtitle?: ReactNode;
  accent?: "teal" | "violet" | "cyan";
}) {
  const accentClass =
    accent === "violet"
      ? "before:bg-[--color-violet]"
      : accent === "cyan"
        ? "before:bg-[--color-cyan]"
        : accent
          ? "before:bg-[--color-accent]"
          : "before:bg-transparent";

  return (
    <section
      className={`relative flex flex-col overflow-hidden rounded-xl border border-[--color-border-subtle] bg-[--color-surface] shadow-[0_0_0_1px_rgba(255,255,255,0.02),0_8px_24px_-12px_rgba(0,0,0,0.6)] before:absolute before:inset-x-4 before:top-0 before:h-px ${accentClass} ${className ?? ""}`}
    >
      <header className="flex items-center justify-between gap-3 border-b border-[--color-border-subtle] px-4 py-3">
        <div className="flex flex-col leading-tight">
          <h2 className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[--color-foreground]">
            {title}
          </h2>
          {subtitle && (
            <span className="text-[10px] uppercase tracking-wider text-[--color-muted-foreground]">
              {subtitle}
            </span>
          )}
        </div>
        {trailing}
      </header>
      <div className="flex min-h-0 flex-1 flex-col p-4">{children}</div>
    </section>
  );
}
