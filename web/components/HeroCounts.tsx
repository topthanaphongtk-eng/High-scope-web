interface Stat {
  label: string;
  value: number;
  hint: string;
  icon: string;
  tint: string; // tailwind classes for the colored fill behind the icon
}

interface Props {
  today: number;
  week: number;
  month: number;
  total: number;
}

export default function HeroCounts({ today, week, month, total }: Props) {
  const stats: Stat[] = [
    {
      label: "Today",
      value: today,
      hint: "captures today",
      icon: "📅",
      tint: "bg-brand-50 text-brand-600",
    },
    {
      label: "This week",
      value: week,
      hint: "Mon → now",
      icon: "📊",
      tint: "bg-sky-50 text-sky-600",
    },
    {
      label: "This month",
      value: month,
      hint: "month-to-date",
      icon: "🗓️",
      tint: "bg-emerald-50 text-emerald-600",
    },
    {
      label: "All time",
      value: total,
      hint: "in the database",
      icon: "💾",
      tint: "bg-accent-400/20 text-amber-700",
    },
  ];

  return (
    <section className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-8">
      {stats.map((s) => (
        <div
          key={s.label}
          className="relative bg-ios-surface rounded-ios-lg shadow-ios p-4 md:p-5 overflow-hidden"
        >
          <div className="flex items-start justify-between gap-2 mb-3">
            <div
              className={`grid place-items-center w-9 h-9 rounded-[10px] text-base ${s.tint}`}
            >
              {s.icon}
            </div>
          </div>
          <div className="text-[28px] md:text-[34px] font-display font-bold tabular-nums leading-none text-ios-label tracking-tight">
            {s.value.toLocaleString()}
          </div>
          <div className="mt-1.5 text-ios-footnote font-medium text-ios-label">
            {s.label}
          </div>
          <div className="text-ios-caption2 text-ios-label3 mt-0.5">
            {s.hint}
          </div>
        </div>
      ))}
    </section>
  );
}
