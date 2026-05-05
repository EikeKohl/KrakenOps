"use client";

import { api } from "@/lib/api";
import { useTopicListener } from "@/lib/ws";
import type { DiscoveredProcess, DiscoveredProcessSnapshot } from "@/types/api";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

/**
 * Live table of host processes the backend's psutil sampler matched against
 * `KRAKENOPS_PROCESS_ALLOWLIST`. Collapsed by default — opens to show a
 * sortable list with per-row kill buttons. REST seeds the initial render;
 * the `processes` WS topic streams 1 Hz snapshots that fully replace state.
 */

const STORAGE_KEY = "ko.processes.collapsed";

function sortByCpuDesc(rows: DiscoveredProcess[]): DiscoveredProcess[] {
  return [...rows].sort((a, b) => b.cpu_pct - a.cpu_pct);
}

function CpuBar({ pct }: { pct: number }) {
  const clamped = Math.max(0, Math.min(100, pct));
  return (
    <div className="flex items-center gap-2">
      <div
        className="h-1 w-14 overflow-hidden rounded-full bg-[--color-border-subtle]"
        aria-hidden="true"
      >
        <div
          className="h-full rounded-full bg-gradient-to-r from-sky-500 to-cyan-400"
          style={{ width: `${clamped}%` }}
        />
      </div>
      <span className="w-10 text-right tabular-nums text-[--color-foreground]">
        {pct.toFixed(1)}
      </span>
    </div>
  );
}

function KillButton({ pid, name }: { pid: number; name: string }) {
  const qc = useQueryClient();
  const mut = useMutation({
    mutationFn: () => api.killProcess(pid),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["processes", "latest"] });
    },
  });

  const handleClick = () => {
    if (mut.isPending) return;
    if (typeof window !== "undefined") {
      const ok = window.confirm(`Kill ${name} (pid ${pid})?`);
      if (!ok) return;
    }
    mut.mutate();
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={mut.isPending}
      className="rounded-md border border-rose-500/30 bg-rose-500/5 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-rose-300 transition hover:bg-rose-500/15 disabled:opacity-50"
      title={mut.isError ? String(mut.error) : "Send SIGTERM (then SIGKILL after 2s)"}
    >
      {mut.isPending ? "…" : "kill"}
    </button>
  );
}

export function DiscoveredProcessesSection() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["processes", "latest"],
    queryFn: () => api.listProcesses(),
  });

  const [processes, setProcesses] = useState<DiscoveredProcess[]>([]);
  const [collapsed, setCollapsed] = useState<boolean>(true);

  // Restore the user's last collapse preference (per-browser).
  useEffect(() => {
    if (typeof window === "undefined") return;
    const v = window.localStorage.getItem(STORAGE_KEY);
    if (v === "false") setCollapsed(false);
  }, []);

  const setCollapsedPersisted = (next: boolean) => {
    setCollapsed(next);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(STORAGE_KEY, String(next));
    }
  };

  useEffect(() => {
    if (data?.processes) setProcesses(sortByCpuDesc(data.processes));
  }, [data]);

  useTopicListener<DiscoveredProcessSnapshot>("processes", (msg) => {
    setProcesses(sortByCpuDesc(msg.data.processes));
  });

  const totalCpu = useMemo(
    () => processes.reduce((acc, p) => acc + p.cpu_pct, 0),
    [processes],
  );
  const totalRam = useMemo(
    () => processes.reduce((acc, p) => acc + p.rss_mb, 0),
    [processes],
  );

  const headerSummary = (
    <span className="text-[10px] uppercase tracking-[0.15em] text-[--color-muted-foreground]">
      {processes.length} {processes.length === 1 ? "process" : "processes"}
      {processes.length > 0 && (
        <span className="ml-2 normal-case tracking-normal">
          · cpu {totalCpu.toFixed(0)}% · ram {totalRam.toFixed(0)} MB
        </span>
      )}
    </span>
  );

  return (
    <section className="ko-surface-2 rounded-lg">
      <button
        type="button"
        onClick={() => setCollapsedPersisted(!collapsed)}
        aria-expanded={!collapsed}
        className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left"
      >
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-[--color-muted-foreground]">
            {collapsed ? "▸" : "▾"}
          </span>
          <h3 className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[--color-foreground]">
            Discovered processes
          </h3>
        </div>
        {headerSummary}
      </button>

      {!collapsed && (
        <div className="border-t border-[--color-border-subtle]/80 px-3 pb-2">
          {error ? (
            <p className="py-3 text-center text-xs text-red-300">
              Backend unreachable: {String(error)}
            </p>
          ) : isLoading && processes.length === 0 ? (
            <p className="py-3 text-center text-xs text-[--color-muted-foreground]">Loading…</p>
          ) : processes.length === 0 ? (
            <p className="py-3 text-center text-xs text-[--color-muted-foreground]">
              No matching processes detected. Edit{" "}
              <code className="rounded bg-[--color-surface-3] px-1 py-px text-[--color-foreground]">
                [processes].allowlist
              </code>{" "}
              in <code>~/.krakenops/config.toml</code> to widen the filter.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-[10px] uppercase tracking-wider text-[--color-muted-foreground]">
                    <th scope="col" className="py-1.5 pr-3 text-left font-medium">
                      Name
                    </th>
                    <th scope="col" className="py-1.5 pr-3 text-right font-medium">
                      PID
                    </th>
                    <th scope="col" className="py-1.5 pr-3 text-left font-medium">
                      CPU %
                    </th>
                    <th scope="col" className="py-1.5 pr-3 text-right font-medium">
                      RAM (MB)
                    </th>
                    <th scope="col" className="py-1.5 text-right font-medium" />
                  </tr>
                </thead>
                <tbody>
                  {processes.map((p) => (
                    <tr
                      key={p.pid}
                      className="border-t border-[--color-border-subtle]/60"
                      title={p.cmdline}
                    >
                      <td className="max-w-[14rem] truncate py-1.5 pr-3 font-mono text-[--color-foreground]">
                        {p.name}
                      </td>
                      <td className="py-1.5 pr-3 text-right font-mono tabular-nums text-[--color-muted-foreground]">
                        {p.pid}
                      </td>
                      <td className="py-1.5 pr-3 font-mono">
                        <CpuBar pct={p.cpu_pct} />
                      </td>
                      <td className="py-1.5 pr-3 text-right font-mono tabular-nums text-[--color-foreground]">
                        {p.rss_mb.toFixed(1)}
                      </td>
                      <td className="py-1.5 text-right">
                        <KillButton pid={p.pid} name={p.name} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
