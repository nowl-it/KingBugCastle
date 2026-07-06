import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{js,ts,jsx,tsx}", "./components/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        base: { bg: "#0d1117", side: "#161b22", card: "#161b22", hover: "#1c2128", border: "#30363d" },
        accent: { DEFAULT: "#58a6ff", hover: "#79c0ff" },
        muted: "#8b949e", dim: "#484f58", success: "#3fb950", danger: "#f85149",
      },
      fontFamily: { mono: ["SF Mono", "Fira Code", "Cascadia Code", "monospace"] },
    },
  },
  plugins: [],
};

export default config;
