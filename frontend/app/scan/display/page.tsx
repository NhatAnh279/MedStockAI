"use client";

import { QRCodeSVG } from "qrcode.react";

const SCAN_URL = "http://172.20.10.3:3000/scan?item_id=26";

export default function ScanDisplayPage() {
  return (
    <main className="min-h-screen flex flex-col items-center justify-center gap-6 bg-white p-8 print:p-4">
      <QRCodeSVG value={SCAN_URL} size={400} level="H" />
      <p className="text-2xl font-semibold tracking-tight text-gray-900">
        Paracetamol 500mg
      </p>
      <p className="text-sm text-gray-400 font-mono break-all text-center max-w-sm">
        {SCAN_URL}
      </p>
    </main>
  );
}
