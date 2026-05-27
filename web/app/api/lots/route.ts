import { NextResponse } from "next/server";
import { allLots } from "@/lib/capture-db";

export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  const url = new URL(req.url);
  const limit = Number(url.searchParams.get("limit") || 200);
  const lots = await allLots(Number.isFinite(limit) ? limit : 200);
  return NextResponse.json(lots);
}
