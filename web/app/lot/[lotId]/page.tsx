import { notFound } from "next/navigation";
import { lotCaptures } from "@/lib/capture-db";
import { decorate } from "@/lib/decorate";
import { fmtDt } from "@/lib/format";
import type { Capture } from "@/lib/types";

export const dynamic = "force-dynamic";

function getWire(c: Capture): string | null {
  const info = c.raw_lot_info;
  if (info && typeof info === "object" && !Array.isArray(info)) {
    const w = (info as Record<string, unknown>).wire;
    return typeof w === "string" ? w : null;
  }
  return null;
}

function modeBadge(mode: string) {
  return mode === "mode2"
    ? { cls: "bg-accent-400/20 text-amber-700", label: "Engineering" }
    : { cls: "bg-brand-50 text-brand-600", label: "Monitoring" };
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ lotId: string }>;
}) {
  const { lotId } = await params;
  return { title: `LOT ${decodeURIComponent(lotId)} · High Scope Monitor` };
}

export default async function LotDetail({
  params,
}: {
  params: Promise<{ lotId: string }>;
}) {
  const { lotId: rawId } = await params;
  const lotId = decodeURIComponent(rawId);
  const captures = lotCaptures(lotId).map(decorate);
  if (captures.length === 0) notFound();

  const first = captures[0];
  const wire = first ? getWire(first) : null;

  return (
    <>
      <a
        href="/"
        className="inline-flex items-center gap-1 text-[14px] font-medium text-brand-600 hover:text-brand-700 mb-3 -ml-1"
      >
        <span aria-hidden>‹</span> Dashboard
      </a>

      {/* iOS hero card with subtle gradient + glass */}
      <header className="relative mb-8 rounded-ios-xl overflow-hidden shadow-ios-md">
        <div
          className="absolute inset-0"
          style={{
            background:
              "linear-gradient(135deg, #0E3689 0%, #1f4dab 50%, #0a2660 100%)",
          }}
        />
        {/* yellow accent bloom */}
        <div
          className="absolute -top-16 -right-16 w-64 h-64 rounded-full opacity-40 blur-3xl"
          style={{ background: "#FFD53A" }}
        />
        <div className="relative p-6 md:p-8 text-white">
          <div className="text-ios-caption2 uppercase tracking-wider font-semibold opacity-70">
            LOT detail
          </div>
          <div className="mt-1 font-mono font-bold text-ios-largeTitle leading-tight">
            {lotId}
          </div>
          <div className="flex flex-wrap gap-x-5 gap-y-1 text-ios-subhead mt-4 text-white/90">
            <span>
              <span className="text-white/55">MPC</span>{" "}
              <b>{first?.mpc || "—"}</b>
            </span>
            <span className="text-white/30">·</span>
            <span>
              <span className="text-white/55">Wire</span>{" "}
              <b>{wire || "—"}</b>
            </span>
            <span className="text-white/30">·</span>
            <span>
              <span className="text-white/55">Captures</span>{" "}
              <b className="tabular-nums">{captures.length}</b>
            </span>
          </div>
        </div>
      </header>

      {/* Captures list — iOS inset grouped style */}
      <h2 className="text-ios-caption font-semibold uppercase tracking-wider text-ios-label3 mb-2.5 px-1">
        Captures
      </h2>
      <div className="space-y-4">
        {captures.map((c) => {
          const cWire = getWire(c);
          const badge = modeBadge(c.mode);
          return (
            <section
              key={c.capture_id}
              className="bg-ios-surface rounded-ios-lg shadow-ios overflow-hidden"
            >
              <div className="px-5 py-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 ios-hairline text-ios-caption">
                <span className="font-semibold font-mono text-ios-label">
                  {fmtDt(c.confirmed_at)}
                </span>
                <span className="text-ios-label4">·</span>
                <a
                  href={`/bonding/${encodeURIComponent(c.bonding_number || "")}?machine=${encodeURIComponent(c.lot_location || "")}`}
                  className="font-semibold text-ios-label hover:text-brand-600 hover:underline"
                >
                  {c.bonding_number || "—"}
                </a>
                {c.lot_location && (
                  <span className="px-2 py-0.5 rounded-md bg-ios-fill font-mono text-ios-label2">
                    {c.lot_location}
                  </span>
                )}
                <span className="text-ios-label3">op {c.operator_badge}</span>
                {c.mpc && <span className="text-ios-label3">MPC {c.mpc}</span>}
                {cWire && <span className="text-ios-label3">Wire {cWire}</span>}
                {c.package && (
                  <span className="text-ios-label3">Pkg {c.package}</span>
                )}
                <span
                  className={`text-[10.5px] font-semibold px-2 py-0.5 rounded-full ${badge.cls}`}
                >
                  {badge.label}
                </span>
                <span className="ml-auto text-ios-caption2 font-mono text-ios-label4 truncate max-w-[200px]">
                  {c.capture_id}
                </span>
              </div>

              <div className="p-5">
                <div
                  className="grid gap-3"
                  style={{
                    gridTemplateColumns: `repeat(${c.files.length || 1}, minmax(0, 1fr))`,
                  }}
                >
                  {c.files.map((f, i) => (
                    <div key={i} className="space-y-2">
                      {f.image_rel ? (
                        <a
                          target="_blank"
                          rel="noopener"
                          href={`/image?path=${encodeURIComponent(f.image_rel)}`}
                          className="block group"
                        >
                          <div className="aspect-[4/3] bg-slate-900 rounded-[12px] overflow-hidden ring-1 ring-black/5">
                            <img
                              src={`/image?path=${encodeURIComponent(f.image_rel)}`}
                              alt={f.slot}
                              loading="lazy"
                              className="w-full h-full object-cover group-hover:scale-[1.03] transition-transform duration-300"
                            />
                          </div>
                        </a>
                      ) : (
                        <div className="aspect-[4/3] bg-ios-fill rounded-[12px] grid place-items-center text-ios-caption text-ios-label3">
                          file outside share
                        </div>
                      )}
                      <div className="flex items-center justify-between text-ios-caption">
                        <span className="font-semibold text-emerald-600">
                          {f.slot}
                        </span>
                        <span
                          className="font-mono truncate ml-2 text-ios-label3"
                          title={f.fused_name}
                        >
                          {f.fused_name}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </section>
          );
        })}
      </div>
    </>
  );
}
