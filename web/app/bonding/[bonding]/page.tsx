import { recentCaptures } from "@/lib/capture-db";
import { decorate } from "@/lib/decorate";
import CaptureCard from "@/components/CaptureCard";

export const dynamic = "force-dynamic";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ bonding: string }>;
}) {
  const { bonding } = await params;
  return {
    title: `${decodeURIComponent(bonding)} · High Scope Monitor`,
  };
}

export default async function BondingView({
  params,
  searchParams,
}: {
  params: Promise<{ bonding: string }>;
  searchParams: Promise<{ machine?: string }>;
}) {
  const { bonding: rawBonding } = await params;
  const sp = await searchParams;
  const bonding = decodeURIComponent(rawBonding);
  const machine = sp.machine || null;

  const captures = recentCaptures({
    bonding_number: bonding,
    lot_location: machine,
    limit: 200,
  }).map(decorate);

  return (
    <>
      <a
        href="/"
        className="inline-flex items-center gap-1 text-[14px] font-medium text-brand-600 hover:text-brand-700 mb-3 -ml-1"
      >
        <span aria-hidden>‹</span> Dashboard
      </a>

      {/* iOS hero */}
      <header className="relative mb-8 rounded-ios-xl overflow-hidden shadow-ios-md">
        <div
          className="absolute inset-0"
          style={{
            background:
              "linear-gradient(135deg, #0E3689 0%, #1f4dab 50%, #0a2660 100%)",
          }}
        />
        <div
          className="absolute -top-16 -right-16 w-64 h-64 rounded-full opacity-40 blur-3xl"
          style={{ background: "#FFD53A" }}
        />
        <div className="relative p-6 md:p-8 text-white">
          <div className="text-ios-caption2 uppercase tracking-wider font-semibold opacity-70">
            Bonding × Machine
          </div>
          <div className="mt-1 flex items-baseline gap-3 flex-wrap">
            <span className="font-mono font-bold text-ios-largeTitle leading-tight">
              {bonding}
            </span>
            <span className="text-white/50 text-ios-title3">@</span>
            <span className="text-accent-400 font-display font-bold text-ios-title2">
              {machine || "—"}
            </span>
          </div>
          <div className="text-ios-subhead mt-4 text-white/85">
            <span className="text-white/55">Captures</span>{" "}
            <b className="tabular-nums">{captures.length}</b>
          </div>
        </div>
      </header>

      <h2 className="text-ios-caption font-semibold uppercase tracking-wider text-ios-label3 mb-2.5 px-1">
        Captures
      </h2>
      {captures.length === 0 ? (
        <div className="text-center py-16 rounded-ios-lg bg-ios-surface shadow-ios">
          <div className="text-5xl mb-3 opacity-30">📭</div>
          <div className="text-ios-callout font-medium text-ios-label">
            No captures found for this bonding
          </div>
        </div>
      ) : (
        <section className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {captures.map((c) => (
            <CaptureCard key={c.capture_id} c={c} variant="bonding" />
          ))}
        </section>
      )}
    </>
  );
}
