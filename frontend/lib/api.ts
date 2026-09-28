const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type ItemStatus = "adequate" | "low" | "critical";
export type ItemType = "medication" | "supply" | "device";
export type POStatus =
  | "draft"
  | "pending_approval"
  | "sent"
  | "confirmed"
  | "received"
  | "cancelled";
export type POCreator = "ai" | "user";

export interface ItemListOut {
  id: number;
  name: string;
  type: ItemType;
  unit: string;
  total_stock: number;
  status: ItemStatus;
  days_until_stockout: number | null;
  default_supplier_name: string | null;
}

export interface BatchOut {
  id: number;
  lot_no: string;
  qty_on_hand: number;
  expiry_date: string;
  received_at: string;
}

export interface ItemDetailOut {
  id: number;
  name: string;
  type: ItemType;
  unit: string;
  unit_cost: number;
  total_stock: number;
  avg_daily_consumption: number;
  batches: BatchOut[];
}

export interface ExpiringBatchOut {
  id: number;
  item_id: number;
  item_name: string;
  lot_no: string;
  qty_on_hand: number;
  expiry_date: string;
  days_until_expiry: number;
}

export interface DemandBreakdown {
  A_scheduled: number;
  B_baseline: number;
  C_new_intake: number;
  total: number;
}

export interface ForecastItemOut {
  item_id: number;
  item_name: string;
  horizon_days: number;
  demand: DemandBreakdown;
  usable_stock: number;
  qty_on_order: number;
  ROP: number;
  order_qty: number;
  days_until_stockout: number | null;
  needs_order: boolean;
  rationale_data: Record<string, unknown>;
}

export interface SupplierBrief {
  id: number;
  name: string;
  email: string | null;
  phone: string | null;
  contact_person: string | null;
  lead_time_days: number;
  payment_terms: string | null;
}

export interface POLineOut {
  id: number;
  item_id: number;
  item_name: string;
  qty: number;
  unit_price: number;
  line_total: number;
  rationale: string | null;
}

export interface POOut {
  id: number;
  supplier: SupplierBrief;
  status: POStatus;
  created_by: POCreator;
  total: number;
  line_count: number;
  created_at: string;
  lines: POLineOut[];
  supplier_reply: string | null;
  reply_parsed: Record<string, unknown> | null;
  backup_of_po_id: number | null;
  backup_po_id: number | null;
}

export interface POListItem {
  id: number;
  supplier_id: number;
  supplier_name: string;
  status: POStatus;
  created_by: POCreator;
  total: number;
  line_count: number;
  created_at: string;
  backup_of_po_id: number | null;
}

export interface GenerateResult {
  created: number;
  po_ids: number[];
  skipped_items: string[];
  pos: POListItem[];
}

export interface ReceiveResult {
  po: POOut;
  units_received: number;
}

export interface DispenseSummaryLine {
  item_id: number;
  item_name: string;
  qty_dispensed: number;
  patient_id: number;
  patient_name: string;
}

export interface SimulateResult {
  date_processed: string;
  plans_processed: number;
  lines_dispensed: DispenseSummaryLine[];
  total_qty_dispensed: number;
}

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

export interface ChatResult {
  response: string;
  tools_used: string[];
}

export interface ExtractedProtocolItem {
  item_id: number | null;
  item_name: string;
  dosage: string;
  qty_per_cycle: number;
  dose_per_kg: number | null;
}

export interface ExtractedProtocol {
  name: string;
  icd_code: string;
  phase: string;
  cycle_length_days: number;
  total_cycles: number | null;
  items: ExtractedProtocolItem[];
}

export interface ProtocolPreview {
  filename: string;
  protocols: ExtractedProtocol[];
}

export interface SavedProtocol {
  id: number;
  name: string;
  phase: string;
  item_count: number;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init);
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

/** Pull the human-readable message out of a `request` error ("422: {"detail": "..."}"). */
export function errorMessage(e: unknown): string {
  const raw = e instanceof Error ? e.message : String(e);
  const m = raw.match(/^\d+: (\{[\s\S]*\})$/);
  if (m) {
    try {
      const detail = JSON.parse(m[1]).detail;
      if (typeof detail === "string") return detail;
      if (Array.isArray(detail)) return detail.map((d) => d.msg).join("; ");
    } catch {
      /* fall through to the raw message */
    }
  }
  return raw;
}

export const api = {
  items: () => request<ItemListOut[]>("/items"),
  item: (id: number) => request<ItemDetailOut>(`/items/${id}`),
  expiring: (days = 14) =>
    request<ExpiringBatchOut[]>(`/batches/expiring?days=${days}`),
  forecast: (horizonDays = 30) =>
    request<ForecastItemOut[]>(`/forecast?horizon_days=${horizonDays}`),
  orders: () => request<POListItem[]>("/purchase-orders"),
  order: (id: number) => request<POOut>(`/purchase-orders/${id}`),
  generateOrders: () =>
    request<GenerateResult>("/purchase-orders/generate", { method: "POST" }),
  approveOrder: (id: number) =>
    request<POOut>(`/purchase-orders/${id}/approve`, { method: "PATCH" }),
  receiveOrder: (id: number) =>
    request<ReceiveResult>(`/purchase-orders/${id}/receive`, { method: "POST" }),
  advanceDay: () =>
    request<SimulateResult>("/simulate/advance-day", { method: "POST" }),
  chat: (message: string, history: ChatTurn[]) =>
    request<ChatResult>("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, history }),
    }),
  uploadProtocol: (file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<ProtocolPreview>("/protocols/upload", { method: "POST", body });
  },
  confirmProtocols: (protocols: ExtractedProtocol[]) =>
    request<{ saved: SavedProtocol[] }>("/protocols/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        protocols: protocols.map((p) => ({
          name: p.name,
          icd_code: p.icd_code,
          phase: p.phase,
          cycle_length_days: p.cycle_length_days,
          total_cycles: p.total_cycles,
          items: p.items.map((i) => ({
            item_id: i.item_id,
            qty_per_cycle: i.qty_per_cycle,
            dose_per_kg: i.dose_per_kg,
          })),
        })),
      }),
    }),
};
