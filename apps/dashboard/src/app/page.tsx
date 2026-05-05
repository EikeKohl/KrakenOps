import { CostsStrip } from "@/components/CostsStrip";
import { HardwarePanel } from "@/components/HardwarePanel";
import { KanbanPanel } from "@/components/KanbanPanel";
import { LiveIndicator } from "@/components/LiveIndicator";
import { ProcessesPanel } from "@/components/ProcessesPanel";

/**
 * Dashboard shell — header strip with brand + live state + cost rollup,
 * three-panel grid below. The left column hosts Hardware Health on top and
 * leaves room to grow without inheriting the Processes panel's height.
 */
export default function DashboardPage() {
  return (
    <div className="grid h-screen grid-rows-[auto_1fr] gap-4 p-4 lg:p-5">
      <header className="flex flex-wrap items-center justify-between gap-4 px-1">
        <div className="flex items-center gap-3">
          <BrandMark />
          <div className="flex flex-col leading-none">
            <span className="text-sm font-semibold tracking-wide text-[--color-foreground]">
              KrakenOps
            </span>
            <span className="text-[10px] uppercase tracking-[0.18em] text-[--color-muted-foreground]">
              Local Command Center
            </span>
          </div>
          <LiveIndicator />
        </div>
        <CostsStrip />
      </header>
      <main className="grid min-h-0 grid-cols-1 gap-4 lg:grid-cols-12">
        <div className="flex flex-col gap-4 self-start lg:col-span-3">
          <HardwarePanel />
        </div>
        <ProcessesPanel className="lg:col-span-6" />
        <KanbanPanel className="lg:col-span-3" />
      </main>
    </div>
  );
}

/**
 * "Tentacles reaching into agents" — a compact hexagonal mark with a teal
 * glow. SVG so we don't need an asset pipeline.
 */
function BrandMark() {
  return (
    <div className="relative flex h-9 w-9 items-center justify-center rounded-lg border border-[--color-border] bg-[--color-surface-2] shadow-[0_0_30px_-12px_var(--color-accent-glow)]">
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
        className="h-5 w-5 text-[--color-accent]"
      >
        <path d="M12 4c-3.5 0-6 2.5-6 6v3a6 6 0 0 0 12 0v-3c0-3.5-2.5-6-6-6Z" />
        <path d="M9 14c0 1.5-.8 3-2 4" />
        <path d="M15 14c0 1.5.8 3 2 4" />
        <path d="M12 14v4" />
        <circle cx="10" cy="10" r=".8" fill="currentColor" stroke="none" />
        <circle cx="14" cy="10" r=".8" fill="currentColor" stroke="none" />
      </svg>
    </div>
  );
}
