"use client";

import { useEffect, useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  api,
  errorMessage,
  type ExtractedProtocol,
  type ExtractedProtocolItem,
  type ItemListOut,
  type SavedProtocol,
} from "@/lib/api";

const MAX_BYTES = 10 * 1024 * 1024;

const inputCls =
  "h-8 rounded-lg border bg-background px-2 text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50";

export default function ProtocolUploadPage() {
  const [inventory, setInventory] = useState<ItemListOut[]>([]);
  const [protocols, setProtocols] = useState<ExtractedProtocol[] | null>(null);
  const [filename, setFilename] = useState("");
  const [extracting, setExtracting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<SavedProtocol[] | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.items().then(setInventory).catch((e) => setError(errorMessage(e)));
  }, []);

  async function onFile(file: File | undefined) {
    if (!file) return;
    setError(null);
    setSaved(null);
    setProtocols(null);
    if (file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf")) {
      setError("Only PDF files are accepted.");
      return;
    }
    if (file.size > MAX_BYTES) {
      setError("PDF is larger than the 10 MB limit.");
      return;
    }
    setExtracting(true);
    try {
      const preview = await api.uploadProtocol(file);
      setFilename(preview.filename);
      setProtocols(preview.protocols);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setExtracting(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  function updateProtocol(pi: number, patch: Partial<ExtractedProtocol>) {
    setProtocols((prev) => prev && prev.map((p, i) => (i === pi ? { ...p, ...patch } : p)));
  }

  function updateItem(pi: number, ii: number, patch: Partial<ExtractedProtocolItem>) {
    setProtocols(
      (prev) =>
        prev &&
        prev.map((p, i) =>
          i === pi ? { ...p, items: p.items.map((it, j) => (j === ii ? { ...it, ...patch } : it)) } : p
        )
    );
  }

  function removeItem(pi: number, ii: number) {
    setProtocols(
      (prev) =>
        prev && prev.map((p, i) => (i === pi ? { ...p, items: p.items.filter((_, j) => j !== ii) } : p))
    );
  }

  function problems(ps: ExtractedProtocol[]): string | null {
    for (const p of ps) {
      const label = `"${p.name || "Untitled protocol"}"`;
      if (!p.name.trim() || !p.icd_code.trim() || !p.phase.trim())
        return `${label}: name, ICD-10 code and phase are required.`;
      if (!(p.cycle_length_days >= 1)) return `${label}: cycle length must be at least 1 day.`;
      if (p.items.length === 0) return `${label} has no items.`;
      for (const it of p.items) {
        if (it.item_id == null) return `${label}: choose an inventory item for "${it.item_name}" (or remove the row).`;
        if (!(it.qty_per_cycle >= 1)) return `${label}: quantity per cycle must be at least 1 for "${it.item_name}".`;
      }
      const ids = p.items.map((i) => i.item_id);
      if (new Set(ids).size !== ids.length) return `${label} lists the same inventory item more than once.`;
    }
    return null;
  }

  async function confirm() {
    if (!protocols) return;
    const problem = problems(protocols);
    if (problem) {
      setError(problem);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const r = await api.confirmProtocols(protocols);
      setSaved(r.saved);
      setProtocols(null);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="mx-auto max-w-5xl px-6 py-8">
      <h1 className="text-xl font-semibold mb-2">Upload Treatment Protocol</h1>
      <p className="text-muted-foreground text-sm mb-6">
        Upload a protocol PDF (max 10 MB). Claude extracts the phases and the items needed per
        cycle; review and edit them below, then confirm to save.
      </p>

      <div className="flex items-center gap-3">
        <input
          ref={fileRef}
          type="file"
          accept="application/pdf,.pdf"
          className="hidden"
          onChange={(e) => onFile(e.target.files?.[0])}
        />
        <Button onClick={() => fileRef.current?.click()} disabled={extracting || saving}>
          {extracting ? "Reading PDF…" : "Choose PDF"}
        </Button>
        {extracting && (
          <span className="text-sm text-muted-foreground">This can take up to a minute.</span>
        )}
      </div>

      {error && <p className="mt-4 text-destructive text-sm">{error}</p>}

      {saved && (
        <Card className="mt-6">
          <CardHeader>
            <CardTitle className="text-sm">Saved</CardTitle>
          </CardHeader>
          <CardContent className="text-sm flex flex-col gap-1">
            {saved.map((s) => (
              <p key={s.id}>
                <span className="font-medium">{s.name}</span>{" "}
                <span className="text-muted-foreground">
                  — {s.item_count} item{s.item_count === 1 ? "" : "s"}
                </span>
              </p>
            ))}
            <p className="text-muted-foreground mt-2">
              These protocols feed the forecast once patients are enrolled on them.
            </p>
          </CardContent>
        </Card>
      )}

      {protocols && (
        <div className="mt-6 flex flex-col gap-6">
          <p className="text-sm text-muted-foreground">
            Extracted from <span className="font-medium text-foreground">{filename}</span> —{" "}
            {protocols.length} protocol{protocols.length === 1 ? "" : "s"}. Nothing is saved until
            you confirm.
          </p>

          {protocols.map((p, pi) => (
            <Card key={pi}>
              <CardHeader>
                <CardTitle className="text-sm">Protocol {pi + 1}</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-4">
                <div className="grid grid-cols-2 gap-3 md:grid-cols-6">
                  <Field label="Name" className="col-span-2 md:col-span-3">
                    <input
                      className={`${inputCls} w-full`}
                      value={p.name}
                      maxLength={200}
                      onChange={(e) => updateProtocol(pi, { name: e.target.value })}
                    />
                  </Field>
                  <Field label="ICD-10">
                    <input
                      className={`${inputCls} w-full`}
                      value={p.icd_code}
                      maxLength={10}
                      onChange={(e) => updateProtocol(pi, { icd_code: e.target.value })}
                    />
                  </Field>
                  <Field label="Phase">
                    <input
                      className={`${inputCls} w-full`}
                      value={p.phase}
                      maxLength={50}
                      onChange={(e) => updateProtocol(pi, { phase: e.target.value })}
                    />
                  </Field>
                  <div className="grid grid-cols-2 gap-3 col-span-2 md:col-span-6 md:max-w-xs">
                    <Field label="Cycle (days)">
                      <input
                        type="number"
                        min={1}
                        className={`${inputCls} w-full`}
                        value={p.cycle_length_days}
                        onChange={(e) =>
                          updateProtocol(pi, { cycle_length_days: Number(e.target.value) })
                        }
                      />
                    </Field>
                    <Field label="Total cycles">
                      <input
                        type="number"
                        min={1}
                        placeholder="ongoing"
                        className={`${inputCls} w-full`}
                        value={p.total_cycles ?? ""}
                        onChange={(e) =>
                          updateProtocol(pi, {
                            total_cycles: e.target.value === "" ? null : Number(e.target.value),
                          })
                        }
                      />
                    </Field>
                  </div>
                </div>

                <div className="rounded-xl border overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-muted/50 text-muted-foreground">
                      <tr>
                        <Th>Inventory item</Th>
                        <Th>Dosage (from PDF)</Th>
                        <Th right>Qty / cycle</Th>
                        <Th right>Per kg</Th>
                        <Th />
                      </tr>
                    </thead>
                    <tbody className="divide-y">
                      {p.items.map((it, ii) => (
                        <tr key={ii} className={it.item_id == null ? "bg-amber-500/10" : ""}>
                          <td className="px-3 py-2">
                            <select
                              className={`${inputCls} w-full min-w-64`}
                              value={it.item_id ?? ""}
                              onChange={(e) =>
                                updateItem(pi, ii, {
                                  item_id: e.target.value === "" ? null : Number(e.target.value),
                                })
                              }
                            >
                              <option value="">— select item —</option>
                              {inventory.map((inv) => (
                                <option key={inv.id} value={inv.id}>
                                  {inv.name} ({inv.unit})
                                </option>
                              ))}
                            </select>
                            {it.item_id == null && (
                              <Badge variant="secondary" className="mt-1">
                                No match for “{it.item_name}”
                              </Badge>
                            )}
                          </td>
                          <td className="px-3 py-2 text-muted-foreground">{it.dosage}</td>
                          <td className="px-3 py-2 text-right">
                            <input
                              type="number"
                              min={1}
                              className={`${inputCls} w-24 text-right tabular-nums`}
                              value={it.qty_per_cycle}
                              onChange={(e) =>
                                updateItem(pi, ii, { qty_per_cycle: Number(e.target.value) })
                              }
                            />
                          </td>
                          <td className="px-3 py-2 text-right">
                            <input
                              type="number"
                              min={0}
                              step="any"
                              placeholder="—"
                              className={`${inputCls} w-20 text-right tabular-nums`}
                              value={it.dose_per_kg ?? ""}
                              onChange={(e) =>
                                updateItem(pi, ii, {
                                  dose_per_kg: e.target.value === "" ? null : Number(e.target.value),
                                })
                              }
                            />
                          </td>
                          <td className="px-3 py-2 text-right">
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => removeItem(pi, ii)}
                              aria-label={`Remove ${it.item_name}`}
                            >
                              Remove
                            </Button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {p.items.length === 0 && (
                    <p className="text-center text-muted-foreground py-6 text-sm">No items.</p>
                  )}
                </div>
              </CardContent>
            </Card>
          ))}

          <div className="flex gap-2">
            <Button onClick={confirm} disabled={saving}>
              {saving ? "Saving…" : "Confirm & save"}
            </Button>
            <Button variant="outline" onClick={() => setProtocols(null)} disabled={saving}>
              Discard
            </Button>
          </div>
        </div>
      )}
    </main>
  );
}

function Field({
  label,
  children,
  className = "",
}: {
  label: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <label className={`flex flex-col gap-1 ${className}`}>
      <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      {children}
    </label>
  );
}

function Th({ children, right }: { children?: React.ReactNode; right?: boolean }) {
  return (
    <th
      className={`px-3 py-3 text-xs font-medium uppercase tracking-wide whitespace-nowrap ${
        right ? "text-right" : "text-left"
      }`}
    >
      {children}
    </th>
  );
}
