import { NextResponse } from "next/server";
import fs from "node:fs";
import path from "node:path";
import sharp from "sharp";
import { SHARE_ROOT } from "@/lib/settings";

export const dynamic = "force-dynamic";

const TIFF_EXT = new Set([".tif", ".tiff"]);
const MIME: Record<string, string> = {
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".png": "image/png",
  ".webp": "image/webp",
  ".gif": "image/gif",
};

export async function GET(req: Request) {
  const url = new URL(req.url);
  const rel = url.searchParams.get("path") || "";
  if (!rel) return new NextResponse("missing path", { status: 400 });

  const target = path.resolve(SHARE_ROOT, rel);
  // Path-traversal guard — refuse anything outside the share root.
  const relCheck = path.relative(SHARE_ROOT, target);
  if (relCheck.startsWith("..") || path.isAbsolute(relCheck)) {
    return new NextResponse("forbidden", { status: 403 });
  }

  let stat: fs.Stats;
  try {
    stat = fs.statSync(target);
  } catch {
    return new NextResponse("not found", { status: 404 });
  }
  if (!stat.isFile()) return new NextResponse("not found", { status: 404 });

  const ext = path.extname(target).toLowerCase();

  if (TIFF_EXT.has(ext)) {
    try {
      const jpg = await sharp(target)
        .resize({ width: 1200, height: 1200, fit: "inside" })
        .jpeg({ quality: 85 })
        .toBuffer();
      return new NextResponse(new Uint8Array(jpg), {
        headers: {
          "Content-Type": "image/jpeg",
          "Cache-Control": "public, max-age=3600",
          "Content-Disposition": `inline; filename="${path.basename(target, ext)}.jpg"`,
        },
      });
    } catch (err) {
      console.error("TIFF preview failed for", target, err);
      return new NextResponse("conversion error", { status: 500 });
    }
  }

  const mime = MIME[ext] || "application/octet-stream";
  const buf = fs.readFileSync(target);
  return new NextResponse(new Uint8Array(buf), {
    headers: {
      "Content-Type": mime,
      "Cache-Control": "public, max-age=3600",
    },
  });
}
