import { HardwarePanel } from "@/components/HardwarePanel";
import { KanbanPanel } from "@/components/KanbanPanel";
import { ProcessesPanel } from "@/components/ProcessesPanel";

/**
 * Dashboard shell — three-panel grid.
 * Hardware + Processes are live (PR #6); Kanban is a placeholder until PR #8.
 */
export default function DashboardPage() {
  return (
    <main className="grid h-screen grid-cols-1 gap-4 p-4 lg:grid-cols-12">
      <HardwarePanel className="lg:col-span-3" />
      <ProcessesPanel className="lg:col-span-6" />
      <KanbanPanel className="lg:col-span-3" />
    </main>
  );
}
