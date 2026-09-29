"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { api, type ItemListOut, type ItemStatus } from "@/lib/api";

function StatusBadge({ status }: { status: ItemStatus }) {
  if (status === "critical")
    return <Badge variant="destructive">Critical</Badge>;
  if (status === "low")
    return (
      <Badge variant="outline" className="border-amber-500 text-amber-600 dark:text-amber-400">
        Low
      </Badge>
    );
  return <Badge variant="secondary">Adequate</Badge>;
}

export default function InventoryPage() {
  const [items, setItems] = useState<ItemListOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.items()
      .then(setItems)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  return (
    <main className="mx-auto max-w-7xl px-6 py-8">
      <h1 className="text-xl font-semibold mb-6">Inventory</h1>

      {loading && <p className="text-muted-foreground text-sm">Loading…</p>}
      {error && <p className="text-destructive text-sm">{error}</p>}

      {!loading && !error && (
        <div className="rounded-xl border overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-muted-foreground">
              <tr>
                <Th>Name</Th>
                <Th>Type</Th>
                <Th right>Total Stock</Th>
                <Th>Unit</Th>
                <Th>Status</Th>
                <Th right>Days Until Stockout</Th>
                <Th>Default Supplier</Th>
                <Th></Th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {items.map((item) => (
                <tr key={item.id} className="hover:bg-muted/30 transition-colors">
                  <Td>
                    <Link
                      href={`/inventory/${item.id}`}
                      className="font-medium hover:underline underline-offset-2"
                    >
                      {item.name}
                    </Link>
                  </Td>
                  <Td>
                    <span className="capitalize text-muted-foreground">{item.type}</span>
                  </Td>
                  <Td right>
                    <span className={item.status === "critical" ? "text-destructive font-medium" : ""}>
                      {item.total_stock.toLocaleString()}
                    </span>
                  </Td>
                  <Td>{item.unit}</Td>
                  <Td>
                    <StatusBadge status={item.status} />
                  </Td>
                  <Td right>
                    {item.days_until_stockout != null
                      ? `${item.days_until_stockout}d`
                      : <span className="text-muted-foreground">—</span>}
                  </Td>
                  <Td>
                    {item.default_supplier_name ?? <span className="text-muted-foreground">—</span>}
                  </Td>
                  <Td>
                    <a
                      href={`/scan/display?item_id=${item.id}`}
                      target="_blank"
                      rel="noreferrer"
                      className="text-xs text-muted-foreground hover:text-foreground underline underline-offset-2 whitespace-nowrap"
                    >
                      Show QR
                    </a>
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
          {items.length === 0 && (
            <p className="text-center text-muted-foreground py-10 text-sm">No items found.</p>
          )}
        </div>
      )}
    </main>
  );
}

function Th({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return (
    <th className={`px-4 py-3 font-medium text-xs uppercase tracking-wide ${right ? "text-right" : "text-left"}`}>
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
