import type { Capture } from "@/lib/types";
import { fmtDt } from "@/lib/format";

const MODE_BADGE: Record<string, { cls: string; label: string }> = {
  mode2: {
    cls: "bg-accent-400/20 text-amber-700",
    label: "Engineering",
  },
  mode1: {
    cls: "bg-brand-50 text-brand-600",
    label: "Monitoring",
  },
};

function modeBadge(mode: string) {
  return MODE_BADGE[mode] ?? MODE_BADGE.mode1;
}

function getWire(c: Capture): string | null {
  const info = c.raw_lot_info;
  if (info && typeof info === "object" && !Array.isArray(info)) {
    const w = (info as Record<string, unknown>).wire;
    return typeof w === "string" ? w : null;
  }
  return null;
}

interface Props {
  c: Capture;
  variant?: "dashboard" | "bonding";
}

export default function CaptureCard({ c, variant = "dashboard" }: Props) {
  const wire = getWire(c);
  const badge = modeBadge(c.mode);

  return (
    <a
      href={`/lot/${encodeURIComponent(c.lot_id)}`}
      className="group block bg-ios-surface rounded-ios-lg shadow-ios hover:shadow-ios-md hover:-translate-y-0.5 transition-all duration-200 overflow-hidden"
    >
      {/* Top metadata strip */}
      <div className="px-4 pt-4 pb-3 flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="font-mono text-[15px] font-bold text-brand-600 tracking-tight truncate">
            {c.lot_id}
          </div>
          <div className="flex flex-wrap gap-x-2 gap-y-0.5 text-ios-caption mt-1 text-ios-label2">
            <span>
              <span className="text-ios-label3">MPC</span>{" "}
              <span className="font-medium text-ios-label">
                {c.mpc || "—"}
              </span>
            </span>
            <span className="text-ios-label4">·</span>
            <span>
              <span className="text-ios-label3">Wire</span>{" "}
              <span className="font-medium text-ios-label">
                {wire || "—"}
              </span>
            </span>
          </div>
        </div>
        <span
          className={`shrink-0 text-[10.5px] font-semibold px-2 py-0.5 rounded-full ${badge.cls}`}
        >
          {badge.label}
        </span>
      </div>

      {/* Time + machine row */}
      <div className="px-4 pb-3 flex items-center justify-between text-ios-caption">
        <span className="font-mono text-ios-label2">
          {fmtDt(c.confirmed_at)}
        </span>
        {variant === "dashboard" && c.lot_location && (
          <span className="px-2 py-0.5 rounded-md bg-ios-fill text-[10.5px] font-medium font-mono text-ios-label2">
            {c.lot_location}
          </span>
        )}
      </div>

      {/* Operator + bonding row */}
      <div className="px-4 pb-3 flex items-center justify-between gap-2 text-ios-caption">
        <span className="text-ios-label2 truncate">
          {variant === "dashboard"
            ? c.bonding_number || "—"
            : <span className="text-ios-label3">operator</span>}
        </span>
        <span
          title={`Operator ${c.operator_badge}`}
          className="shrink-0 px-2 py-0.5 rounded-full bg-ios-fill text-ios-label2 font-mono text-[10.5px] font-semibold"
        >
          {c.operator_badge || "—"}
        </span>
      </div>

      {/* Image strip — full bleed at bottom */}
      <div
        className="grid gap-1 px-4 pb-4"
        style={{
          gridTemplateColumns: `repeat(${c.files.length || 1}, minmax(0, 1fr))`,
        }}
      >
        {c.files.map((f, i) => (
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
        ))}
      </div>
    </a>
  );
}
