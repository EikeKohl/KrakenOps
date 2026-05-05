import type { TodoItem } from "@/types/api";

/**
 * Compact "2/5 ✓✓○○○" rendering of a workstream's TODO list — same
 * visual idiom as Claude Code's CLI checklist. Designed for the workstream
 * card header; the expanded view uses ``TodoList`` below.
 */
export function TodoProgressBar({ todos }: { todos: TodoItem[] }) {
  if (!todos || todos.length === 0) {
    return (
      <span className="text-[10px] uppercase tracking-wider text-[--color-muted-foreground]">
        no todos yet
      </span>
    );
  }
  const done = todos.filter((t) => t.status === "completed").length;
  const inProgress = todos.find((t) => t.status === "in_progress");
  const total = todos.length;

  return (
    <div className="flex flex-wrap items-baseline gap-2 text-[11px]">
      <span className="font-mono tabular-nums text-[--color-foreground]">
        {done}/{total}
      </span>
      <span className="font-mono leading-none text-[--color-muted-foreground]">
        {todos.map((t, i) => (
          <span
            key={i}
            className={
              t.status === "completed"
                ? "text-teal-300"
                : t.status === "in_progress"
                  ? "text-amber-300"
                  : "text-[--color-muted-foreground]"
            }
          >
            {t.status === "completed" ? "✓" : t.status === "in_progress" ? "◐" : "○"}
          </span>
        ))}
      </span>
      {inProgress && (
        <span className="min-w-0 flex-1 truncate text-[--color-muted-foreground]">
          {inProgress.activeForm ?? inProgress.content}
        </span>
      )}
    </div>
  );
}

/** Full vertical list — used inside the workstream drawer. */
export function TodoList({ todos }: { todos: TodoItem[] }) {
  if (!todos || todos.length === 0) {
    return (
      <p className="py-1 text-[11px] italic text-[--color-muted-foreground]">
        Agent hasn't published a TODO list yet.
      </p>
    );
  }
  return (
    <ul className="flex flex-col gap-1">
      {todos.map((t, i) => (
        <li key={i} className="flex items-baseline gap-2 text-xs">
          <span
            className={
              t.status === "completed"
                ? "text-teal-300"
                : t.status === "in_progress"
                  ? "text-amber-300"
                  : "text-[--color-muted-foreground]"
            }
          >
            {t.status === "completed" ? "✓" : t.status === "in_progress" ? "◐" : "○"}
          </span>
          <span
            className={
              t.status === "completed"
                ? "text-[--color-muted-foreground] line-through"
                : "text-[--color-foreground]"
            }
          >
            {t.status === "in_progress" && t.activeForm ? t.activeForm : t.content}
          </span>
        </li>
      ))}
    </ul>
  );
}
