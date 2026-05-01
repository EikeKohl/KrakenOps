import { CostsStrip } from "@/components/CostsStrip";
import { HardwarePanel } from "@/components/HardwarePanel";
import { KanbanPanel } from "@/components/KanbanPanel";
import { ProcessesPanel } from "@/components/ProcessesPanel";

/**
 * Dashboard shell — title bar with cost rollup + three-panel grid below.
 */
export default function DashboardPage() {
  return (
    <div className="grid h-screen grid-rows-[auto_1fr] gap-3 p-4">
      <header className="flex items-center justify-between gap-4 px-1">
        <h1 className="text-sm font-semibold tracking-wide text-[--color-foreground]">KrakenOps</h1>
        <CostsStrip />
      </header>
      <main className="grid min-h-0 grid-cols-1 gap-4 lg:grid-cols-12">
        <HardwarePanel className="lg:col-span-3" />
        <ProcessesPanel className="lg:col-span-6" />
        <KanbanPanel className="lg:col-span-3" />
      </main>
    </div>
  );
}
