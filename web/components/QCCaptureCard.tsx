import Link from "next/link";
import type { CaptureWithReview } from "@/lib/types";
import { fmtDt } from "@/lib/format";

function chip(c: CaptureWithReview): { cls: string; label: string } {
  if (!c.review) return { cls: "bg-ios-fill text-ios-label2", label: "Needs review" };
  return c.review.overall_verdict === "PASS"
    ? { cls: "bg-emerald-500/15 text-emerald-700", label: "PASS" }
    : { cls: "bg-red-500/15 text-red-700", label: "REJECT" };
}

export default function QCCaptureCard({ c }: { c: CaptureWithReview }) {
  const v = chip(c);
  return (
    <Link
      href={`/qc/review/${encodeURIComponent(c.capture_id)}`}
      className="group block glass-card rounded-ios-lg shadow-ios hover:shadow-ios-md hover:-translate-y-0.5 transition-all duration-200 overflow-hidden"
    >
      <div className="px-4 pt-4 pb-3 flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="font-mono text-[15px] font-bold text-brand-600 tracking-tight truncate">
            {c.lot_id}
          </div>
          <div className="flex flex-wrap gap-x-2 gap-y-0.5 text-ios-caption mt-1 text-ios-label2">
            <span>
              <span className="text-ios-label3">Pkg</span>{" "}
              <span className="font-medium text-ios-label">{c.package || "—"}</span>
            </span>
            <span className="text-ios-label4">·</span>
            <span>
              <span className="text-ios-label3">M/C</span>{" "}
              <span className="font-medium text-ios-label">{c.lot_location || "—"}</span>
            </span>
          </div>
        </div>
        <span className={`shrink-0 text-[10.5px] font-bold px-2 py-0.5 rounded-full ${v.cls}`}>
          {v.label}
        </span>
      </div>

      <div className="px-4 pb-3 flex items-center justify-between text-ios-caption">
        <span className="font-mono text-ios-label2">{fmtDt(c.confirmed_at)}</span>
        <span className="text-ios-label2 truncate">{c.bonding_number || "—"}</span>
      </div>

      <div
        className="grid gap-1 px-4 pb-4"
        style={{ gridTemplateColumns: `repeat(${c.files.length || 1}, minmax(0, 1fr))` }}
      >
        {c.files.length === 0 ? (
          <div className="aspect-[4/3] grid place-items-center bg-ios-fill rounded-[10px] text-ios-caption2 text-ios-label3">
            no images
          </div>
        ) : (
          c.files.map((f, i) => (
            <div key={i} className="space-y-1.5">
              <div className="aspect-[4/3] bg-slate-900 rounded-[10px] overflow-hidden ring-1 ring-black/5">
                {f.image_rel && (
                  <img
                    src={`/image?path=${encodeURIComponent(f.image_rel)}`}
                    alt={f.slot}
                    loading="lazy"
                    className="w-full h-full object-cover group-hover:scale-[1.03] transition-transform duration-300"
                  />
                )}
              </div>
              <div className="text-center text-ios-caption2 text-ios-label3 font-medium">
                {f.slot}
              </div>
            </div>
          ))
        )}
      </div>
    </Link>
  );
}
