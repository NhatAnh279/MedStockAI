"use client";

import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const MODULES = [
  { title: "Inventory", description: "Batches, stock levels, near-expiry alerts" },
  { title: "Demand forecast", description: "Protocol-driven demand from active treatment plans" },
  { title: "Purchase orders", description: "AI-drafted POs awaiting approval" },
  { title: "Audit log", description: "Every AI and user action, before and after" },
];

export default function Home() {
  const [backend, setBackend] = useState<"checking" | "ok" | "down">("checking");

  useEffect(() => {
    fetch(`${API_URL}/health`)
      .then((r) => setBackend(r.ok ? "ok" : "down"))
      .catch(() => setBackend("down"));
  }, []);

  return (
    <main className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-8 px-6 py-16">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">MedStock AI</h1>
          <p className="text-muted-foreground">Hospital inventory and demand forecasting</p>
        </div>
        <Badge variant={backend === "down" ? "destructive" : "secondary"}>
          API: {backend === "checking" ? "checking…" : backend}
        </Badge>
      </header>

      <section className="grid gap-4 sm:grid-cols-2">
        {MODULES.map((m) => (
          <Card key={m.title}>
            <CardHeader>
              <CardTitle>{m.title}</CardTitle>
              <CardDescription>{m.description}</CardDescription>
            </CardHeader>
          </Card>
        ))}
      </section>
    </main>
  );
}
