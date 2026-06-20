import { redirect } from "next/navigation";
import { currentOperator } from "@/lib/qc-session";
import { queueCounts, reviewQueue } from "@/lib/qc-db";
import { decorate } from "@/lib/decorate";
import { parseDate, parseUntil } from "@/lib/format";
import QCCaptureCard from "@/components/QCCaptureCard";

export const dynamic = "force-dynamic";

const QUEUE_LIMIT = 120;

const inputCls =
  "h-9 px-3 text-[14px] bg-ios-fill rounded-[10px] border-0 text-ios-label " +
  "placeholder:text-ios-label3 focus:outline-none focus:ring-2 focus:ring-brand-500/30 transition";
const labelCls =
  "block text-ios-caption2 font-semibold uppercase tracking-wider text-ios-label3 mb-1.5";

function ymd(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

interface SP {
  since?: string;
  until?: string;
  package?: string;
  status?: string;
}

export default async function QCQueue({
  searchParams,
}: {
  searchParams: Promise<SP>;
}) {
  const op = await currentOperator();
  if (!op) redirect("/qc/login?next=/qc");

  const sp = await searchParams;
  const now = new Date();
  // Default window: the last 7 days (today + 6 prior), so "pending" isn't the
  // entire historical backlog.
  const defaultSince = new Date(
    now.getFullYear(),
    now.getMonth(),
    now.getDate() - 6,
  );
  const since = parseDate(sp.since) ?? defaultSince;
  const until = parseUntil(sp.until);
  const pkg = sp.package?.trim() || null;
  const status: "pending" | "reviewed" | "all" =
    sp.status === "reviewed" || sp.status === "all" ? sp.status : "pending";

  const [rows, counts] = await Promise.all([
    reviewQueue({ since, until, package: pkg, status, limit: QUEUE_LIMIT }),
    queueCounts({ since, until, package: pkg }),
  ]);
  const items = rows.map(decorate);

  return (
    <>
      {/* coverage header for the window */}
      <div className="mb-4 flex flex-wrap items-center gap-2 text-ios-footnote">
        <span className="px-3 py-1 rounded-full bg-ios-fill text-ios-label2">
          <b className="tabular-nums text-ios-label">{counts.pending}</b> pending
        </span>
        <span className="px-3 py-1 rounded-full bg-emerald-500/12 text-emerald-700">
          <b className="tabular-nums">{counts.reviewed}</b> reviewed
        </span>
        <span className="px-3 py-1 rounded-full bg-ios-fill text-ios-label3">
          <b className="tabular-nums text-ios-label2">{counts.total}</b> total in window
        </span>
      </div>

      {/* filters (server GET form) */}
      <form
        method="get"
        className="mb-6 p-4 bg-ios-surface rounded-ios-lg shadow-ios flex flex-wrap gap-4 items-end"
      >
        <div>
          <label className={labelCls}>Since</label>
          <input type="date" name="since" defaultValue={sp.since ?? ymd(since)} className={inputCls} />
        </div>
        <div>
          <label className={labelCls}>Until</label>
          <input type="date" name="until" defaultValue={sp.until ?? ""} className={inputCls} />
        </div>
        <div>
          <label className={labelCls}>Package</label>
          <input type="text" name="package" defaultValue={pkg ?? ""} placeholder="8SOIC" className={`${inputCls} w-36`} />
        </div>
        <div>
          <label className={labelCls}>Status</label>
          <select name="status" defaultValue={status} className={`${inputCls} pr-8`}>
            <option value="pending">Pending</option>
            <option value="reviewed">Reviewed</option>
            <option value="all">All</option>
          </select>
        </div>
        <button
          type="submit"
          className="h-9 px-5 rounded-full text-[13px] font-semibold text-white bg-brand-600 hover:bg-brand-700 active:bg-brand-800 shadow-ios-sm transition"
        >
          Apply
        </button>
        <a
          href="/qc"
          className="h-9 inline-flex items-center px-3 text-[13px] font-medium text-brand-600 hover:bg-brand-50 rounded-full transition"
        >
          Reset
        </a>
      </form>

      {items.length === 0 ? (
        <div className="text-center py-16 rounded-ios-lg bg-ios-surface shadow-ios">
          <div className="text-5xl mb-3 opacity-30">✅</div>
          <div className="text-ios-callout font-medium text-ios-label">
            Nothing to review here
          </div>
          <div className="text-ios-footnote text-ios-label3 mt-1">
            Try a wider date range, another package, or the “Reviewed” / “All” status.
          </div>
        </div>
      ) : (
        <>
          <section className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {items.map((c) => (
              <QCCaptureCard key={c.capture_id} c={c} />
            ))}
          </section>
          {rows.length === QUEUE_LIMIT && (
            <p className="text-center text-ios-footnote text-ios-label3 mt-4">
              Showing the first {QUEUE_LIMIT}. Narrow the date range or package to see the rest.
            </p>
          )}
        </>
      )}
    </>
  );
}
