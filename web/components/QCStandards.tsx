// Visual Aid QC — acceptance criteria from "Visual QC.pptx" (Thai).
// Left = Accept example, Right = Reject example, per item.
const CRITERIA = [
  {
    key: "bond-size",
    title: "Bond Over size",
    th: "ลูกบอลต้องกลมสมส่วน ด้านบนและด้านซ้าย-ขวาต้องมองเห็นพื้นสีขาวของ Pad",
    accept: "/qc-standards/bond-size-accept.png",
    reject: "/qc-standards/bond-size-reject.png",
  },
  {
    key: "centering",
    title: "Bond Not centering",
    th: "ลูกบอลต้องอยู่ตรงกลางถูกต้องตาม bonding diagram ไม่ชิดขอบ Pad",
    accept: "/qc-standards/centering-accept.png",
    reject: "/qc-standards/centering-reject.png",
  },
  {
    key: "weld",
    title: "Weld Damage",
    th: "Weld ต้องสมส่วน ไม่มีลักษณะแตกหรือมีรอยของการ crack",
    accept: "/qc-standards/weld-accept.png",
    reject: "/qc-standards/weld-reject.png",
  },
];

function Example({ src, kind }: { src: string; kind: "accept" | "reject" }) {
  const ok = kind === "accept";
  return (
    <div
      className={
        "rounded-2xl overflow-hidden ring-1 " +
        (ok ? "ring-emerald-400/50" : "ring-red-400/50")
      }
    >
      <div
        className={
          "flex items-center justify-center px-2.5 py-1 text-[11px] font-bold " +
          (ok ? "bg-emerald-500/20 text-emerald-700" : "bg-red-500/20 text-red-700")
        }
      >
        {ok ? "✓ Accept" : "✗ Reject"}
      </div>
      <div className="bg-slate-900 aspect-[4/3] grid place-items-center">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={src} alt={kind} className="w-full h-full object-contain" />
      </div>
    </div>
  );
}

export default function QCStandards({ operatorName }: { operatorName: string }) {
  return (
    <div>
      <p className="text-ios-footnote text-ios-label2 mb-4">
        <b className="text-ios-label">{operatorName}</b> — โปรดตรวจสอบเกณฑ์คุณภาพด้านล่าง
        แล้วกด <b>ยอมรับ</b> ก่อนเริ่มตรวจงาน เทียบทุก capture กับตัวอย่าง
        Accept / Reject เหล่านี้
      </p>
      <div className="space-y-3.5">
        {CRITERIA.map((c) => (
          <div
            key={c.key}
            className="p-4 rounded-2xl bg-white/55 ring-1 ring-white/60"
          >
            <h3 className="text-ios-headline text-ios-label">{c.title}</h3>
            <p className="text-ios-footnote text-ios-label2 mt-0.5 mb-3">{c.th}</p>
            <div className="grid grid-cols-2 gap-3">
              <Example src={c.accept} kind="accept" />
              <Example src={c.reject} kind="reject" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
