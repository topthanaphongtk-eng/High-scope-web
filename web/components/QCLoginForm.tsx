"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";

const inputCls =
  "h-11 px-3.5 w-full text-[15px] bg-ios-fill rounded-[10px] border-0 " +
  "text-ios-label placeholder:text-ios-label3 " +
  "focus:outline-none focus:ring-2 focus:ring-brand-500/30 transition";

export default function QCLoginForm({ next }: { next: string }) {
  const router = useRouter();
  const [badge, setBadge] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErr("");
    setBusy(true);
    try {
      const res = await fetch("/api/qc/login", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ badge: badge.trim() }),
      });
      if (res.ok) {
        router.push(next);
        router.refresh();
        return;
      }
      const d = (await res.json().catch(() => ({}))) as { error?: string };
      setErr(
        res.status === 404
          ? "Badge not registered — register first."
          : d.error ?? "Login failed.",
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
        <div className="text-4xl mb-2">🔬</div>
        <h2 className="font-display text-ios-title2 font-bold text-ios-label">
          QC sign in
        </h2>
        <p className="text-ios-footnote text-ios-label3 mt-1">
          Enter your operator badge to start reviewing.
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

      {err && (
        <p className="text-ios-footnote text-red-600 mt-3">{err}</p>
      )}

      <button
        type="submit"
        disabled={busy || !badge.trim()}
        className="mt-5 h-11 w-full rounded-full text-[15px] font-semibold text-white bg-brand-600 hover:bg-brand-700 active:bg-brand-800 shadow-ios-sm transition disabled:opacity-40"
      >
        {busy ? "Signing in…" : "Sign in"}
      </button>

      <p className="text-center text-ios-footnote text-ios-label3 mt-4">
        New operator?{" "}
        <Link href="/qc/register" className="text-brand-600 font-medium hover:underline">
          Register
        </Link>
      </p>
    </form>
  );
}
