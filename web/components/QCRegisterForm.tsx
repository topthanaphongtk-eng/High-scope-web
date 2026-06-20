"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";

const inputCls =
  "h-11 px-3.5 w-full text-[15px] bg-ios-fill rounded-[10px] border-0 " +
  "text-ios-label placeholder:text-ios-label3 " +
  "focus:outline-none focus:ring-2 focus:ring-brand-500/30 transition";

export default function QCRegisterForm() {
  const router = useRouter();
  const [badge, setBadge] = useState("");
  const [fullName, setFullName] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErr("");
    setBusy(true);
    try {
      const res = await fetch("/api/qc/register", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ badge: badge.trim(), full_name: fullName.trim() }),
      });
      if (res.ok) {
        router.push("/qc");
        router.refresh();
        return;
      }
      const d = (await res.json().catch(() => ({}))) as { error?: string };
      setErr(
        res.status === 409
          ? "That badge is already registered — sign in instead."
          : d.error ?? "Registration failed.",
      );
    } catch {
      setErr("Network error — is the server reachable?");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      onSubmit={onSubmit}
      className="max-w-sm mx-auto mt-10 p-6 bg-ios-surface rounded-ios-lg shadow-ios"
    >
      <div className="text-center mb-5">
        <div className="text-4xl mb-2">🪪</div>
        <h2 className="font-display text-ios-title2 font-bold text-ios-label">
          Register QC operator
        </h2>
        <p className="text-ios-footnote text-ios-label3 mt-1">
          One-time setup. Your badge identifies your reviews.
        </p>
      </div>

      <label className="block text-ios-caption2 font-semibold uppercase tracking-wider text-ios-label3 mb-1.5">
        Operator badge
      </label>
      <input
        autoFocus
        value={badge}
        onChange={(e) => setBadge(e.target.value)}
        placeholder="e.g.  B19277"
        className={inputCls}
      />

      <label className="block text-ios-caption2 font-semibold uppercase tracking-wider text-ios-label3 mb-1.5 mt-4">
        Full name
      </label>
      <input
        value={fullName}
        onChange={(e) => setFullName(e.target.value)}
        placeholder="e.g.  Somchai Jaidee"
        className={inputCls}
      />

      {err && <p className="text-ios-footnote text-red-600 mt-3">{err}</p>}

      <button
        type="submit"
        disabled={busy || !badge.trim() || !fullName.trim()}
        className="mt-5 h-11 w-full rounded-full text-[15px] font-semibold text-white bg-brand-600 hover:bg-brand-700 active:bg-brand-800 shadow-ios-sm transition disabled:opacity-40"
      >
        {busy ? "Registering…" : "Register & start"}
      </button>

      <p className="text-center text-ios-footnote text-ios-label3 mt-4">
        Already registered?{" "}
        <Link href="/qc/login" className="text-brand-600 font-medium hover:underline">
          Sign in
        </Link>
      </p>
    </form>
  );
}
