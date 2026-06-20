"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import QCStandards from "./QCStandards";

export default function QCStandardsModal({
  acknowledged,
  operatorName,
}: {
  acknowledged: boolean;
  operatorName: string;
}) {
  const router = useRouter();
  const gate = !acknowledged; // must accept before using QC
  const [open, setOpen] = useState(gate);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function accept() {
    setBusy(true);
    setErr("");
    try {
      const res = await fetch("/api/qc/accept-standards", { method: "POST" });
      if (res.ok) {
        setOpen(false);
        router.refresh();
        return;
      }
      setErr("บันทึกไม่สำเร็จ — ลองอีกครั้ง");
    } catch {
      setErr("เชื่อมต่อเซิร์ฟเวอร์ไม่ได้");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="px-3 py-1 text-[13px] font-medium text-brand-600 rounded-full hover:bg-brand-50 transition"
      >
        📋 Visual Aid
      </button>

      {open && (
        <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-3 sm:p-6">
          {/* frosted glass scrim over the main page */}
          <div
            className="qc-fade absolute inset-0 bg-slate-900/30 backdrop-blur-xl backdrop-saturate-150"
            onClick={() => {
              if (!gate) setOpen(false);
            }}
          />

          {/* floating glass card */}
          <div className="qc-rise relative w-full max-w-2xl max-h-[90vh] flex flex-col rounded-[28px] bg-white/70 backdrop-blur-2xl backdrop-saturate-150 ring-1 ring-white/60 border border-white/40 shadow-[0_40px_100px_-20px_rgba(14,54,137,0.55)] overflow-hidden">
            {/* top light sheen */}
            <div className="pointer-events-none absolute inset-x-0 top-0 h-24 bg-gradient-to-b from-white/55 to-transparent" />

            {/* header */}
            <div className="relative flex items-center justify-between gap-3 px-5 pt-5 pb-3">
              <div className="flex items-center gap-2.5">
                <span
                  className="grid place-items-center w-9 h-9 rounded-[11px] text-white text-[16px] shadow-ios-sm"
                  style={{ background: "linear-gradient(135deg,#0E3689 0%,#0A2660 100%)" }}
                >
                  📋
                </span>
                <div>
                  <h2 className="font-display text-ios-title3 text-ios-label leading-tight">
                    Visual Aid QC
                  </h2>
                  <p className="text-ios-caption2 text-ios-label3">
                    เกณฑ์การตรวจสอบคุณภาพ · Criteria
                  </p>
                </div>
              </div>
              {!gate && (
                <button
                  onClick={() => setOpen(false)}
                  aria-label="Close"
                  className="w-8 h-8 grid place-items-center rounded-full bg-ios-fill text-ios-label2 hover:bg-ios-fill2 transition"
                >
                  ✕
                </button>
              )}
            </div>

            {/* scrollable body */}
            <div className="relative overflow-y-auto px-5 pb-4">
              <QCStandards operatorName={operatorName} />
            </div>

            {/* footer */}
            <div className="relative px-5 py-4 border-t border-white/40 bg-white/40">
              {gate ? (
                <>
                  <button
                    onClick={accept}
                    disabled={busy}
                    className="h-12 w-full rounded-full text-[15px] font-semibold text-white bg-brand-600 hover:bg-brand-700 active:bg-brand-800 shadow-ios-md transition disabled:opacity-40"
                  >
                    {busy
                      ? "กำลังบันทึก…"
                      : "✓  ยอมรับ — เข้าใจและจะปฏิบัติตามเกณฑ์นี้"}
                  </button>
                  {err && (
                    <p className="text-ios-footnote text-red-600 mt-2 text-center">{err}</p>
                  )}
                </>
              ) : (
                <button
                  onClick={() => setOpen(false)}
                  className="h-11 w-full rounded-full text-[14px] font-semibold text-brand-600 bg-brand-50 hover:bg-brand-100 transition"
                >
                  ปิด
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
