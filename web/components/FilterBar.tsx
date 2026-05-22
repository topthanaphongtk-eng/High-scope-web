"use client";

import { useRef } from "react";

interface Props {
  since: string;
  until: string;
  bonding: string;
  machine: string;
  mode: string;
  active: boolean;
  matchCount: number;
}

export default function FilterBar({
  since,
  until,
  bonding,
  machine,
  mode,
  active,
  matchCount,
}: Props) {
  const formRef = useRef<HTMLFormElement>(null);
  const modeRef = useRef<HTMLInputElement>(null);

  function pickMode(m: string) {
    if (modeRef.current) modeRef.current.value = m;
    formRef.current?.submit();
  }

  const inputCls =
    "h-9 px-3 text-[14px] bg-ios-fill rounded-[10px] border-0 " +
    "text-ios-label placeholder:text-ios-label3 " +
    "focus:outline-none focus:ring-2 focus:ring-brand-500/30 transition";
  const labelCls =
    "block text-ios-caption2 font-semibold uppercase tracking-wider text-ios-label3 mb-1.5";

  function segCls(m: string) {
    const isActive = mode === m || (m === "" && !mode);
    if (isActive) {
      return "px-3.5 py-1 text-[12px] font-semibold rounded-[8px] bg-white text-ios-label shadow-ios-sm transition";
    }
    return "px-3.5 py-1 text-[12px] font-medium rounded-[8px] text-ios-label2 hover:text-ios-label transition";
  }

  return (
    <form
      ref={formRef}
      method="get"
      className="mb-6 p-4 md:p-5 bg-ios-surface rounded-ios-lg shadow-ios flex flex-wrap gap-4 items-end"
    >
      <div>
        <label className={labelCls}>Since</label>
        <input type="date" name="since" defaultValue={since} className={inputCls} />
      </div>
      <div>
        <label className={labelCls}>Until</label>
        <input type="date" name="until" defaultValue={until} className={inputCls} />
      </div>
      <div>
        <label className={labelCls}>Bonding</label>
        <input
          type="text"
          name="bonding"
          defaultValue={bonding}
          placeholder="A-060063-A"
          className={`${inputCls} w-44`}
        />
      </div>
      <div>
        <label className={labelCls}>Machine</label>
        <input
          type="text"
          name="machine"
          defaultValue={machine}
          placeholder="MTAI_WB158"
          className={`${inputCls} w-40`}
        />
      </div>

      <div>
        <label className={labelCls}>Mode</label>
        <input ref={modeRef} type="hidden" name="mode" defaultValue={mode} />
        {/* iOS-style segmented control */}
        <div className="inline-flex p-1 bg-ios-fill rounded-[10px]">
          <button type="button" className={segCls("")} onClick={() => pickMode("")}>
            All
          </button>
          <button
            type="button"
            className={segCls("mode1")}
            onClick={() => pickMode("mode1")}
          >
            Monitoring
          </button>
          <button
            type="button"
            className={segCls("mode2")}
            onClick={() => pickMode("mode2")}
          >
            Engineering
          </button>
        </div>
      </div>

      <button
        type="submit"
        className="h-9 px-5 rounded-full text-[13px] font-semibold text-white bg-brand-600 hover:bg-brand-700 active:bg-brand-800 shadow-ios-sm transition"
      >
        Apply
      </button>
      {active && (
        <a
          href="/"
          className="h-9 inline-flex items-center px-3 text-[13px] font-medium text-brand-600 hover:bg-brand-50 rounded-full transition"
        >
          Clear
        </a>
      )}
      <span className="ml-auto text-ios-footnote text-ios-label3">
        <span className="font-semibold tabular-nums text-ios-label">
          {matchCount}
        </span>{" "}
        match{matchCount === 1 ? "" : "es"}
      </span>
    </form>
  );
}
