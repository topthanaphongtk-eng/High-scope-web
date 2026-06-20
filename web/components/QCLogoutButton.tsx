"use client";

import { useRouter } from "next/navigation";

export default function QCLogoutButton() {
  const router = useRouter();
  async function logout() {
    await fetch("/api/qc/logout", { method: "POST" });
    router.push("/qc/login");
    router.refresh();
  }
  return (
    <button
      onClick={logout}
      className="px-3 py-1 text-[13px] font-medium text-ios-label2 hover:text-red-600 rounded-full hover:bg-red-50 transition"
    >
      Sign out
    </button>
  );
}
