import Link from "next/link";
import { cookies } from "next/headers";
import { QC_AID_COOKIE, currentOperator } from "@/lib/qc-session";
import QCLogoutButton from "@/components/QCLogoutButton";
import QCStandardsModal from "@/components/QCStandardsModal";

export const dynamic = "force-dynamic";

export const metadata = {
  title: "QC Mode · High Scope Monitor",
};

export default async function QCLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const op = await currentOperator();
  const acknowledged = op
    ? !!(await cookies()).get(QC_AID_COOKIE)?.value
    : false;
  return (
    <div>
      <div className="mb-6 flex items-center gap-4 flex-wrap">
        <div className="flex items-center gap-2">
          <span
            className="grid place-items-center w-7 h-7 rounded-[8px] text-white text-[14px] shadow-ios-sm"
            style={{ background: "linear-gradient(135deg,#0E3689 0%,#0A2660 100%)" }}
          >
            ✓
          </span>
          <h1 className="font-display text-ios-title1 text-ios-label">QC Mode</h1>
        </div>

        {op && (
          <nav className="flex items-center gap-1">
            <Link
              href="/qc"
              className="px-3 py-1 text-[13px] font-medium text-brand-600 rounded-full hover:bg-brand-50 transition"
            >
              Queue
            </Link>
            <Link
              href="/qc/summary"
              className="px-3 py-1 text-[13px] font-medium text-brand-600 rounded-full hover:bg-brand-50 transition"
            >
              Summary
            </Link>
            <QCStandardsModal
              acknowledged={acknowledged}
              operatorName={op.full_name}
            />
          </nav>
        )}

        <div className="ml-auto flex items-center gap-2">
          {op ? (
            <>
              <span className="text-ios-footnote text-ios-label2">
                {op.full_name}{" "}
                <span className="text-ios-label3">({op.badge_number})</span>
              </span>
              <QCLogoutButton />
            </>
          ) : (
            <Link
              href="/"
              className="text-ios-footnote text-brand-600 hover:underline"
            >
              ← Back to gallery
            </Link>
          )}
        </div>
      </div>

      {children}
    </div>
  );
}
