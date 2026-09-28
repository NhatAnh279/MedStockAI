"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
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

// Short label for the chart legend — strip dosage/units suffix
function shortName(name: string): string {
  return name.length > 22 ? name.slice(0, 20) + "…" : name;
}

// Recharts data: [{date, "Item A": 123, "Item B": 456}, ...]
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

  const loadHistory = useCallback(() => {
    api.stockHistory().then((r) => setSnapshots(r.snapshots)).catch(() => {});
  }, []);

  useEffect(() => {
    const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
    fetch(`${base}/health`)
      .then((r) => setApiStatus(r.ok ? "ok" : "down"))
      .catch(() => setApiStatus("down"));

    api.items().then(setItems).catch(() => {});
    api.orders().then(setOrders).catch(() => {});
    api.expiring(14).then(setExpiring).catch(() => {});
    loadHistory();
  }, [loadHistory]);

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

  // Top 5 critical/low items by urgency to track in the chart
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

  return (
    <main className="mx-auto max-w-7xl px-6 py-10 flex flex-col gap-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
          <p className="text-muted-foreground text-sm mt-1">Hospital inventory and demand forecasting</p>
        </div>
        <Badge variant={apiStatus === "down" ? "destructive" : apiStatus === "ok" ? "secondary" : "outline"}>
          API: {apiStatus === "checking" ? "checking…" : apiStatus}
        </Badge>
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
