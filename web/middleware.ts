import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Cheap Edge gate for /qc/* PAGES only: is the badge cookie present?
// Full validation (badge still exists + active) happens in Node-runtime pages
// and API routes via currentOperator(). Cookie name is inlined because this
// runs on the Edge runtime and must not import qc-session (which pulls in pg).
const QC_COOKIE = "qc_badge";
const PUBLIC = ["/qc/login", "/qc/register"];

export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
  if (PUBLIC.some((p) => pathname === p || pathname.startsWith(p + "/"))) {
    return NextResponse.next();
  }
  // Must be signed in. The Visual Aid acceptance gate is enforced by the
  // floating modal in the QC layout (shown until the operator accepts).
  if (!req.cookies.get(QC_COOKIE)?.value) {
    const url = req.nextUrl.clone();
    url.pathname = "/qc/login";
    url.searchParams.set("next", pathname);
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

// Pages only — API routes self-guard with currentOperator().
export const config = {
  matcher: ["/qc/:path*"],
};
