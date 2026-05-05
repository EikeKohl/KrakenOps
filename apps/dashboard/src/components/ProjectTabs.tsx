"use client";

import type { Project } from "@/types/api";

/**
 * Horizontal tab strip for the Kanban panel header (ADR 0006). Adds an
 * implicit "all projects" tab that aggregates everything. Sticky preference
 * lives outside this component (KanbanPanel handles localStorage so the
 * user's last project comes back on reload).
 */
export function ProjectTabs({
  projects,
  active,
  onChange,
}: {
  projects: Project[];
  active: string | "all";
  onChange: (next: string | "all") => void;
}) {
  if (projects.length <= 1) return null;
  return (
    <nav className="-mx-1 flex gap-1 overflow-x-auto pb-1.5">
      <Tab
        label="all"
        isActive={active === "all"}
        onClick={() => onChange("all")}
      />
      {projects.map((p) => (
        <Tab
          key={p.id}
          label={p.title}
          subtitle={p.owner_login || undefined}
          isActive={active === p.id}
          onClick={() => onChange(p.id)}
        />
      ))}
    </nav>
  );
}

function Tab({
  label,
  subtitle,
  isActive,
  onClick,
}: {
  label: string;
  subtitle?: string;
  isActive: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={isActive}
      className={[
        "flex shrink-0 items-baseline gap-1.5 rounded-full border px-2.5 py-0.5 font-mono text-[11px] transition",
        isActive
          ? "border-[--color-accent]/40 bg-[--color-accent]/15 text-[--color-accent]"
          : "border-[--color-border] bg-[--color-surface-2]/60 text-[--color-muted-foreground] hover:text-[--color-foreground]",
      ].join(" ")}
    >
      <span>{label}</span>
      {subtitle && (
        <span className="text-[10px] opacity-60">· {subtitle}</span>
      )}
    </button>
  );
}
