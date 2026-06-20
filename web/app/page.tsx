import type { Capture, Grade, Mode } from "@/lib/types";
import { bucketCounts, countCaptures, recentCaptures } from "@/lib/capture-db";
import { reviewStatusFor } from "@/lib/qc-db";
import { decorate } from "@/lib/decorate";
import { parseDate, parseUntil } from "@/lib/format";
import CaptureCard from "@/components/CaptureCard";
import FilterBar from "@/components/FilterBar";
import HeroCounts from "@/components/HeroCounts";
import Pagination from "@/components/Pagination";

export const dynamic = "force-dynamic";

const PER_PAGE = 60;

interface SearchParams {
  since?: string;
  until?: string;
  bonding?: string;
  machine?: string;
  mode?: string;
  page?: string;
}

export const metadata = {
  title: "Dashboard · High Scope Monitor",
};

function buildHref(sp: SearchParams, page: number): string {
  const qs = new URLSearchParams();
  if (sp.since) qs.set("since", sp.since);
  if (sp.until) qs.set("until", sp.until);
  if (sp.bonding) qs.set("bonding", sp.bonding);
  if (sp.machine) qs.set("machine", sp.machine);
  if (sp.mode) qs.set("mode", sp.mode);
  if (page > 1) qs.set("page", String(page));
  const q = qs.toString();
  return q ? `/?${q}` : "/";
}

export default async function Dashboard({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const sp = await searchParams;
  const since = parseDate(sp.since);
  const until = parseUntil(sp.until);
  const bonding = sp.bonding || null;
  const machine = sp.machine || null;
  const mode: Mode | null =
    sp.mode === "mode1" || sp.mode === "mode2" ? sp.mode : null;

  const filter = {
    since,
    until,
    bonding_number: bonding,
    lot_location: machine,
    mode,
  };

  const totalMatch = await countCaptures(filter);
  const totalPages = Math.max(1, Math.ceil(totalMatch / PER_PAGE));
  const rawPage = Number(sp.page || 1);
  const page = Number.isFinite(rawPage)
    ? Math.min(Math.max(1, Math.trunc(rawPage)), totalPages)
    : 1;
  const offset = (page - 1) * PER_PAGE;

  const [rawCaptures, counts] = await Promise.all([
    recentCaptures({ ...filter, limit: PER_PAGE, offset }),
    bucketCounts(),
  ]);
  const captures = rawCaptures.map(decorate);
  const qcVerdicts = await reviewStatusFor(captures.map((c) => c.capture_id));
  const awaiting = captures.filter((c) => !qcVerdicts[c.capture_id]);
  const done = captures.filter((c) => qcVerdicts[c.capture_id]);
  const active = !!(since || until || bonding || machine || mode);

  const firstShown = totalMatch === 0 ? 0 : offset + 1;
  const lastShown = Math.min(offset + captures.length, totalMatch);

  return (
    <>
      {/* iOS Large Title */}
      <div className="mb-6 flex items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-ios-largeTitle text-ios-label">
            Online 200X Monitoring
          </h1>
          <p className="text-ios-subhead text-ios-label2 mt-1">
            Visual inspection after setup and convert machine.
          </p>
        </div>
        <div className="flex items-end gap-4">
          <a
            href="/qc"
            className="h-9 px-4 inline-flex items-center gap-1.5 rounded-full text-[13px] font-semibold text-white bg-brand-600 hover:bg-brand-700 active:bg-brand-800 shadow-ios-sm transition"
          >
            🔬 QC Mode
          </a>
          <div className="text-right hidden sm:block">
            <div className="text-ios-caption2 uppercase tracking-wider font-semibold text-ios-label3">
              Showing
            </div>
            <div className="font-display text-3xl font-bold tabular-nums text-brand-600 leading-none mt-1">
              {captures.length}
            </div>
          </div>
        </div>
      </div>

      <SectionHeader>Overview</SectionHeader>
      <HeroCounts
        today={counts.today}
        week={counts.week}
        month={counts.month}
        total={counts.total}
      />

      <SectionHeader>Filters</SectionHeader>
      <FilterBar
        since={sp.since || ""}
        until={sp.until || ""}
        bonding={bonding || ""}
        machine={machine || ""}
        mode={mode || ""}
        active={active}
        matchCount={totalMatch}
      />

      <div className="flex items-baseline justify-between mb-2.5 px-1">
        <h2 className="text-ios-caption font-semibold uppercase tracking-wider text-ios-label3">
          Recent captures
        </h2>
        {totalMatch > 0 && (
          <span className="text-ios-caption2 text-ios-label3 tabular-nums">
            {firstShown}–{lastShown} of {totalMatch}
          </span>
        )}
      </div>

      {captures.length === 0 ? (
        <div className="text-center py-16 rounded-ios-lg glass shadow-ios">
          <div className="text-5xl mb-3 opacity-30">📭</div>
          <div className="text-ios-callout font-medium text-ios-label">
            No captures match this filter
          </div>
          <div className="text-ios-footnote text-ios-label3 mt-1">
            Try widening the date range or clearing filters.
          </div>
        </div>
      ) : (
        <>
          <QCZone
            title="Awaiting QC"
            dotCls="bg-amber-400"
            items={awaiting}
            qc={qcVerdicts}
            emptyMsg="All caught up — nothing waiting for QC in this view."
          />
          <QCZone
            title="QC done"
            dotCls="bg-emerald-500"
            items={done}
            qc={qcVerdicts}
            emptyMsg="No reviewed captures in this view yet."
          />
          <Pagination
            page={page}
            totalPages={totalPages}
            buildHref={(p) => buildHref(sp, p)}
          />
        </>
      )}
    </>
  );
}

function SectionHeader({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-ios-caption font-semibold uppercase tracking-wider text-ios-label3 mb-2.5 px-1">
      {children}
    </h2>
  );
}

function QCZone({
  title,
  dotCls,
  items,
  qc,
  emptyMsg,
}: {
  title: string;
  dotCls: string;
  items: Capture[];
  qc: Record<string, { verdict: Grade; badge: string }>;
  emptyMsg: string;
}) {
  return (
    <section className="mb-7">
      <div className="flex items-center gap-2 mb-2.5 px-1">
        <span className={`w-2 h-2 rounded-full ${dotCls}`} />
        <h2 className="text-ios-caption font-semibold uppercase tracking-wider text-ios-label3">
          {title}
        </h2>
        <span className="text-ios-caption2 font-semibold text-ios-label3 tabular-nums">
          {items.length}
        </span>
      </div>
      {items.length === 0 ? (
        <p className="text-ios-footnote text-ios-label3 px-1 pb-1">{emptyMsg}</p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {items.map((c) => {
            const v = qc[c.capture_id];
            return (
              <CaptureCard
                key={c.capture_id}
                c={c}
                variant="dashboard"
                qcStatus={v?.verdict ?? "AWAITING"}
                qcBadge={v?.badge ?? null}
              />
            );
          })}
        </div>
      )}
    </section>
  );
}
