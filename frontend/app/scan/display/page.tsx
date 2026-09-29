"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api, type ItemDetailOut } from "@/lib/api";

export default function ScanDisplayPage() {
  const params = useSearchParams();
  const itemId = Number(params.get("item_id"));
  const [item, setItem] = useState<ItemDetailOut | null>(null);
  const [scanUrl, setScanUrl] = useState("");

  useEffect(() => {
    setScanUrl(`${window.location.origin}/scan?item_id=${itemId}`);
    if (itemId) {
      api.item(itemId).then(setItem).catch(() => {});
    }
  }, [itemId]);

  if (!itemId) {
    return (
      <main className="flex items-center justify-center min-h-screen text-gray-500">
        Missing item_id parameter.
      </main>
    );
  }

  const qrImageUrl = scanUrl
    ? `https://api.qrserver.com/v1/create-qr-code/?size=400x400&data=${encodeURIComponent(scanUrl)}`
    : null;

  return (
    <div className="flex flex-col items-center justify-center min-h-screen gap-4 bg-white p-8">
      {qrImageUrl ? (
        <img src={qrImageUrl} width={400} height={400} alt="QR Code" />
      ) : (
        <div className="size-[400px] bg-gray-100 animate-pulse rounded" />
      )}
      <p className="mt-4 text-xl font-bold">{item ? item.name : `Item #${itemId}`}</p>
      <p className="text-gray-500">Scan to log a transaction</p>
      {scanUrl && (
        <p className="text-xs text-gray-400 font-mono break-all text-center max-w-sm">{scanUrl}</p>
      )}
    </div>
  );
}
