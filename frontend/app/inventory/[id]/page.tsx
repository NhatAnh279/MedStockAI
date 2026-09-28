"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api, type ItemDetailOut } from "@/lib/api";

export default function ItemDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const [item, setItem] = useState<ItemDetailOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.item(Number(id))
      .then(setItem)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) return <PageShell><p className="text-muted-foreground text-sm">Loading…</p></PageShell>;
  if (error) return <PageShell><p className="text-destructive text-sm">{error}</p></PageShell>;
  if (!item) return null;

  return (
    <PageShell>
      <div className="flex items-center gap-2 text-sm text-muted-foreground mb-6">
        <Link href="/inventory" className="hover:text-foreground">Inventory</Link>
        <span>/</span>
        <span className="text-foreground">{item.name}</span>
      </div>

      <div className="grid gap-4 sm:grid-cols-4 mb-8">
        <Stat label="Total Stock" value={`${item.total_stock.toLocaleString()} ${item.unit}`} />
        <Stat label="Type" value={item.type} />
        <Stat label="Avg Daily Use" value={`${item.avg_daily_consumption} ${item.unit}/day`} />
        <Stat label="Unit Cost" value={`$${item.unit_cost.toFixed(2)}`} />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Batches</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-muted-foreground">
              <tr>
                <Th>Lot No.</Th>
                <Th right>Qty on Hand</Th>
                <Th>Expiry Date</Th>
                <Th>Received At</Th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {item.batches.map((b) => {
                const daysLeft = Math.ceil(
                  (new Date(b.expiry_date).getTime() - Date.now()) / 86_400_000
                );
                const expiringSoon = daysLeft <= 14 && daysLeft >= 0;
                const expired = daysLeft < 0;
                return (
                  <tr key={b.id} className="hover:bg-muted/30">
                    <Td>{b.lot_no}</Td>
                    <Td right>{b.qty_on_hand.toLocaleString()}</Td>
                    <Td>
                      <span className={expired ? "text-destructive" : expiringSoon ? "text-amber-600 dark:text-amber-400" : ""}>
                        {b.expiry_date}
                        {expiringSoon && ` (${daysLeft}d)`}
                        {expired && " (expired)"}
                      </span>
                    </Td>
                    <Td>{new Date(b.received_at).toLocaleDateString()}</Td>
                  </tr>
                );
              })}
              {item.batches.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-4 py-8 text-center text-muted-foreground text-sm">
                    No batches on record.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </PageShell>
  );
}

function PageShell({ children }: { children: React.ReactNode }) {
  return (
    <main className="mx-auto max-w-4xl px-6 py-8">{children}</main>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
          {label}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <span className="font-medium capitalize">{value}</span>
      </CardContent>
    </Card>
  );
}

function Th({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return (
    <th className={`px-4 py-3 text-xs font-medium uppercase tracking-wide ${right ? "text-right" : "text-left"}`}>
      {children}
    </th>
  );
}

function Td({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return (
    <td className={`px-4 py-3 ${right ? "text-right tabular-nums" : ""}`}>
      {children}
    </td>
  );
}
