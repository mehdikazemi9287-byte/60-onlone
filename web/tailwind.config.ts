import type { Config } from "tailwindcss";

// Vambi palette (Figma file "Vambi — Logo").
const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: { extend: { colors: { brand: { navy: "#102B7A", blue: "#1748C9", orange: "#FF8A00", mist: "#F5F7FD" } } } },
  plugins: [],
};
export default config;
