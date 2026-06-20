import { cookies } from "next/headers";
import { findOperator } from "./qc-db";
import type { QcOperator } from "./types";

export const QC_COOKIE = "qc_badge";
// Set when the operator accepts the Visual Aid QC criteria. Cleared on
// login/logout so every login must re-accept.
export const QC_AID_COOKIE = "qc_aid_ack";
// One shift; re-login after. (maxAge counts from login, not shift start.)
export const QC_COOKIE_MAX_AGE = 12 * 60 * 60; // seconds

/**
 * Resolve the logged-in QC operator from the badge cookie, re-validating
 * against the DB on every call — the cookie is only a hint, never trusted
 * alone, so a removed/deactivated badge stops working immediately.
 * Returns null when there is no cookie or the badge is unknown/inactive.
 */
export async function currentOperator(): Promise<QcOperator | null> {
  const store = await cookies();
  const badge = store.get(QC_COOKIE)?.value;
  if (!badge) return null;
  return findOperator(badge);
}
