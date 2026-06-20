"use client";

import type { Grade } from "@/lib/types";

interface Props {
  label: string;
  value: Grade | null;
  note: string;
  onValue: (g: Grade) => void;
  onNote: (s: string) => void;
}

export default function QCItemControl({
  label,
  value,
  note,
  onValue,
  onNote,
}: Props) {
  function seg(g: Grade, activeCls: string): string {
    const base = "px-5 py-1.5 text-[13px] font-semibold rounded-[8px] transition";
    return value === g
      ? `${base} ${activeCls} shadow-ios-sm`
      : `${base} text-ios-label2 hover:text-ios-label`;
  }

  return (
    <div className="p-4 bg-ios-surface rounded-ios-lg shadow-ios">
      <div className="flex items-center justify-between gap-3 mb-3">
        <span className="text-ios-headline text-ios-label">{label}</span>
        <div className="inline-flex p-1 bg-ios-fill rounded-[10px]">
          <button
            type="button"
            onClick={() => onValue("PASS")}
            className={seg("PASS", "bg-emerald-500 text-white")}
          >
            Pass
          </button>
          <button
            type="button"
            onClick={() => onValue("REJECT")}
            className={seg("REJECT", "bg-red-500 text-white")}
          >
            Reject
          </button>
        </div>
      </div>
      <input
        value={note}
        onChange={(e) => onNote(e.target.value)}
        maxLength={512}
        placeholder="Note (optional)"
        className="h-9 px-3 w-full text-[13px] bg-ios-fill rounded-[10px] border-0 text-ios-label placeholder:text-ios-label3 focus:outline-none focus:ring-2 focus:ring-brand-500/30 transition"
      />
    </div>
  );
}
