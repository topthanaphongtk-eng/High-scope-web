import type { PackageDaySummary } from "@/lib/types";

// Hand-rolled flexbox bar chart — one stacked bar per package, scaled to the
// busiest package's total. Segments: Pass (green) + Reject (red) = reviewed;
// the grey tail is still-pending (total − reviewed). No charting library.
export default function QCSummaryChart({ data }: { data: PackageDaySummary[] }) {
  if (data.length === 0) {
    return (
      <div className="text-center py-10 text-ios-footnote text-ios-label3">
        No captures bonded on this day.
      </div>
    );
  }
  const maxTotal = Math.max(...data.map((d) => d.total_captures), 1);
  const pct = (n: number) => `${(n / maxTotal) * 100}%`;

  return (
    <div className="space-y-3.5">
      {data.map((d) => {
        const pending = Math.max(0, d.total_captures - d.reviewed);
        return (
          <div key={d.package}>
            <div className="flex items-baseline justify-between text-ios-caption mb-1 gap-2">
              <span className="font-medium text-ios-label font-mono truncate">
                {d.package}
              </span>
              <span className="text-ios-label3 tabular-nums shrink-0">
                <b className="text-emerald-600">{d.pass}</b> pass ·{" "}
                <b className="text-red-600">{d.reject}</b> reject ·{" "}
                <span className="text-ios-label2">
                  {d.reviewed}/{d.total_captures} reviewed
                </span>
              </span>
            </div>
            <div className="h-5 flex rounded-[6px] overflow-hidden bg-ios-fill ring-1 ring-black/5">
              <div style={{ width: pct(d.pass) }} className="bg-emerald-500" title={`${d.pass} pass`} />
              <div style={{ width: pct(d.reject) }} className="bg-red-500" title={`${d.reject} reject`} />
              <div style={{ width: pct(pending) }} className="bg-ios-label4" title={`${pending} pending`} />
            </div>
          </div>
        );
      })}

      <div className="flex flex-wrap gap-4 text-ios-caption2 text-ios-label3 pt-1">
        <span className="inline-flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-sm bg-emerald-500" /> Pass
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-sm bg-red-500" /> Reject
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-sm bg-ios-label4" /> Pending (not yet reviewed)
        </span>
      </div>
    </div>
  );
}
