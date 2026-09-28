"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { api, type ExpiringBatchOut } from "@/lib/api";

const WINDOWS = [7, 14, 30, 60, 90];

export default function ExpiringPage() {
  const [batches, setBatches] = useState<ExpiringBatchOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [days, setDays] = useState(14);

  function load(d: number) {
    setLoading(true);
    setError(null);
    api.expiring(d)
      .then(setBatches)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }

  useEffect(() => { load(days); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function changeDays(d: number) {
    setDays(d);
    load(d);
  }

  return (
    <main className="mx-auto max-w-5xl px-6 py-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold">Expiring Batches</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            {batches.length} batch{batches.length !== 1 ? "es" : ""} expiring within {days} days
          </p>
        </div>
        <div className="flex gap-1">
          {WINDOWS.map((d) => (
            <Button
              key={d}
              size="sm"
              variant={days === d ? "default" : "outline"}
              onClick={() => changeDays(d)}
            >
              {d}d
            </Button>
          ))}
        </div>
      </div>

      {loading && <p className="text-muted-foreground text-sm">Loading…</p>}
      {error && <p className="text-destructive text-sm">{error}</p>}

      {!loading && !error && (
        <div className="rounded-xl border overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-muted-foreground">
              <tr>
                <Th>Item</Th>
                <Th>Lot No.</Th>
                <Th right>Qty on Hand</Th>
                <Th>Expiry Date</Th>
                <Th right>Days Left</Th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {batches.map((b) => (
                <tr key={b.id} className="hover:bg-muted/30">
                  <Td>
                    <Link
                      href={`/inventory/${b.item_id}`}
                      className="font-medium hover:underline underline-offset-2"
                    >
                      {b.item_name}
                    </Link>
                  </Td>
                  <Td>{b.lot_no}</Td>
                  <Td right>{b.qty_on_hand.toLocaleString()}</Td>
                  <Td>{b.expiry_date}</Td>
                  <Td right>
                    <span
                      className={
                        b.days_until_expiry <= 7
                          ? "text-destructive font-semibold"
                          : b.days_until_expiry <= 14
                          ? "text-amber-600 dark:text-amber-400 font-medium"
                          : ""
                      }
                    >
                      {b.days_until_expiry}d
                    </span>
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
          {batches.length === 0 && (
            <p className="text-center text-muted-foreground py-10 text-sm">
              No batches expiring within {days} days.
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
