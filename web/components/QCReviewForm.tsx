"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import QCItemControl from "./QCItemControl";
import type { Grade, QcReview } from "@/lib/types";

// Local date formatter — this is a client component, so it must not import
// lib/format (which pulls in node:path / node:fs via toImageUrl + settings).
function fmtWhen(s: string): string {
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return s;
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

export default function QCReviewForm({
  captureId,
  existing,
}: {
  captureId: string;
  existing: QcReview | null;
}) {
  const router = useRouter();
  const [ball, setBall] = useState<Grade | null>(existing?.ball_size ?? null);
  const [ballNote, setBallNote] = useState(existing?.ball_size_note ?? "");
  const [pad, setPad] = useState<Grade | null>(existing?.pad_bond ?? null);
  const [padNote, setPadNote] = useState(existing?.pad_bond_note ?? "");
  const [weld, setWeld] = useState<Grade | null>(existing?.weld_damage ?? null);
  const [weldNote, setWeldNote] = useState(existing?.weld_damage_note ?? "");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const allSet = ball && pad && weld;
  const overall: Grade | null = !allSet
    ? null
    : ball === "REJECT" || pad === "REJECT" || weld === "REJECT"
      ? "REJECT"
      : "PASS";
  const rejected = [
    ball === "REJECT" && "Ball size",
    pad === "REJECT" && "Bond of pad",
    weld === "REJECT" && "Weld damage",
  ].filter(Boolean) as string[];

  async function submit() {
    setErr("");
    setBusy(true);
    try {
      const res = await fetch("/api/qc/review", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          captureId,
          ball_size: ball,
          ball_size_note: ballNote.trim() || null,
          pad_bond: pad,
          pad_bond_note: padNote.trim() || null,
          weld_damage: weld,
          weld_damage_note: weldNote.trim() || null,
        }),
      });
      if (res.ok) {
        router.push("/qc");
        router.refresh();
        return;
      }
      const d = (await res.json().catch(() => ({}))) as { error?: string };
      setErr(d.error ?? "Save failed.");
    } catch {
      setErr("Network error — is the server reachable?");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3">
      {existing && (
        <div className="p-3 rounded-[12px] bg-accent-400/15 text-amber-800 text-ios-footnote">
          Already reviewed by{" "}
          <span className="font-semibold font-mono">{existing.badge_number}</span>{" "}
          at {fmtWhen(existing.reviewed_at)} — submitting will overwrite it.
        </div>
      )}

      <QCItemControl label="Ball size" value={ball} note={ballNote} onValue={setBall} onNote={setBallNote} />
      <QCItemControl label="Bond of pad" value={pad} note={padNote} onValue={setPad} onNote={setPadNote} />
      <QCItemControl label="Weld damage" value={weld} note={weldNote} onValue={setWeld} onNote={setWeldNote} />

      {/* live overall verdict */}
      <div
        className={
          "p-4 rounded-ios-lg text-center font-display font-bold text-ios-title3 " +
          (overall === "PASS"
            ? "bg-emerald-500/15 text-emerald-700"
            : overall === "REJECT"
              ? "bg-red-500/15 text-red-700"
              : "bg-ios-fill text-ios-label3")
        }
      >
        {overall === "PASS" && "Overall: PASS"}
        {overall === "REJECT" && `Overall: REJECT — ${rejected.join(", ")}`}
        {overall === null && "Grade all three items to set the verdict"}
      </div>

      {err && <p className="text-ios-footnote text-red-600">{err}</p>}

      <button
        onClick={submit}
        disabled={busy || !allSet}
        className="h-11 w-full rounded-full text-[15px] font-semibold text-white bg-brand-600 hover:bg-brand-700 active:bg-brand-800 shadow-ios-sm transition disabled:opacity-40"
      >
        {busy ? "Saving…" : existing ? "Update review" : "Submit review"}
      </button>
    </div>
  );
}
