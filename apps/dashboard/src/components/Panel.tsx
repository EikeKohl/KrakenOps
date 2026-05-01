import type { ReactNode } from "react";

export function Panel({
  title,
  className,
  children,
  trailing,
}: {
  title: string;
  className?: string;
  children: ReactNode;
  trailing?: ReactNode;
}) {
  return (
    <section
      className={`flex flex-col rounded-xl border border-[--color-border] bg-[--color-muted] p-4 ${className ?? ""}`}
    >
      <header className="mb-3 flex items-center justify-between">
        <h2 className="text-xs font-medium uppercase tracking-wider text-[--color-muted-foreground]">
          {title}
        </h2>
        {trailing}
      </header>
      <div className="flex min-h-0 flex-1 flex-col">{children}</div>
    </section>
  );
}
