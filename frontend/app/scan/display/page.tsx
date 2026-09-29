"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { QRCodeSVG } from "qrcode.react";
import { api, type ItemDetailOut } from "@/lib/api";

export default function ScanDisplayPage() {
  const params = useSearchParams();
  const itemId = Number(params.get("item_id"));
  const [item, setItem] = useState<ItemDetailOut | null>(null);
  const [origin, setOrigin] = useState("");

  useEffect(() => {
    setOrigin(window.location.origin);
    if (itemId) {
      api.item(itemId).then(setItem).catch(() => {});
    }
  }, [itemId]);

  const scanUrl = origin && itemId ? `${origin}/scan?item_id=${itemId}` : null;

  if (!itemId) {
    return (
      <main className="min-h-screen flex items-center justify-center text-gray-500">
        Missing item_id parameter.
      </main>
    );
  }

  return (
    <main className="min-h-screen flex flex-col items-center justify-center gap-6 bg-white p-8 print:p-4">
      {scanUrl ? (
        <QRCodeSVG value={scanUrl} size={300} level="H" />
      ) : (
        <div className="size-[300px] bg-gray-100 animate-pulse rounded" />
      )}
      <p className="text-2xl font-semibold tracking-tight text-gray-900">
        {item ? item.name : `Item #${itemId}`}
      </p>
      {scanUrl && (
        <p className="text-xs text-gray-400 font-mono break-all text-center max-w-sm">
          {scanUrl}
        </p>
      )}
    </main>
  );
}
