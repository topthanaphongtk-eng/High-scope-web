import { redirect } from "next/navigation";
import { currentOperator } from "@/lib/qc-session";
import { dailyPackageSummary } from "@/lib/qc-db";
import QCSummaryChart from "@/components/QCSummaryChart";

export const dynamic = "force-dynamic";

const labelCls =
  "block text-ios-caption2 font-semibold uppercase tracking-wider text-ios-label3 mb-1.5";

function ymd(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

export default async function QCSummaryPage({
  searchParams,
}: {
  searchParams: Promise<{ date?: string }>;
}) {
  const op = await currentOperator();
  if (!op) redirect("/qc/login?next=/qc/summary");

  const sp = await searchParams;
  const now = new Date();
  const m = sp.date?.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  // Day bounds in Node-local (= plant) time, mirroring bucketCounts.
  const day = m
    ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
    : new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const nextDay = new Date(day.getFullYear(), day.getMonth(), day.getDate() + 1);

  const data = await dailyPackageSummary(day, nextDay);
  const tot = data.reduce(
    (a, d) => ({
      total: a.total + d.total_captures,
      reviewed: a.reviewed + d.reviewed,
      pass: a.pass + d.pass,
      reject: a.reject + d.reject,
    }),
    { total: 0, reviewed: 0, pass: 0, reject: 0 },
  );
  const passRate = tot.reviewed ? Math.round((tot.pass / tot.reviewed) * 100) : 0;

  return (
    <>
      <div className="mb-5 flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h2 className="font-display text-ios-title2 text-ios-label">
            Daily QC summary
          </h2>
          <p className="text-ios-footnote text-ios-label3 mt-0.5">
            Reviewed vs total captures bonded on {ymd(day)}, by package.
          </p>
        </div>
        <form method="get" className="flex items-end gap-2">
          <div>
            <label className={labelCls}>Day</label>
            <input
              type="date"
              name="date"
              defaultValue={ymd(day)}
              className="h-9 px-3 text-[14px] bg-ios-fill rounded-[10px] border-0 text-ios-label focus:outline-none focus:ring-2 focus:ring-brand-500/30 transition"
            />
          </div>
          <button
            type="submit"
            className="h-9 px-5 rounded-full text-[13px] font-semibold text-white bg-brand-600 hover:bg-brand-700 shadow-ios-sm transition"
          >
            View
          </button>
        </form>
      </div>

      {/* totals row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
        {[
          { k: "Total captures", v: tot.total, cls: "text-ios-label" },
          { k: "Reviewed", v: `${tot.reviewed}`, cls: "text-brand-600" },
          { k: "Pass", v: tot.pass, cls: "text-emerald-600" },
          { k: "Reject", v: tot.reject, cls: "text-red-600" },
        ].map((c) => (
          <div key={c.k} className="p-4 bg-ios-surface rounded-ios-lg shadow-ios">
            <div className={`font-display text-3xl font-bold tabular-nums leading-none ${c.cls}`}>
              {c.v}
            </div>
            <div className="text-ios-caption2 uppercase tracking-wider font-semibold text-ios-label3 mt-1.5">
              {c.k}
            </div>
          </div>
        ))}
      </div>

      <h3 className="text-ios-caption font-semibold uppercase tracking-wider text-ios-label3 mb-2.5 px-1">
        By package
      </h3>
      <div className="p-4 md:p-5 bg-ios-surface rounded-ios-lg shadow-ios mb-6">
        <QCSummaryChart data={data} />
      </div>

      {data.length > 0 && (
        <div className="overflow-hidden rounded-ios-lg bg-ios-surface shadow-ios">
          <table className="w-full text-ios-footnote">
            <thead>
              <tr className="text-ios-label3 text-left bg-ios-fill">
                <th className="px-4 py-2 font-semibold">Package</th>
                <th className="px-4 py-2 font-semibold text-right">Total</th>
                <th className="px-4 py-2 font-semibold text-right">Reviewed</th>
                <th className="px-4 py-2 font-semibold text-right">Pass</th>
                <th className="px-4 py-2 font-semibold text-right">Reject</th>
                <th className="px-4 py-2 font-semibold text-right">% Pass</th>
              </tr>
            </thead>
            <tbody className="tabular-nums text-ios-label2">
              {data.map((d) => (
                <tr key={d.package} className="border-t border-ios-separator">
                  <td className="px-4 py-2 font-mono text-ios-label">{d.package}</td>
                  <td className="px-4 py-2 text-right">{d.total_captures}</td>
                  <td className="px-4 py-2 text-right">{d.reviewed}</td>
                  <td className="px-4 py-2 text-right text-emerald-600 font-semibold">{d.pass}</td>
                  <td className="px-4 py-2 text-right text-red-600 font-semibold">{d.reject}</td>
                  <td className="px-4 py-2 text-right">
                    {d.reviewed ? `${Math.round((d.pass / d.reviewed) * 100)}%` : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t-2 border-ios-separator font-semibold text-ios-label">
                <td className="px-4 py-2">All packages</td>
                <td className="px-4 py-2 text-right">{tot.total}</td>
                <td className="px-4 py-2 text-right">{tot.reviewed}</td>
                <td className="px-4 py-2 text-right text-emerald-600">{tot.pass}</td>
                <td className="px-4 py-2 text-right text-red-600">{tot.reject}</td>
                <td className="px-4 py-2 text-right">{tot.reviewed ? `${passRate}%` : "—"}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}
    </>
  );
}
