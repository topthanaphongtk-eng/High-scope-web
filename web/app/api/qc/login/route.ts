import { NextResponse } from "next/server";
import { findOperator } from "@/lib/qc-db";
import { QC_AID_COOKIE, QC_COOKIE, QC_COOKIE_MAX_AGE } from "@/lib/qc-session";

export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  let body: { badge?: string };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "bad request" }, { status: 400 });
  }
  const badge = (body.badge ?? "").trim();
  if (!badge) {
    return NextResponse.json({ error: "badge required" }, { status: 400 });
  }
  const operator = await findOperator(badge);
  if (!operator) {
    return NextResponse.json({ error: "badge not registered" }, { status: 404 });
  }
  const res = NextResponse.json({ ok: true, operator });
  res.cookies.set(QC_COOKIE, operator.badge_number, {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    secure: process.env.NODE_ENV === "production",
    maxAge: QC_COOKIE_MAX_AGE,
  });
  // Force re-accepting the Visual Aid criteria on every login.
  res.cookies.delete(QC_AID_COOKIE);
  return res;
}
