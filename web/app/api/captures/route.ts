import { NextResponse } from "next/server";
import { recentCaptures } from "@/lib/capture-db";
import { parseDate, parseUntil } from "@/lib/format";
import type { Mode } from "@/lib/types";

export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  const url = new URL(req.url);
  const since = parseDate(url.searchParams.get("since"));
  const until = parseUntil(url.searchParams.get("until"));
  const bonding = url.searchParams.get("bonding") || null;
  const machine = url.searchParams.get("machine") || null;
  const lotId = url.searchParams.get("lot") || null;
  const modeArg = url.searchParams.get("mode");
  const mode: Mode | null =
    modeArg === "mode1" || modeArg === "mode2" ? modeArg : null;
  const limitRaw = Number(url.searchParams.get("limit") || 500);
  const limit = Number.isFinite(limitRaw) ? limitRaw : 500;

  const captures = recentCaptures({
    since,
    until,
    bonding_number: bonding,
    lot_location: machine,
    lot_id: lotId,
    mode,
    limit,
  });

  return NextResponse.json({ count: captures.length, captures });
}
