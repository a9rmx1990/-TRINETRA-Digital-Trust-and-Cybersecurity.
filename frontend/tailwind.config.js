/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Public Sans"', "system-ui", "sans-serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "monospace"],
      },
      colors: {
        // Customer workspace
        canvas: "rgb(var(--ui-canvas) / <alpha-value>)",
        ink: "rgb(var(--ui-ink) / <alpha-value>)",
        muted: "rgb(var(--ui-muted) / <alpha-value>)",
        line: "rgb(var(--ui-line) / <alpha-value>)",
        primary: {
          DEFAULT: "rgb(var(--ui-blue) / <alpha-value>)",
          hover: "rgb(var(--ui-blue-hover) / <alpha-value>)",
          soft: "rgb(var(--ui-sky) / <alpha-value>)",
        },
        ok: { DEFAULT: "#17734A", soft: "#E6F3EC" },
        warn: { DEFAULT: "#8A5300", soft: "#FBF1DF" },
        bad: { DEFAULT: "#B42318", soft: "#FBEAE8" },
        // SOC workspace
        soc: {
          canvas: "rgb(var(--ui-canvas) / <alpha-value>)",
          panel: "#FFFFFF",
          raised: "rgb(var(--ui-sky) / <alpha-value>)",
          line: "rgb(var(--ui-line) / <alpha-value>)",
          ink: "rgb(var(--ui-ink) / <alpha-value>)",
          muted: "rgb(var(--ui-muted) / <alpha-value>)",
          faint: "#526A81",
          amber: "rgb(var(--ui-amber) / <alpha-value>)",
          red: "rgb(var(--ui-red) / <alpha-value>)",
          slate: "rgb(var(--ui-blue) / <alpha-value>)",
        },
      },
      fontSize: {
        xs: ["0.75rem", { lineHeight: "1.1rem" }],
        sm: ["0.8125rem", { lineHeight: "1.25rem" }],
        base: ["0.9375rem", { lineHeight: "1.5rem" }],
        lg: ["1.125rem", { lineHeight: "1.6rem" }],
        xl: ["1.375rem", { lineHeight: "1.8rem" }],
        "2xl": ["1.75rem", { lineHeight: "2.1rem" }],
        "3xl": ["2.25rem", { lineHeight: "2.6rem" }],
      },
    },
  },
  plugins: [],
};
