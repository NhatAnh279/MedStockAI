"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api, type ItemListOut, type POListItem, type ExpiringBatchOut } from "@/lib/api";

export default function Dashboard() {
  const [apiStatus, setApiStatus] = useState<"checking" | "ok" | "down">("checking");
  const [items, setItems] = useState<ItemListOut[]>([]);
  const [orders, setOrders] = useState<POListItem[]>([]);
  const [expiring, setExpiring] = useState<ExpiringBatchOut[]>([]);

  useEffect(() => {
    const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
    fetch(`${base}/health`)
      .then((r) => setApiStatus(r.ok ? "ok" : "down"))
      .catch(() => setApiStatus("down"));

    api.items().then(setItems).catch(() => {});
    api.orders().then(setOrders).catch(() => {});
    api.expiring(14).then(setExpiring).catch(() => {});
  }, []);

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
