import { NextResponse } from "next/server";
import {
  QC_AID_COOKIE,
  QC_COOKIE_MAX_AGE,
  currentOperator,
} from "@/lib/qc-session";
import { recordAcknowledgement } from "@/lib/qc-db";

export const dynamic = "force-dynamic";

export async function POST() {
  const op = await currentOperator();
  if (!op) {
    return NextResponse.json({ error: "not signed in" }, { status: 401 });
  }
  await recordAcknowledgement(op.badge_number);
  const res = NextResponse.json({ ok: true });
  res.cookies.set(QC_AID_COOKIE, new Date().toISOString(), {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    secure: process.env.NODE_ENV === "production",
    maxAge: QC_COOKIE_MAX_AGE,
  });
  return res;
}
