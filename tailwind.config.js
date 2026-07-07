export default {
  content: ["./index.html", "./src/**/*.{js,jsx,ts,tsx}"],
  theme: {
    fontSize: {
      xs: ["10px", { lineHeight: "1rem" }],
      sm: ["12px", { lineHeight: "1.35rem" }],
      base: ["14px", { lineHeight: "1.6rem" }],
      lg: ["16px", { lineHeight: "1.8rem" }],
      xl: ["18px", { lineHeight: "2rem" }],
      "2xl": ["22px", { lineHeight: "2.25rem" }],
      "3xl": ["28px", { lineHeight: "2.5rem" }],
    },
    extend: {
      colors: {
        ink: "#ffffff",
        muted: "#c4c4c4",
        line: "#292929",
        canvas: "#050505",
        panel: "#090909",
        chat: "#070707",
        midnight: "#050505",
        surface: {
          DEFAULT: "#0b0b0b",
          elevated: "#111111",
          hover: "#1a1a1a",
        },
        teal: {
          DEFAULT: "#d4d4d4",
          light: "#a3a3a3",
          bright: "#ffffff",
        },
        worktual: {
          50: "#111111",
          100: "#1a1a1a",
          300: "#525252",
          500: "#a3a3a3",
          600: "#d4d4d4",
          700: "#ffffff",
        },
      },
      boxShadow: {
        text: "0 1px 2px rgba(0, 0, 0, 0.9), 0 0 12px rgba(0, 0, 0, 0.35)",
      },
    },
  },
  plugins: [],
};
