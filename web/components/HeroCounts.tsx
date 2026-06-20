interface Props {
  today: number;
  week: number;
  month: number;
  total: number;
}

interface Stat {
  label: string;
  value: number;
  hint: string;
  live?: boolean;
  accent?: boolean;
}

export default function HeroCounts({ today, week, month, total }: Props) {
  const stats: Stat[] = [
    { label: "Today", value: today, hint: "captures today", live: true },
    { label: "This week", value: week, hint: "Mon — now" },
    { label: "This month", value: month, hint: "month-to-date" },
    { label: "All time", value: total, hint: "in database", accent: true },
  ];

  return (
    <section className="mb-8 glass rounded-ios-lg shadow-ios">
      <div className="flex flex-col sm:flex-row divide-y sm:divide-y-0 sm:divide-x divide-white/40">
        {stats.map((s) => (
          <div key={s.label} className="flex-1 px-5 py-4">
            <div className="flex items-center gap-1.5">
              {s.live && (
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
              )}
              <span className="text-ios-caption2 uppercase tracking-[0.14em] font-semibold text-ios-label3">
                {s.label}
              </span>
            </div>
            <div
              className={
                "mt-2.5 font-mono text-[30px] leading-none font-semibold tabular-nums " +
                (s.accent ? "text-brand-600" : "text-ios-label")
              }
            >
              {s.value.toLocaleString()}
            </div>
            <div className="mt-2 text-ios-caption2 text-ios-label3">{s.hint}</div>
          </div>
        ))}
      </div>
    </section>
  );
}
