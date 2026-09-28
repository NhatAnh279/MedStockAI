"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api, type POListItem, type POStatus } from "@/lib/api";

function StatusBadge({ status }: { status: POStatus }) {
  const map: Record<POStatus, { label: string; variant: "default" | "secondary" | "outline" | "destructive" }> = {
    draft: { label: "Draft", variant: "outline" },
    pending_approval: { label: "Pending", variant: "outline" },
    sent: { label: "Sent", variant: "secondary" },
    confirmed: { label: "Confirmed", variant: "default" },
    received: { label: "Received", variant: "secondary" },
    cancelled: { label: "Cancelled", variant: "destructive" },
  };
  const { label, variant } = map[status] ?? { label: status, variant: "outline" as const };
  return <Badge variant={variant}>{label}</Badge>;
}

export default function OrdersPage() {
  const [orders, setOrders] = useState<POListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [genMsg, setGenMsg] = useState<string | null>(null);

  function loadOrders() {
    api.orders()
      .then(setOrders)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }

  useEffect(() => { loadOrders(); }, []);

  async function handleGenerate() {
    setGenerating(true);
    setGenMsg(null);
    try {
      const result = await api.generateOrders();
      setGenMsg(
        result.created > 0
          ? `Created ${result.created} PO${result.created > 1 ? "s" : ""} (IDs: ${result.po_ids.join(", ")}).`
          : "No new orders needed — all items are adequately stocked."
      );
      loadOrders();
    } catch (e) {
      setGenMsg(`Error: ${(e as Error).message}`);
    } finally {
      setGenerating(false);
    }
  }

  return (
    <main className="mx-auto max-w-7xl px-6 py-8">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-semibold">Purchase Orders</h1>
        <Button onClick={handleGenerate} disabled={generating}>
          {generating ? "Generating…" : "Generate POs"}
        </Button>
      </div>

      {genMsg && (
        <div className="mb-4 rounded-lg border px-4 py-3 text-sm bg-muted/50">
          {genMsg}
        </div>
      )}

      {loading && <p className="text-muted-foreground text-sm">Loading…</p>}
      {error && <p className="text-destructive text-sm">{error}</p>}

      {!loading && !error && (
        <div className="rounded-xl border overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-muted-foreground">
              <tr>
                <Th>PO #</Th>
                <Th>Supplier</Th>
                <Th>Status</Th>
                <Th>Created By</Th>
                <Th right>Lines</Th>
                <Th right>Total</Th>
                <Th>Created</Th>
                <Th>Backup Of</Th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {orders.map((po) => (
                <tr key={po.id} className="hover:bg-muted/30">
                  <Td>
                    <Link
                      href={`/orders/${po.id}`}
                      className="font-medium hover:underline underline-offset-2"
                    >
                      #{po.id}
                    </Link>
                  </Td>
                  <Td>{po.supplier_name}</Td>
                  <Td><StatusBadge status={po.status} /></Td>
                  <Td>
                    <span className={`capitalize ${po.created_by === "ai" ? "text-muted-foreground" : ""}`}>
                      {po.created_by}
                    </span>
                  </Td>
                  <Td right>{po.line_count}</Td>
                  <Td right>${po.total.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</Td>
                  <Td>{new Date(po.created_at).toLocaleDateString()}</Td>
                  <Td>
                    {po.backup_of_po_id ? (
                      <Link href={`/orders/${po.backup_of_po_id}`} className="hover:underline underline-offset-2 text-muted-foreground">
                        #{po.backup_of_po_id}
                      </Link>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
          {orders.length === 0 && (
            <p className="text-center text-muted-foreground py-10 text-sm">
              No purchase orders yet. Click &quot;Generate POs&quot; to create AI-drafted orders.
            </p>
          )}
        </div>
      )}
    </main>
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
