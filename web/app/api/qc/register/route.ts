import { NextResponse } from "next/server";
import { findOperator, registerOperator } from "@/lib/qc-db";
import { QC_COOKIE, QC_COOKIE_MAX_AGE } from "@/lib/qc-session";

export const dynamic = "force-dynamic";

// Badge domain matches captures.operator_badge (e.g. "B19277").
const BADGE_RE = /^[A-Za-z0-9._-]{1,32}$/;

export async function POST(req: Request) {
  let body: { badge?: string; full_name?: string };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "bad request" }, { status: 400 });
  }
  const badge = (body.badge ?? "").trim();
  const fullName = (body.full_name ?? "").trim();
  if (!BADGE_RE.test(badge)) {
    return NextResponse.json(
      { error: "badge must be 1–32 chars (letters, digits, . _ -)" },
      { status: 422 },
    );
  }
  if (!fullName || fullName.length > 255) {
    return NextResponse.json(
      { error: "full name required (max 255 chars)" },
      { status: 422 },
    );
  }

  const { created } = await registerOperator(badge, fullName);
  if (!created) {
    return NextResponse.json(
      { error: "badge already registered" },
      { status: 409 },
    );
  }
  const operator = await findOperator(badge);
  const res = NextResponse.json({ ok: true, operator });
  res.cookies.set(QC_COOKIE, badge, {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    secure: process.env.NODE_ENV === "production",
    maxAge: QC_COOKIE_MAX_AGE,
  });
  return res;
}
