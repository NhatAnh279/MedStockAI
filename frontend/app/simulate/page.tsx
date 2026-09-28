"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api, type SimulateResult } from "@/lib/api";

export default function SimulatePage() {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<SimulateResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleAdvance() {
    setLoading(true);
    setError(null);
    try {
      const r = await api.advanceDay();
      setResult(r);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto max-w-3xl px-6 py-8">
      <h1 className="text-xl font-semibold mb-2">Simulate</h1>
      <p className="text-muted-foreground text-sm mb-6">
        Advance one calendar day — runs all due treatment plans and dispenses
        medications via FEFO. Use this to generate consumption history for
        forecasting.
      </p>

      <Button onClick={handleAdvance} disabled={loading} size="lg">
        {loading ? "Processing…" : "Advance One Day"}
      </Button>

      {error && (
        <p className="mt-4 text-destructive text-sm">{error}</p>
      )}

      {result && (
        <div className="mt-8 flex flex-col gap-4">
          <div className="grid grid-cols-3 gap-4">
            <Stat label="Date Processed" value={result.date_processed} />
            <Stat label="Plans Processed" value={String(result.plans_processed)} />
            <Stat label="Units Dispensed" value={result.total_qty_dispensed.toLocaleString()} />
          </div>

          {result.lines_dispensed.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">Dispense Log</CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <table className="w-full text-sm">
                  <thead className="bg-muted/50 text-muted-foreground">
                    <tr>
                      <Th>Item</Th>
                      <Th>Patient</Th>
                      <Th right>Qty Dispensed</Th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {result.lines_dispensed.map((l, i) => (
                      <tr key={i} className="hover:bg-muted/30">
                        <Td>{l.item_name}</Td>
                        <Td>{l.patient_name}</Td>
                        <Td right>{l.qty_dispensed.toLocaleString()}</Td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </CardContent>
            </Card>
          )}

          {result.plans_processed === 0 && (
            <p className="text-sm text-muted-foreground">
              No treatment plans were due today.
            </p>
          )}
        </div>
      )}
    </main>
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
        <span className="font-semibold">{value}</span>
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
