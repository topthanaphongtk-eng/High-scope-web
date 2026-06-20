import { NextResponse } from "next/server";
import { currentOperator } from "@/lib/qc-session";
import { QcNotFoundError, submitReview } from "@/lib/qc-db";
import type { Grade } from "@/lib/types";

export const dynamic = "force-dynamic";

const isGrade = (v: unknown): v is Grade => v === "PASS" || v === "REJECT";

/** Trim + validate a note: empty -> null; over 512 -> error (never truncate a
 * QC note silently). Returns the cleaned string, null, or false on overflow. */
function cleanNote(v: unknown): string | null | false {
  if (v == null) return null;
  if (typeof v !== "string") return false;
  const s = v.trim();
  if (!s) return null;
  if (s.length > 512) return false;
  return s;
}

export async function POST(req: Request) {
  // Self-guard — never rely on middleware for API routes. Badge comes from the
  // session, never the request body.
  const op = await currentOperator();
  if (!op) {
    return NextResponse.json({ error: "not signed in" }, { status: 401 });
  }

  let body: Record<string, unknown>;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "bad request" }, { status: 400 });
  }

  const captureId = typeof body.captureId === "string" ? body.captureId : "";
  if (!captureId) {
    return NextResponse.json({ error: "captureId required" }, { status: 400 });
  }
  if (!isGrade(body.ball_size) || !isGrade(body.pad_bond) || !isGrade(body.weld_damage)) {
    return NextResponse.json(
      { error: "each item must be PASS or REJECT" },
      { status: 422 },
    );
  }
  const ballNote = cleanNote(body.ball_size_note);
  const padNote = cleanNote(body.pad_bond_note);
  const weldNote = cleanNote(body.weld_damage_note);
  if (ballNote === false || padNote === false || weldNote === false) {
    return NextResponse.json(
      { error: "notes must be 512 characters or fewer" },
      { status: 422 },
    );
  }

  try {
    const review = await submitReview(op.badge_number, captureId, {
      ball_size: body.ball_size,
      ball_size_note: ballNote,
      pad_bond: body.pad_bond,
      pad_bond_note: padNote,
      weld_damage: body.weld_damage,
      weld_damage_note: weldNote,
    });
    return NextResponse.json({ ok: true, review });
  } catch (e) {
    if (e instanceof QcNotFoundError) {
      return NextResponse.json({ error: "capture not found" }, { status: 404 });
    }
    console.error("qc review submit failed:", e);
    return NextResponse.json({ error: "could not save review" }, { status: 500 });
  }
}
