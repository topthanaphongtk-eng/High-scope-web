import QCLoginForm from "@/components/QCLoginForm";

export const dynamic = "force-dynamic";
export const metadata = { title: "QC sign in · High Scope Monitor" };

export default async function QCLoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string }>;
}) {
  const sp = await searchParams;
  // Only allow same-app QC redirects (no open redirect).
  const next = sp.next && sp.next.startsWith("/qc") ? sp.next : "/qc";
  return <QCLoginForm next={next} />;
}
