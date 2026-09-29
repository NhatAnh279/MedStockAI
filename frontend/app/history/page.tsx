"use client";

import { useEffect, useRef, useState } from "react";
import { api, type RecentTxnOut } from "@/lib/api";

type FilterTab = "all" | "dispense" | "receive" | "waste" | "flagged";

function formatTime(iso: string) {
  const d = new Date(iso);
  return d.toLocaleTimeString("en-AU", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function formatDate(iso: string) {
  const d = new Date(iso);
  return d.toLocaleDateString("en-AU", { day: "numeric", month: "short" });
}

function AnomalyIcon({ status, message }: { status: string | null; message: string | null }) {
  if (!status || status === "normal") {
    return (
      <span title="Normal" className="text-green-600 text-base">✓</span>
    );
  }
  if (status === "warning") {
    return (
      <span title={message ?? "Warning"} className="cursor-help text-base">⚠️</span>
    );
  }
  return (
    <span title={message ?? "Alert"} className="cursor-help text-base">🚩</span>
  );
}

function ActionBadge({ reason }: { reason: string }) {
  const styles: Record<string, string> = {
    dispense: "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300",
    receive: "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300",
    waste: "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300",
    adjust: "bg-gray-100 text-gray-800 dark:bg-gray-900/30 dark:text-gray-300",
  };
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium capitalize ${
        styles[reason] ?? styles.adjust
      }`}
    >
      {reason}
    </span>
  );
}

export default function HistoryPage() {
  const [txns, setTxns] = useState<RecentTxnOut[]>([]);
  const [newIds, setNewIds] = useState<Set<number>>(new Set());
  const [filter, setFilter] = useState<FilterTab>("all");
  const seenIds = useRef<Set<number>>(new Set());
  const isFirst = useRef(true);

  useEffect(() => {
    const poll = () => {
      api.recentTxns(50).then((data) => {
        const fresh = new Set<number>();
        for (const t of data) {
          if (!seenIds.current.has(t.id)) {
            if (!isFirst.current) fresh.add(t.id);
            seenIds.current.add(t.id);
          }
        }
        isFirst.current = false;
        setTxns(data);
        if (fresh.size > 0) {
          setNewIds((prev) => new Set([...prev, ...fresh]));
          setTimeout(() => {
            setNewIds((prev) => {
              const next = new Set(prev);
              fresh.forEach((id) => next.delete(id));
              return next;
            });
          }, 2000);
        }
      }).catch(() => {});
    };

    poll();
    const interval = setInterval(poll, 2000);
    return () => clearInterval(interval);
  }, []);

  const filtered = txns.filter((t) => {
    if (filter === "all") return true;
    if (filter === "flagged") return t.anomaly_status === "warning" || t.anomaly_status === "alert";
    return t.reason === filter;
  });

  const TABS: { key: FilterTab; label: string }[] = [
    { key: "all", label: "All" },
    { key: "dispense", label: "Dispense" },
    { key: "receive", label: "Receive" },
    { key: "waste", label: "Waste" },
    { key: "flagged", label: "⚠ Flagged" },
  ];

  return (
    <main className="mx-auto max-w-7xl px-6 py-8 flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Transaction History</h1>
          <p className="text-muted-foreground text-sm mt-1">
            Live feed — refreshes every 2 seconds
          </p>
        </div>
        <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
          <span className="size-2 rounded-full bg-green-500 animate-pulse" />
          Live
        </span>
      </div>

      {/* Filter chips */}
      <div className="flex flex-wrap gap-2">
        {TABS.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setFilter(key)}
            className={`rounded-full px-3 py-1 text-sm font-medium border transition-colors ${
              filter === key
                ? "bg-primary text-primary-foreground border-primary"
                : "border-border bg-background text-muted-foreground hover:text-foreground hover:bg-muted"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Table */}
      <div className="rounded-xl border overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/40">
                <th className="px-4 py-3 text-left font-medium text-muted-foreground whitespace-nowrap">Time</th>
                <th className="px-4 py-3 text-left font-medium text-muted-foreground">Action</th>
                <th className="px-4 py-3 text-left font-medium text-muted-foreground">Item</th>
                <th className="px-4 py-3 text-left font-medium text-muted-foreground whitespace-nowrap">Batch (Lot)</th>
                <th className="px-4 py-3 text-right font-medium text-muted-foreground">Qty</th>
                <th className="px-4 py-3 text-left font-medium text-muted-foreground">Dept</th>
                <th className="px-4 py-3 text-left font-medium text-muted-foreground">User</th>
                <th className="px-4 py-3 text-center font-medium text-muted-foreground">AI</th>
                <th className="px-4 py-3 text-left font-medium text-muted-foreground">Reason</th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={9} className="px-4 py-12 text-center text-muted-foreground">
                    No transactions yet — scan a QR code to get started
                  </td>
                </tr>
              ) : (
                filtered.map((t) => (
                  <tr
                    key={t.id}
                    className={`border-b last:border-b-0 transition-colors ${
                      newIds.has(t.id) ? "animate-row-flash" : "hover:bg-muted/30"
                    }`}
                  >
                    <td className="px-4 py-2.5 whitespace-nowrap text-muted-foreground text-xs">
                      <span className="block font-medium text-foreground">{formatTime(t.created_at)}</span>
                      <span>{formatDate(t.created_at)}</span>
                    </td>
                    <td className="px-4 py-2.5">
                      <ActionBadge reason={t.reason} />
                    </td>
                    <td className="px-4 py-2.5 font-medium max-w-[160px] truncate" title={t.item_name}>
                      {t.item_name}
                    </td>
                    <td className="px-4 py-2.5 text-muted-foreground text-xs">
                      {t.lot_no ?? "—"}
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono font-medium">
                      <span className={t.qty_delta < 0 ? "text-red-600 dark:text-red-400" : "text-green-600 dark:text-green-400"}>
                        {t.qty_delta > 0 ? "+" : ""}{t.qty_delta.toLocaleString()}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-muted-foreground text-xs whitespace-nowrap">
                      {t.department ?? "—"}
                    </td>
                    <td className="px-4 py-2.5 text-muted-foreground text-xs">
                      {t.user}
                    </td>
                    <td className="px-4 py-2.5 text-center">
                      <AnomalyIcon status={t.anomaly_status} message={t.anomaly_message} />
                    </td>
                    <td className="px-4 py-2.5 text-xs text-muted-foreground max-w-[180px] truncate" title={t.dispense_reason ?? undefined}>
                      {t.dispense_reason ?? "—"}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </main>
  );
}
