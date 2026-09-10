/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: { 950: "#0b0e13", 900: "#0f131a", 850: "#131924", 800: "#18202c", 700: "#223041", 600: "#2e4054" },
        line: "#243040",
        cad: { orange: "#e0762a", red: "#d64533", blue: "#4d8fd1", green: "#4fa37a", amber: "#c9a227" },
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
        sans: ["Inter", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
      },
    },
  },
  plugins: [],
};
