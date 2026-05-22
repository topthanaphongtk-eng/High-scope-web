import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});

const display = Inter({
  subsets: ["latin"],
  variable: "--font-display",
  weight: ["600", "700", "800"],
  display: "swap",
});

const mono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "High Scope Monitor",
  description: "Read-only image gallery for confirmed wire-bond captures.",
  icons: {
    icon: {
      url:
        "data:image/svg+xml;utf8," +
        encodeURIComponent(
          `<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'><defs><linearGradient id='g' x1='0' y1='0' x2='1' y2='1'><stop offset='0' stop-color='#0E3689'/><stop offset='1' stop-color='#0A2660'/></linearGradient></defs><rect width='64' height='64' rx='14' fill='url(#g)'/><circle cx='52' cy='14' r='6' fill='#FFD53A'/><text x='32' y='44' font-size='38' text-anchor='middle' font-family='Apple Color Emoji,Segoe UI Emoji,Noto Color Emoji'>🔬</text></svg>`,
        ),
      type: "image/svg+xml",
    },
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${display.variable} ${mono.variable}`}
    >
      <body className="font-sans">
        {/* Frosted iOS-style nav bar */}
        <header className="sticky top-0 z-30 bg-white/72 backdrop-blur-ios backdrop-saturate-150 ios-hairline">
          <div className="max-w-6xl mx-auto px-5 h-12 flex items-center gap-4">
            <a href="/" className="flex items-center gap-2 group">
              <span
                className="grid place-items-center w-7 h-7 rounded-[8px] text-white text-[14px] shadow-ios-sm"
                style={{
                  background:
                    "linear-gradient(135deg, #0E3689 0%, #0A2660 100%)",
                }}
              >
                🔬
              </span>
              <span className="font-display font-semibold text-[15px] tracking-tight text-ios-label group-hover:text-brand-600 transition-colors">
                High Scope
              </span>
            </a>
            <nav className="flex items-center gap-1">
              <a
                href="/"
                className="px-3 py-1 text-[13px] font-medium text-brand-600 rounded-full hover:bg-brand-50 transition-colors"
              >
                Dashboard
              </a>
            </nav>
            <span className="ml-auto text-ios-caption2 text-ios-label3 hidden sm:flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
              Live · read-only
            </span>
          </div>
        </header>

        <main className="max-w-6xl mx-auto px-5 pt-6 pb-16">{children}</main>

        <footer className="max-w-6xl mx-auto px-5 py-8 text-ios-caption2 text-ios-label3 text-center">
          High Scope Monitor · captures DB owned by the desktop app · this view
          is read-only.
        </footer>
      </body>
    </html>
  );
}
