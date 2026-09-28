"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api, type POOut, type POStatus } from "@/lib/api";

function StatusBadge({ status }: { status: POStatus }) {
  const map: Record<POStatus, { label: string; variant: "default" | "secondary" | "outline" | "destructive" }> = {
    draft: { label: "Draft", variant: "outline" },
    pending_approval: { label: "Pending Approval", variant: "outline" },
    sent: { label: "Sent", variant: "secondary" },
    confirmed: { label: "Confirmed", variant: "default" },
    received: { label: "Received", variant: "secondary" },
    cancelled: { label: "Cancelled", variant: "destructive" },
  };
  const { label, variant } = map[status] ?? { label: status, variant: "outline" as const };
  return <Badge variant={variant}>{label}</Badge>;
}

export default function OrderDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const [po, setPo] = useState<POOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState(false);
  const [actionMsg, setActionMsg] = useState<string | null>(null);

  function loadPo() {
    setLoading(true);
    api.order(Number(id))
      .then(setPo)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }

  useEffect(() => { loadPo(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function handleApprove() {
    setActionLoading(true);
    setActionMsg(null);
    try {
      const updated = await api.approveOrder(Number(id));
      setPo(updated);
      setActionMsg("PO approved and sent. Supplier reply received.");
    } catch (e) {
      setActionMsg(`Error: ${(e as Error).message}`);
    } finally {
      setActionLoading(false);
    }
  }

  async function handleReceive() {
    setActionLoading(true);
    setActionMsg(null);
    try {
      const result = await api.receiveOrder(Number(id));
      setPo(result.po);
      setActionMsg(`Received ${result.units_received.toLocaleString()} units into stock.`);
    } catch (e) {
      setActionMsg(`Error: ${(e as Error).message}`);
    } finally {
      setActionLoading(false);
    }
  }

  if (loading) return <PageShell><p className="text-muted-foreground text-sm">Loading…</p></PageShell>;
  if (error) return <PageShell><p className="text-destructive text-sm">{error}</p></PageShell>;
  if (!po) return null;

  const canApprove = ["draft", "pending_approval"].includes(po.status);
  const canReceive = ["sent", "confirmed"].includes(po.status) &&
    po.reply_parsed?.status !== "rejected";

  return (
    <PageShell>
      <div className="flex items-center gap-2 text-sm text-muted-foreground mb-6">
        <Link href="/orders" className="hover:text-foreground">Purchase Orders</Link>
        <span>/</span>
        <span className="text-foreground">PO #{po.id}</span>
      </div>

      <div className="flex items-start justify-between gap-4 mb-6 flex-wrap">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <h1 className="text-xl font-semibold">PO #{po.id}</h1>
            <StatusBadge status={po.status} />
          </div>
          <p className="text-sm text-muted-foreground">
            {po.supplier.name} · Created by {po.created_by} on{" "}
            {new Date(po.created_at).toLocaleString()}
          </p>
        </div>
        <div className="flex gap-2">
          {canApprove && (
            <Button onClick={handleApprove} disabled={actionLoading}>
              {actionLoading ? "Processing…" : "Approve & Send"}
            </Button>
          )}
          {canReceive && (
            <Button onClick={handleReceive} disabled={actionLoading} variant="secondary">
              {actionLoading ? "Processing…" : "Receive Delivery"}
            </Button>
          )}
        </div>
      </div>

      {actionMsg && (
        <div className="mb-4 rounded-lg border px-4 py-3 text-sm bg-muted/50">
          {actionMsg}
        </div>
      )}

      {po.backup_of_po_id && (
        <div className="mb-4 text-sm text-muted-foreground">
          Backup order for{" "}
          <Link href={`/orders/${po.backup_of_po_id}`} className="hover:underline">
            PO #{po.backup_of_po_id}
          </Link>
        </div>
      )}
      {po.backup_po_id && (
        <div className="mb-4 text-sm text-muted-foreground">
          Shortfall covered by{" "}
          <Link href={`/orders/${po.backup_po_id}`} className="hover:underline">
            backup PO #{po.backup_po_id}
          </Link>
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-3 mb-6">
        <Stat label="Total" value={`$${po.total.toLocaleString(undefined, { minimumFractionDigits: 2 })}`} />
        <Stat label="Supplier" value={po.supplier.name} />
        <Stat label="Lead Time" value={`${po.supplier.lead_time_days} days`} />
      </div>

      <Card className="mb-6">
        <CardHeader>
          <CardTitle className="text-sm">Order Lines</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-muted-foreground">
              <tr>
                <Th>Item</Th>
                <Th right>Qty</Th>
                <Th right>Unit Price</Th>
                <Th right>Line Total</Th>
                <Th>Rationale</Th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {po.lines.map((line) => (
                <tr key={line.id} className="hover:bg-muted/30">
                  <Td>
                    <Link href={`/inventory/${line.item_id}`} className="hover:underline">
                      {line.item_name}
                    </Link>
                  </Td>
                  <Td right>{line.qty.toLocaleString()}</Td>
                  <Td right>${line.unit_price.toFixed(2)}</Td>
                  <Td right>${line.line_total.toLocaleString(undefined, { minimumFractionDigits: 2 })}</Td>
                  <Td>
                    {line.rationale ? (
                      <span className="text-xs text-muted-foreground">{line.rationale}</span>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>

      {po.supplier_reply && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm flex items-center gap-2">
              Supplier Reply
              {po.reply_parsed && (
                <Badge
                  variant={
                    po.reply_parsed.status === "full"
                      ? "default"
                      : po.reply_parsed.status === "partial"
                      ? "outline"
                      : "destructive"
                  }
                >
                  {String(po.reply_parsed.status)}
                </Badge>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="text-xs bg-muted/50 rounded p-3 whitespace-pre-wrap leading-relaxed">
              {po.supplier_reply}
            </pre>
          </CardContent>
        </Card>
      )}
    </PageShell>
  );
}

function PageShell({ children }: { children: React.ReactNode }) {
  return <main className="mx-auto max-w-5xl px-6 py-8">{children}</main>;
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
        <span className="font-medium">{value}</span>
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
