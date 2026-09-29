"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  api,
  type ItemListOut,
  type POListItem,
  type ExpiringBatchOut,
  type StockSnapshotPoint,
} from "@/lib/api";

const LINE_COLORS = ["#ef4444", "#f97316", "#8b5cf6", "#0ea5e9", "#10b981"];

function shortName(name: string): string {
  return name.length > 22 ? name.slice(0, 20) + "…" : name;
}

function buildChartData(
  snapshots: StockSnapshotPoint[],
  itemNames: string[]
): Record<string, string | number>[] {
  const byDate = new Map<string, Record<string, string | number>>();
  for (const s of snapshots) {
    if (!itemNames.includes(s.item_name)) continue;
    if (!byDate.has(s.sim_date)) byDate.set(s.sim_date, { date: s.sim_date });
    byDate.get(s.sim_date)![shortName(s.item_name)] = s.qty_on_hand;
  }
  return [...byDate.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([, row]) => row);
}

export default function Dashboard() {
  const [apiStatus, setApiStatus] = useState<"checking" | "ok" | "down">("checking");
  const [items, setItems] = useState<ItemListOut[]>([]);
  const [orders, setOrders] = useState<POListItem[]>([]);
  const [expiring, setExpiring] = useState<ExpiringBatchOut[]>([]);
  const [snapshots, setSnapshots] = useState<StockSnapshotPoint[]>([]);
  const [flashingIds, setFlashingIds] = useState<Set<number>>(new Set());
  const prevStock = useRef<Map<number, number>>(new Map());
  const [qrLoading, setQrLoading] = useState(false);

  const loadHistory = useCallback(() => {
    api.stockHistory().then((r) => setSnapshots(r.snapshots)).catch(() => {});
  }, []);

  // Items poll every 3 seconds with row-flash on changes
  useEffect(() => {
    const pollItems = () => {
      api.items().then((newItems) => {
        const freshFlash = new Set<number>();
        for (const item of newItems) {
          const prev = prevStock.current.get(item.id);
          if (prev !== undefined && prev !== item.total_stock) {
            freshFlash.add(item.id);
          }
        }
        prevStock.current = new Map(newItems.map((i) => [i.id, i.total_stock]));
        setItems(newItems);
        if (freshFlash.size > 0) {
          setFlashingIds((prev) => new Set([...prev, ...freshFlash]));
          setTimeout(() => {
            setFlashingIds((prev) => {
              const next = new Set(prev);
              freshFlash.forEach((id) => next.delete(id));
              return next;
            });
          }, 2000);
        }
      }).catch(() => {});
    };

    pollItems();
    const interval = setInterval(pollItems, 3000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
    fetch(`${base}/health`)
      .then((r) => setApiStatus(r.ok ? "ok" : "down"))
      .catch(() => setApiStatus("down"));

    api.orders().then(setOrders).catch(() => {});
    api.expiring(14).then(setExpiring).catch(() => {});
    loadHistory();
  }, [loadHistory]);

  const printQrLabels = async () => {
    const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
    setQrLoading(true);
    try {
      const res = await fetch(`${base}/items/qr-labels`);
      if (!res.ok) throw new Error(`${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "qr-labels.pdf";
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      alert("Failed to download QR labels");
    } finally {
      setQrLoading(false);
    }
  };

  const critical = items.filter((i) => i.status === "critical").length;
  const low = items.filter((i) => i.status === "low").length;
  const openOrders = orders.filter((o) =>
    ["draft", "pending_approval", "sent"].includes(o.status)
  ).length;

  const stats = [
    { label: "Total items", value: items.length || "—" },
    { label: "Critical stock", value: critical || "—", urgent: critical > 0 },
    { label: "Low stock", value: low || "—", warn: low > 0 },
    { label: "Open POs", value: openOrders || "—" },
    { label: "Expiring in 14d", value: expiring.length || "—", warn: expiring.length > 0 },
  ];

  const top5 = [...items]
    .filter((i) => i.status !== "adequate")
    .sort((a, b) => {
      const da = a.days_until_stockout ?? Infinity;
      const db2 = b.days_until_stockout ?? Infinity;
      return da - db2;
    })
    .slice(0, 5)
    .map((i) => i.name);

  const chartData = buildChartData(snapshots, top5);
  const hasHistory = chartData.length > 0;

  const statusColor: Record<string, string> = {
    adequate: "text-green-600 dark:text-green-400",
    low: "text-amber-600 dark:text-amber-400",
    critical: "text-destructive",
  };

  return (
    <main className="mx-auto max-w-7xl px-6 py-10 flex flex-col gap-8">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
          <p className="text-muted-foreground text-sm mt-1">Hospital inventory and demand forecasting</p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={printQrLabels}
            disabled={qrLoading}
            className="rounded-lg border border-border bg-background px-3 py-1.5 text-sm font-medium hover:bg-muted disabled:opacity-50 transition-colors"
          >
            {qrLoading ? "Generating…" : "Print QR Labels"}
          </button>
          <Badge variant={apiStatus === "down" ? "destructive" : apiStatus === "ok" ? "secondary" : "outline"}>
            API: {apiStatus === "checking" ? "checking…" : apiStatus}
          </Badge>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
        {stats.map((s) => (
          <Card key={s.label} size="sm">
            <CardHeader>
              <CardTitle className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                {s.label}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <span
                className={`text-2xl font-semibold ${
                  s.urgent ? "text-destructive" : s.warn ? "text-amber-600 dark:text-amber-400" : ""
                }`}
              >
                {String(s.value)}
              </span>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Stock levels table with real-time flash */}
      {items.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Live Stock Levels</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b">
                    <th className="px-4 py-2 text-left font-medium text-muted-foreground">Item</th>
                    <th className="px-4 py-2 text-left font-medium text-muted-foreground">Type</th>
                    <th className="px-4 py-2 text-right font-medium text-muted-foreground">Stock</th>
                    <th className="px-4 py-2 text-left font-medium text-muted-foreground">Status</th>
                    <th className="px-4 py-2 text-right font-medium text-muted-foreground">Days Left</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => (
                    <tr
                      key={item.id}
                      className={`border-b last:border-b-0 transition-colors ${
                        flashingIds.has(item.id) ? "animate-row-flash" : "hover:bg-muted/30"
                      }`}
                    >
                      <td className="px-4 py-2.5 font-medium">
                        <Link href={`/inventory/${item.id}`} className="hover:underline">
                          {item.name}
                        </Link>
                      </td>
                      <td className="px-4 py-2.5 text-muted-foreground capitalize text-xs">{item.type}</td>
                      <td className="px-4 py-2.5 text-right font-mono">
                        {item.total_stock.toLocaleString()}
                      </td>
                      <td className={`px-4 py-2.5 capitalize text-xs font-medium ${statusColor[item.status] ?? ""}`}>
                        {item.status}
                      </td>
                      <td className="px-4 py-2.5 text-right text-muted-foreground text-xs">
                        {item.days_until_stockout != null ? `${item.days_until_stockout}d` : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Stock depletion chart */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Stock Depletion — Top 5 Critical Items</CardTitle>
        </CardHeader>
        <CardContent>
          {hasHistory ? (
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={chartData} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 11 }}
                  tickFormatter={(v: string) => {
                    const d = new Date(v + "T00:00:00");
                    return d.toLocaleDateString("en-AU", { day: "numeric", month: "short" });
                  }}
                />
                <YAxis
                  tick={{ fontSize: 11 }}
                  tickFormatter={(v: number) => v.toLocaleString()}
                  width={56}
                />
                <Tooltip
                  formatter={(value) =>
                    typeof value === "number" ? value.toLocaleString() : String(value ?? "")
                  }
                  labelFormatter={(label) => {
                    if (typeof label !== "string") return String(label ?? "");
                    const d = new Date(label + "T00:00:00");
                    return d.toLocaleDateString("en-AU", { day: "numeric", month: "long", year: "numeric" });
                  }}
                />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                {top5.map((name, i) => (
                  <Line
                    key={name}
                    type="monotone"
                    dataKey={shortName(name)}
                    stroke={LINE_COLORS[i % LINE_COLORS.length]}
                    strokeWidth={2}
                    dot={false}
                    activeDot={{ r: 4 }}
                    connectNulls
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <p className="py-10 text-center text-sm text-muted-foreground">
              No history yet — click{" "}
              <Link href="/simulate" className="underline underline-offset-2">
                Advance Day
              </Link>{" "}
              to start recording stock snapshots.
            </p>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <QuickLink href="/history" title="Live History" desc="Real-time transaction feed with AI anomaly detection" />
        <QuickLink href="/inventory" title="Inventory" desc="View all items, stock levels and batch details" />
        <QuickLink href="/forecast" title="Demand Forecast" desc="Protocol-driven demand from active treatment plans" />
        <QuickLink href="/orders" title="Purchase Orders" desc="Generate, approve and receive AI-drafted POs" />
        <QuickLink href="/expiring" title="Expiring Batches" desc="Batches expiring within the next 14 days" />
        <QuickLink href="/simulate" title="Simulate" desc="Advance one day to run scheduled dispensing" />
      </div>

      {critical > 0 && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
          <strong>{critical} item{critical > 1 ? "s" : ""}</strong> with critical stock levels — consider{" "}
          <Link href="/orders" className="underline underline-offset-2">generating a purchase order</Link>.
        </div>
      )}
    </main>
  );
}

function QuickLink({ href, title, desc }: { href: string; title: string; desc: string }) {
  return (
    <Link href={href} className="block">
      <Card className="h-full transition-shadow hover:shadow-md cursor-pointer">
        <CardHeader>
          <CardTitle className="text-sm">{title}</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-xs text-muted-foreground">{desc}</p>
        </CardContent>
      </Card>
    </Link>
  );
}
