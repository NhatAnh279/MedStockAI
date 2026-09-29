"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import type { AnomalyCheckOut, ItemDetailOut } from "@/lib/api";

// Use the device's hostname so QR → scan works from any device on the LAN
function scanApiBase(): string {
  if (typeof window !== "undefined") {
    return `${window.location.protocol}//${window.location.hostname}:8000`;
  }
  return process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
}

const DEPARTMENTS = [
  "Pharmacy",
  "Ward A",
  "Ward B",
  "ICU",
  "Emergency",
  "Oncology Day Unit",
];

type Action = "dispense" | "receive" | "waste";

function ScanContent() {
  const params = useSearchParams();
  const itemId = Number(params.get("item_id"));
  const batchId = params.get("batch_id") ? Number(params.get("batch_id")) : undefined;
  const lotNo = params.get("lot_no") ?? undefined;

  const [item, setItem] = useState<ItemDetailOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [department, setDepartment] = useState("Pharmacy");
  const [action, setAction] = useState<Action>("dispense");
  const [qty, setQty] = useState(1);

  const [checking, setChecking] = useState(false);
  const [anomaly, setAnomaly] = useState<AnomalyCheckOut | null>(null);
  const [reason, setReason] = useState("");
  const [logging, setLogging] = useState(false);

  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const showToast = (msg: string, ok = true) => {
    if (toastTimer.current) clearTimeout(toastTimer.current);
    setToast({ msg, ok });
    toastTimer.current = setTimeout(() => setToast(null), 4000);
  };

  useEffect(() => {
    if (!itemId) {
      setError("No item_id in URL");
      setLoading(false);
      return;
    }
    fetch(`${scanApiBase()}/items/${itemId}`)
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status}`);
        return r.json() as Promise<ItemDetailOut>;
      })
      .then((data) => setItem(data))
      .catch(() => setError("Failed to load item — check WiFi connection"))
      .finally(() => setLoading(false));
  }, [itemId]);

  // Resolve which batch to use
  const activeBatch = item?.batches.find((b) => b.id === batchId) ?? item?.batches[0] ?? null;

  const handleConfirm = async () => {
    if (!item) return;
    setChecking(true);
    try {
      const res = await fetch(`${scanApiBase()}/scan/check-anomaly`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          item_id: item.id,
          batch_id: activeBatch?.id,
          qty,
          action,
          department,
        }),
      });
      const result: AnomalyCheckOut = await res.json();
      if (result.status === "normal") {
        await logTransaction(result);
      } else {
        setAnomaly(result);
      }
    } catch {
      showToast("Connection error — try again", false);
    } finally {
      setChecking(false);
    }
  };

  const logTransaction = async (anomalyResult: AnomalyCheckOut, overrideReason?: string) => {
    if (!item) return;
    setLogging(true);
    try {
      const res = await fetch(`${scanApiBase()}/scan/log`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          item_id: item.id,
          batch_id: activeBatch?.id,
          qty,
          action,
          department,
          anomaly_status: anomalyResult.status,
          anomaly_message: anomalyResult.message,
          dispense_reason: overrideReason || undefined,
        }),
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(txt);
      }
      const logs = await res.json();
      const totalQty = logs.reduce((s: number, l: { qty_delta: number }) => s + Math.abs(l.qty_delta), 0);
      showToast(`✓ ${action.charAt(0).toUpperCase() + action.slice(1)}d ${totalQty} × ${item.name}`);
      setAnomaly(null);
      setReason("");
      setQty(1);
      // Refresh item stock
      fetch(`${scanApiBase()}/items/${item.id}`)
        .then((r) => r.json())
        .then(setItem)
        .catch(() => {});
    } catch (e: unknown) {
      showToast(`Error: ${e instanceof Error ? e.message : "unknown"}`, false);
    } finally {
      setLogging(false);
    }
  };

  const handleAnomalyConfirm = async () => {
    if (!anomaly) return;
    await logTransaction(anomaly, reason || undefined);
  };

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-muted-foreground animate-pulse">Loading item…</p>
      </div>
    );
  }

  if (error || !item) {
    return (
      <div className="flex min-h-screen items-center justify-center p-6">
        <div className="text-center">
          <p className="text-destructive text-lg font-medium">{error ?? "Item not found"}</p>
          <p className="text-muted-foreground text-sm mt-2">Scan the QR code again</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-[calc(100vh-3rem)] bg-background p-4 pb-8 flex flex-col gap-5 max-w-lg mx-auto">
      {/* Item name */}
      <div className="pt-2">
        <p className="text-xs font-medium text-muted-foreground uppercase tracking-widest mb-1">
          {item.type}
        </p>
        <h1 className="text-3xl font-bold leading-tight tracking-tight">{item.name}</h1>
      </div>

      {/* Batch info card */}
      {activeBatch ? (
        <div className="rounded-xl border bg-card p-4 grid grid-cols-3 gap-3 text-center">
          <div>
            <p className="text-xs text-muted-foreground">Lot No.</p>
            <p className="font-semibold text-sm mt-0.5">{activeBatch.lot_no}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Expiry</p>
            <p className="font-semibold text-sm mt-0.5">
              {new Date(activeBatch.expiry_date + "T00:00:00").toLocaleDateString("en-AU", {
                day: "numeric",
                month: "short",
                year: "2-digit",
              })}
            </p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">In Stock</p>
            <p className="font-semibold text-sm mt-0.5">
              {item.total_stock.toLocaleString()} {item.unit}
            </p>
          </div>
        </div>
      ) : (
        <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-center">
          <p className="text-destructive text-sm font-medium">No stock available</p>
        </div>
      )}

      {/* Department selector */}
      <div>
        <label className="block text-sm font-medium mb-2">Department</label>
        <select
          value={department}
          onChange={(e) => setDepartment(e.target.value)}
          className="w-full rounded-lg border border-input bg-background px-3 py-3 text-base focus:outline-none focus:ring-2 focus:ring-ring"
        >
          {DEPARTMENTS.map((d) => (
            <option key={d} value={d}>{d}</option>
          ))}
        </select>
      </div>

      {/* Action selector */}
      <div>
        <label className="block text-sm font-medium mb-2">Action</label>
        <div className="grid grid-cols-3 gap-2">
          {(["dispense", "receive", "waste"] as Action[]).map((a) => (
            <button
              key={a}
              onClick={() => setAction(a)}
              className={`rounded-xl border py-3 text-sm font-semibold capitalize transition-colors ${
                action === a
                  ? "bg-primary text-primary-foreground border-primary"
                  : "border-input bg-background hover:bg-muted"
              }`}
            >
              {a}
            </button>
          ))}
        </div>
      </div>

      {/* Quantity stepper */}
      <div>
        <label className="block text-sm font-medium mb-2">Quantity ({item.unit})</label>
        <div className="flex items-center gap-3">
          <button
            onClick={() => setQty((q) => Math.max(1, q - 1))}
            className="w-14 h-14 rounded-xl border border-input bg-background text-2xl font-medium hover:bg-muted active:scale-95 transition-transform flex items-center justify-center"
          >
            −
          </button>
          <input
            type="number"
            min={1}
            value={qty}
            onChange={(e) => setQty(Math.max(1, parseInt(e.target.value) || 1))}
            className="flex-1 h-14 rounded-xl border border-input bg-background text-center text-2xl font-bold focus:outline-none focus:ring-2 focus:ring-ring"
          />
          <button
            onClick={() => setQty((q) => q + 1)}
            className="w-14 h-14 rounded-xl border border-input bg-background text-2xl font-medium hover:bg-muted active:scale-95 transition-transform flex items-center justify-center"
          >
            +
          </button>
        </div>
      </div>

      {/* Confirm button */}
      <button
        onClick={handleConfirm}
        disabled={checking || logging || !activeBatch}
        className="w-full py-4 rounded-xl bg-primary text-primary-foreground text-lg font-semibold disabled:opacity-50 active:scale-[0.98] transition-transform"
      >
        {checking ? "Checking…" : logging ? "Saving…" : `Confirm ${action.charAt(0).toUpperCase() + action.slice(1)}`}
      </button>

      {/* Anomaly modal */}
      {anomaly && (
        <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-4 bg-black/60">
          <div className="w-full max-w-md rounded-2xl bg-background border p-6 shadow-2xl flex flex-col gap-4">
            <div className="flex items-start gap-3">
              <span className="text-3xl">
                {anomaly.status === "alert" ? "🚩" : "⚠️"}
              </span>
              <div>
                <h2 className={`text-lg font-bold ${anomaly.status === "alert" ? "text-destructive" : "text-amber-600"}`}>
                  {anomaly.status === "alert" ? "Alert" : "Unusual Quantity"}
                </h2>
                <p className="text-sm text-muted-foreground mt-1">{anomaly.message}</p>
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium mb-1">
                Reason (required)
              </label>
              <textarea
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="e.g. Monthly bulk dispense for ward stock"
                rows={3}
                className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring resize-none"
              />
            </div>

            <div className="flex gap-3">
              <button
                onClick={() => { setAnomaly(null); setReason(""); }}
                className="flex-1 py-3 rounded-xl border border-input bg-background text-sm font-medium hover:bg-muted"
              >
                Cancel
              </button>
              <button
                onClick={handleAnomalyConfirm}
                disabled={!reason.trim() || logging}
                className="flex-1 py-3 rounded-xl bg-primary text-primary-foreground text-sm font-semibold disabled:opacity-50"
              >
                {logging ? "Saving…" : "Confirm with Reason"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Toast */}
      {toast && (
        <div
          className={`fixed bottom-6 left-1/2 -translate-x-1/2 z-50 px-5 py-3 rounded-xl shadow-lg text-sm font-medium text-white transition-all ${
            toast.ok ? "bg-green-600" : "bg-destructive"
          }`}
        >
          {toast.msg}
        </div>
      )}
    </div>
  );
}

export default function ScanPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[calc(100vh-3rem)] items-center justify-center">
          <p className="text-muted-foreground animate-pulse">Loading…</p>
        </div>
      }
    >
      <ScanContent />
    </Suspense>
  );
}
