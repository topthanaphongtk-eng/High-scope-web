import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { currentOperator } from "@/lib/qc-session";
import { captureById } from "@/lib/capture-db";
import { getReview } from "@/lib/qc-db";
import { decorate } from "@/lib/decorate";
import { fmtDt } from "@/lib/format";
import QCReviewForm from "@/components/QCReviewForm";

export const dynamic = "force-dynamic";

export default async function ReviewPage({
  params,
}: {
  params: Promise<{ captureId: string }>;
}) {
  const op = await currentOperator();
  if (!op) redirect("/qc/login");

  const { captureId } = await params;
  const capture = await captureById(captureId);
  if (!capture) notFound();
  decorate(capture);
  const existing = await getReview(captureId);

  return (
    <div className="max-w-3xl mx-auto">
      <Link
        href="/qc"
        className="inline-block mb-3 text-ios-footnote text-brand-600 hover:underline"
      >
        ← Back to queue
      </Link>

      {/* capture header */}
      <div className="mb-4 p-4 bg-ios-surface rounded-ios-lg shadow-ios">
        <div className="font-mono text-ios-title3 font-bold text-brand-600 truncate">
          {capture.lot_id}
        </div>
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-ios-caption mt-1.5 text-ios-label2">
          <span><span className="text-ios-label3">Package</span> <b className="text-ios-label">{capture.package || "—"}</b></span>
          <span className="text-ios-label4">·</span>
          <span><span className="text-ios-label3">Machine</span> <b className="text-ios-label">{capture.lot_location || "—"}</b></span>
          <span className="text-ios-label4">·</span>
          <span><span className="text-ios-label3">Bonding</span> <b className="text-ios-label">{capture.bonding_number || "—"}</b></span>
          <span className="text-ios-label4">·</span>
          <span className="font-mono">{fmtDt(capture.confirmed_at)}</span>
        </div>
      </div>

      {/* image gallery */}
      {capture.files.length === 0 ? (
        <div className="mb-4 p-6 text-center bg-ios-surface rounded-ios-lg shadow-ios text-ios-footnote text-ios-label3">
          No images saved for this capture — grade from available context, or
          escalate the missing-image issue.
        </div>
      ) : (
        <div
          className="mb-4 grid gap-2"
          style={{
            gridTemplateColumns: `repeat(${Math.min(capture.files.length, 3)}, minmax(0, 1fr))`,
          }}
        >
          {capture.files.map((f, i) => (
            <div key={i} className="space-y-1.5">
              <div className="aspect-[4/3] bg-slate-900 rounded-[12px] overflow-hidden ring-1 ring-black/5">
                {f.image_rel && (
                  <img
                    src={`/image?path=${encodeURIComponent(f.image_rel)}`}
                    alt={f.slot}
                    className="w-full h-full object-contain"
                  />
                )}
              </div>
              <div className="text-center text-ios-caption text-ios-label2 font-medium">
                {f.slot}
              </div>
            </div>
          ))}
        </div>
      )}

      <QCReviewForm captureId={captureId} existing={existing} />
    </div>
  );
}
