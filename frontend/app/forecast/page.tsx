"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api, type ForecastItemOut } from "@/lib/api";

const HORIZONS = [7, 14, 30, 60, 90];

export default function ForecastPage() {
  const [data, setData] = useState<ForecastItemOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [horizon, setHorizon] = useState(30);

  function load(h: number) {
    setLoading(true);
    setError(null);
    api.forecast(h)
      .then(setData)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }

  useEffect(() => { load(horizon); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function changeHorizon(h: number) {
    setHorizon(h);
    load(h);
  }

  return (
    <main className="mx-auto max-w-7xl px-6 py-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-semibold">Demand Forecast</h1>
        <div className="flex gap-1">
          {HORIZONS.map((h) => (
            <Button
              key={h}
              size="sm"
              variant={horizon === h ? "default" : "outline"}
              onClick={() => changeHorizon(h)}
            >
              {h}d
            </Button>
          ))}
        </div>
      </div>

      {loading && <p className="text-muted-foreground text-sm">Running forecast…</p>}
      {error && <p className="text-destructive text-sm">{error}</p>}

      {!loading && !error && (
        <div className="rounded-xl border overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-muted-foreground">
              <tr>
                <Th>Item</Th>
                <Th right>A (Scheduled)</Th>
                <Th right>B (Baseline)</Th>
                <Th right>C (New Intake)</Th>
                <Th right>Total Demand</Th>
                <Th right>Usable Stock</Th>
                <Th right>On Order</Th>
                <Th right>ROP</Th>
                <Th right>Order Qty</Th>
                <Th right>Days Until Stockout</Th>
                <Th>Needs Order</Th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {data.map((row) => (
                <tr key={row.item_id} className="hover:bg-muted/30">
                  <Td>
                    <span className="font-medium">{row.item_name}</span>
                  </Td>
                  <Td right>{row.demand.A_scheduled.toFixed(1)}</Td>
                  <Td right>{row.demand.B_baseline.toFixed(1)}</Td>
                  <Td right>{row.demand.C_new_intake.toFixed(1)}</Td>
                  <Td right>
                    <strong>{row.demand.total.toFixed(1)}</strong>
                  </Td>
                  <Td right>{row.usable_stock.toLocaleString()}</Td>
                  <Td right>{row.qty_on_order.toLocaleString()}</Td>
                  <Td right>{row.ROP.toFixed(1)}</Td>
                  <Td right>
                    {row.order_qty > 0 ? (
                      <span className="font-semibold">{row.order_qty.toLocaleString()}</span>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </Td>
                  <Td right>
                    {row.days_until_stockout != null ? (
                      <span
                        className={
                          row.days_until_stockout < 7
                            ? "text-destructive font-medium"
                            : row.days_until_stockout < 30
                            ? "text-amber-600 dark:text-amber-400"
                            : ""
                        }
                      >
                        {row.days_until_stockout.toFixed(1)}d
                      </span>
                    ) : (
                      <span className="text-muted-foreground">∞</span>
                    )}
                  </Td>
                  <Td>
                    {row.needs_order ? (
                      <Badge variant="destructive">Yes</Badge>
                    ) : (
                      <Badge variant="secondary">No</Badge>
                    )}
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.length === 0 && (
            <p className="text-center text-muted-foreground py-10 text-sm">No forecast data.</p>
          )}
        </div>
      )}
    </main>
  );
}

function Th({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return (
    <th className={`px-3 py-3 text-xs font-medium uppercase tracking-wide whitespace-nowrap ${right ? "text-right" : "text-left"}`}>
      {children}
    </th>
  );
}

function Td({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return (
    <td className={`px-3 py-3 ${right ? "text-right tabular-nums" : ""}`}>
      {children}
    </td>
  );
}
