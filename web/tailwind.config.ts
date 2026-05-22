import type { Config } from "tailwindcss";

export default {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // High Scope navy (kept) acting as iOS tintColor
        brand: {
          50: "#f0f3fb",
          100: "#dde4f5",
          200: "#bac9ec",
          300: "#8aa1dc",
          400: "#5979c8",
          500: "#2b56b3",
          600: "#0E3689",
          700: "#0a2a6d",
          800: "#081e51",
          900: "#061538",
        },
        // High Scope yellow accent — used sparingly like SF Symbol tint
        accent: {
          400: "#FFD53A",
          500: "#f5c106",
          600: "#caa006",
        },
        // iOS surface system
        ios: {
          bg: "#f2f2f7",         // systemGroupedBackground
          surface: "#ffffff",     // systemBackground
          elevated: "#ffffff",
          fill: "#7878801f",      // tertiaryFill
          fill2: "#78788028",
          separator: "#3c3c4322", // ~12% opacity
          label: "#1d1d1f",
          label2: "#3c3c4399",    // secondary
          label3: "#3c3c434c",    // tertiary
          label4: "#3c3c4326",    // quaternary
        },
      },
      fontFamily: {
        sans: [
          "var(--font-sans)",
          "-apple-system",
          "BlinkMacSystemFont",
          "SF Pro Text",
          "system-ui",
          "sans-serif",
        ],
        display: [
          "var(--font-display)",
          "-apple-system",
          "BlinkMacSystemFont",
          "SF Pro Display",
          "system-ui",
          "sans-serif",
        ],
        mono: [
          "var(--font-mono)",
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "monospace",
        ],
      },
      fontSize: {
        // iOS type ramp
        "ios-largeTitle": ["2.125rem", { lineHeight: "2.5rem", letterSpacing: "-0.02em", fontWeight: "700" }],
        "ios-title1": ["1.75rem", { lineHeight: "2.125rem", letterSpacing: "-0.015em", fontWeight: "700" }],
        "ios-title2": ["1.375rem", { lineHeight: "1.75rem", letterSpacing: "-0.01em", fontWeight: "700" }],
        "ios-title3": ["1.25rem", { lineHeight: "1.5rem", fontWeight: "600" }],
        "ios-headline": ["1.0625rem", { lineHeight: "1.375rem", fontWeight: "600" }],
        "ios-body": ["1.0625rem", { lineHeight: "1.375rem" }],
        "ios-callout": ["1rem", { lineHeight: "1.3125rem" }],
        "ios-subhead": ["0.9375rem", { lineHeight: "1.25rem" }],
        "ios-footnote": ["0.8125rem", { lineHeight: "1.125rem" }],
        "ios-caption": ["0.75rem", { lineHeight: "1rem" }],
        "ios-caption2": ["0.6875rem", { lineHeight: "0.8125rem" }],
      },
      borderRadius: {
        "ios": "0.875rem",  // 14px — iOS card radius
        "ios-lg": "1.25rem", // 20px — bigger cards
        "ios-xl": "1.5rem",  // 24px
      },
      boxShadow: {
        // Soft iOS-style elevation
        "ios-sm": "0 1px 2px rgba(0,0,0,0.04), 0 1px 3px rgba(0,0,0,0.04)",
        "ios": "0 2px 8px -2px rgba(0,0,0,0.06), 0 1px 3px rgba(0,0,0,0.04)",
        "ios-md": "0 8px 24px -8px rgba(14,54,137,0.12), 0 2px 6px rgba(0,0,0,0.04)",
        "ios-lg": "0 16px 40px -12px rgba(14,54,137,0.18), 0 4px 8px rgba(0,0,0,0.04)",
      },
      backdropBlur: {
        ios: "20px",
      },
    },
  },
  plugins: [],
} satisfies Config;
