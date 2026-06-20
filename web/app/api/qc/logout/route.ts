import { NextResponse } from "next/server";
import { QC_AID_COOKIE, QC_COOKIE } from "@/lib/qc-session";

export const dynamic = "force-dynamic";

export async function POST() {
  const res = NextResponse.json({ ok: true });
  res.cookies.delete(QC_COOKIE);
  res.cookies.delete(QC_AID_COOKIE);
  return res;
}
