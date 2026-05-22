interface Props {
  page: number;
  totalPages: number;
  buildHref: (page: number) => string;
}

export default function Pagination({ page, totalPages, buildHref }: Props) {
  if (totalPages <= 1) return null;

  const prev = page > 1 ? buildHref(page - 1) : null;
  const next = page < totalPages ? buildHref(page + 1) : null;

  const pages: number[] = [];
  for (let i = 1; i <= totalPages; i++) pages.push(i);

  const pillBase =
    "h-9 min-w-9 px-3 inline-flex items-center justify-center text-[13px] font-medium rounded-full transition select-none";
  const idle = "bg-ios-fill text-ios-label hover:bg-ios-fill2 active:scale-[0.97]";
  const active = "bg-brand-600 text-white shadow-ios-sm";
  const disabled = "bg-ios-fill text-ios-label4 cursor-not-allowed";

  return (
    <nav className="mt-8 flex items-center justify-center gap-1.5 flex-wrap">
      {prev ? (
        <a href={prev} className={`${pillBase} ${idle}`}>
          <span aria-hidden className="mr-1">‹</span>
          Prev
        </a>
      ) : (
        <span className={`${pillBase} ${disabled}`}>
          <span aria-hidden className="mr-1">‹</span>
          Prev
        </span>
      )}

      {pages.map((p) =>
        p === page ? (
          <span key={p} className={`${pillBase} ${active} tabular-nums`}>
            {p}
          </span>
        ) : (
          <a
            key={p}
            href={buildHref(p)}
            className={`${pillBase} ${idle} tabular-nums`}
          >
            {p}
          </a>
        ),
      )}

      {next ? (
        <a href={next} className={`${pillBase} ${idle}`}>
          Next
          <span aria-hidden className="ml-1">›</span>
        </a>
      ) : (
        <span className={`${pillBase} ${disabled}`}>
          Next
          <span aria-hidden className="ml-1">›</span>
        </span>
      )}
    </nav>
  );
}
