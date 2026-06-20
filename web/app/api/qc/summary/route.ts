import { NextResponse } from "next/server";
import { currentOperator } from "@/lib/qc-session";
import { dailyPackageSummary } from "@/lib/qc-db";

export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  const op = await currentOperator();
  if (!op) {
    return NextResponse.json({ error: "not signed in" }, { status: 401 });
  }
  const date = new URL(req.url).searchParams.get("date");
  const m = date?.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  const now = new Date();
  const day = m
    ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
    : new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const nextDay = new Date(day.getFullYear(), day.getMonth(), day.getDate() + 1);
  const data = await dailyPackageSummary(day, nextDay);
  return NextResponse.json({
    date: `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, "0")}-${String(day.getDate()).padStart(2, "0")}`,
    data,
  });
}
